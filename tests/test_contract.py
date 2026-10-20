"""Проверки работают с написанным вручную YAML-контрактом."""

import pytest
import schemathesis
import yaml
from hypothesis import HealthCheck, Phase, settings
from openapi_spec_validator import validate

pytestmark = pytest.mark.assignment

REQUIRED_OPERATIONS = {
    "/health": {"get"},
    "/orders/{order_id}": {"get"},
    "/refunds": {"get", "post"},
    "/refunds/{refund_id}": {"get"},
    "/refunds/{refund_id}/approve": {"post"},
    "/refunds/{refund_id}/reject": {"post"},
}
EXPECTED_RESPONSES = {
    ("/health", "get"): {"200"},
    ("/orders/{order_id}", "get"): {"200", "404", "422"},
    ("/refunds", "get"): {"200", "422"},
    ("/refunds", "post"): {"200", "201", "404", "409", "422"},
    ("/refunds/{refund_id}", "get"): {"200", "404", "422"},
    ("/refunds/{refund_id}/approve", "post"): {"200", "404", "409", "422"},
    ("/refunds/{refund_id}/reject", "post"): {"200", "404", "409", "422"},
}
ORDER_FIELDS = {"id", "amount", "currency", "status"}
REFUND_FIELDS = {"id", "order_id", "amount", "currency", "reason", "status", "created_at"}
CREATE_FIELDS = {"order_id", "amount", "currency", "reason"}
PAID_ORDER = "11111111-1111-4111-8111-111111111111"
SEEDED_REFUND = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def resolve(document, value):
    while "$ref" in value:
        reference = value["$ref"]
        assert reference.startswith("#/"), "Для задания используйте локальные $ref"
        value = document
        for part in reference[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def schema_view(document, schema):
    """Собрать поля allOf для проверки полноты, не меняя исходный контракт."""
    schema = resolve(document, schema)
    if "allOf" not in schema:
        return schema
    parts = [{key: value for key, value in schema.items() if key != "allOf"}]
    parts.extend(schema["allOf"])
    merged = {}
    for part in parts:
        for key, value in schema_view(document, part).items():
            if key == "required":
                merged[key] = sorted(set(merged.get(key, [])) | set(value))
            elif key == "properties":
                properties = dict(merged.get(key, {}))
                for name, definition in value.items():
                    properties[name] = (
                        {"allOf": [properties[name], definition]}
                        if name in properties
                        else definition
                    )
                merged[key] = properties
            elif key == "enum" and key in merged:
                merged[key] = [item for item in merged[key] if item in value]
            else:
                merged[key] = value
    return merged


def object_properties(document, schema, expected_fields):
    schema = schema_view(document, schema)
    assert schema.get("type") == "object", "Опишите тип объекта в схеме"
    properties = schema.get("properties", {})
    assert expected_fields <= set(properties), f"Добавьте поля: {sorted(expected_fields)}"
    assert expected_fields <= set(schema.get("required", [])), (
        f"Отметьте обязательные поля: {sorted(expected_fields)}"
    )
    assert all(schema_view(document, properties[name]) for name in expected_fields), (
        "Схемы полей не должны быть пустыми"
    )
    return properties


def check_payload_schemas(document):
    paths = document["paths"]
    for (path, method), codes in EXPECTED_RESPONSES.items():
        operation = paths[path][method]
        responses = operation["responses"]
        assert codes <= responses.keys(), f"Опишите ответы {sorted(codes)}: {method.upper()} {path}"
        for code in sorted(codes):
            response = resolve(document, responses[code])
            content = response.get("content", {}).get("application/json", {})
            assert "schema" in content, f"Добавьте JSON-схему для {method.upper()} {path}: {code}"
            if int(code) >= 400:
                fields = object_properties(document, content["schema"], {"error"})
                object_properties(document, fields["error"], {"code", "message"})
            elif path == "/health":
                fields = object_properties(document, content["schema"], {"status"})
                assert schema_view(document, fields["status"]).get("enum") == ["ok"]
            elif path == "/orders/{order_id}":
                fields = object_properties(document, content["schema"], ORDER_FIELDS)
                assert set(schema_view(document, fields["status"]).get("enum", [])) == {
                    "paid",
                    "unpaid",
                }
            elif path == "/refunds" and method == "get":
                fields = object_properties(
                    document, content["schema"], {"items", "total", "limit", "offset"}
                )
                items = schema_view(document, fields["items"])
                assert items.get("type") == "array", "items должен быть массивом заявок"
                object_properties(document, items.get("items", {}), REFUND_FIELDS)
            else:
                fields = object_properties(document, content["schema"], REFUND_FIELDS)
                allowed = {"pending", "approved", "rejected"}
                expected = allowed
                if path.endswith("/approve"):
                    expected = {"approved"}
                elif path.endswith("/reject"):
                    expected = {"rejected"}
                elif path == "/refunds" and code == "201":
                    expected = {"pending"}
                statuses = set(schema_view(document, fields["status"]).get("enum", []))
                assert expected <= statuses <= allowed, (
                    f"Проверьте статусы ответа {code} для {method.upper()} {path}"
                )
    body = resolve(document, paths["/refunds"]["post"].get("requestBody", {}))
    assert body.get("required") is True, "Для POST /refunds необходимо тело запроса"
    schema = body.get("content", {}).get("application/json", {}).get("schema", {})
    object_properties(document, schema, CREATE_FIELDS)


def read_complete_contract(contract_path):
    with contract_path.open(encoding="utf-8") as source:
        document = yaml.safe_load(source)
    assert isinstance(document, dict), "В contracts/openapi.yaml должен быть OpenAPI-документ"
    assert str(document.get("openapi", "")).startswith("3.0."), "Используйте OpenAPI 3.0"
    paths = document.get("paths", {})
    missing = [
        f"{method.upper()} {path}"
        for path, methods in REQUIRED_OPERATIONS.items()
        for method in sorted(methods)
        if method not in paths.get(path, {})
    ]
    assert not missing, (
        "Допишите контракт по docs/requirements.md. Отсутствуют операции: " + ", ".join(missing)
    )
    validate(document)
    check_payload_schemas(document)
    return document


@pytest.fixture
def api_schema(contract_path):
    return schemathesis.openapi.from_dict(read_complete_contract(contract_path))


def test_contract_is_complete_and_valid(contract_path):
    read_complete_contract(contract_path)


@schemathesis.pytest.from_fixture("api_schema").parametrize()
@settings(
    max_examples=10,
    deadline=None,
    derandomize=True,
    phases=[Phase.generate],
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_generated_requests_follow_contract(case, client):
    case.call_and_validate(app=client.app)


def test_existing_refund_follows_contract(api_schema, client):
    case = api_schema["/refunds/{refund_id}"]["GET"].Case(
        path_parameters={"refund_id": SEEDED_REFUND}
    )
    response = case.call_and_validate(app=client.app)
    assert response.status_code == 200


def test_create_response_follows_contract(api_schema, client):
    case = api_schema["/refunds"]["POST"].Case(
        headers={"Idempotency-Key": "contract-create-01"},
        body={
            "order_id": PAID_ORDER,
            "amount": 700,
            "currency": "RUB",
            "reason": "Товар повреждён",
        },
        media_type="application/json",
    )
    response = case.call_and_validate(app=client.app)
    assert response.status_code == 201
    assert response.headers.get("location") == [f"/refunds/{response.json()['id']}"]

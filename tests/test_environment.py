"""Проверки запуска, данных и файлов задания."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from yaml import safe_load

from refund_api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_all_example_orders_are_loaded(client):
    for order in json.loads((ROOT / "fixtures/orders.json").read_text()):
        response = client.get(f"/orders/{order['id']}")
        assert response.status_code == 200
        assert response.json() == order


def test_clients_use_separate_databases(client, tmp_path, refund_body):
    created = client.post(
        "/refunds", json=refund_body, headers={"Idempotency-Key": "isolation-key-001"}
    )
    assert created.is_success
    other_app = create_app(tmp_path / "other.sqlite3")
    with TestClient(other_app) as other_client:
        assert other_client.get(f"/refunds/{created.json()['id']}").status_code == 404


def test_contract_file_is_valid_openapi_30(contract_path):
    document = safe_load(contract_path.read_text())
    assert document["openapi"].startswith("3.0.")
    validate(document)


def test_generated_contract_is_not_exposed(client):
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404

"""Проверки бизнес-правил, которые нельзя выразить одним JSON Schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from uuid import UUID

import pytest
from conftest import MISSING_ID, ORDER_PARTIAL, ORDER_UNPAID, SEED_REFUND
from fastapi.testclient import TestClient

from refund_api.app import create_app

pytestmark = pytest.mark.assignment


def create(client, body, key="scenario-key-001"):
    return client.post("/refunds", json=body, headers={"Idempotency-Key": key})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert isinstance(response.json()["error"]["message"], str)


def test_create_returns_201_and_location(client, refund_body):
    response = create(client, refund_body)
    assert response.status_code == 201
    refund = response.json()
    assert response.headers["location"] == f"/refunds/{refund['id']}"
    assert str(UUID(refund["id"])) == refund["id"]
    assert refund["status"] == "pending"
    assert isinstance(refund["amount"], int)
    assert refund["amount"] == refund_body["amount"]
    assert datetime.fromisoformat(refund["created_at"]).tzinfo is not None


@pytest.mark.parametrize("amount", [0, -1, 1.5, "100", True])
def test_amount_must_be_positive_integer(client, refund_body, amount):
    assert_error(create(client, {**refund_body, "amount": amount}), 422, "validation_error")


@pytest.mark.parametrize("reason", ["", "ab", "x" * 201])
def test_reason_length(client, refund_body, reason):
    assert_error(create(client, {**refund_body, "reason": reason}), 422, "validation_error")


def test_extra_body_fields_are_rejected(client, refund_body):
    assert_error(create(client, {**refund_body, "status": "approved"}), 422, "validation_error")


@pytest.mark.parametrize("key", [None, "short", "x" * 65, "spaces are forbidden"])
def test_idempotency_header_is_required_and_validated(client, refund_body, key):
    headers = {} if key is None else {"Idempotency-Key": key}
    response = client.post("/refunds", json=refund_body, headers=headers)
    assert_error(response, 422, "validation_error")


def test_identical_retry_returns_original_record(client, refund_body):
    first = create(client, refund_body)
    second = create(client, refund_body)
    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["location"] == f"/refunds/{first.json()['id']}"
    ids = [row["id"] for row in client.get("/refunds").json()["items"]]
    assert ids.count(first.json()["id"]) == 1


def test_replay_is_allowed_when_order_budget_is_fully_used(client, refund_body):
    body = {**refund_body, "amount": 10000}
    first = create(client, body)
    second = create(client, body)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_same_key_with_different_body_is_conflict(client, refund_body):
    create(client, refund_body)
    assert_error(create(client, {**refund_body, "amount": 2000}), 409, "idempotency_conflict")


def test_refund_requires_paid_order(client, refund_body):
    assert_error(
        create(client, {**refund_body, "order_id": ORDER_UNPAID, "currency": "USD"}),
        409,
        "order_not_paid",
    )


def test_currency_matches_order(client, refund_body):
    assert_error(create(client, {**refund_body, "currency": "USD"}), 409, "currency_mismatch")


def test_unknown_order_and_refund(client, refund_body):
    assert_error(client.get(f"/orders/{MISSING_ID}"), 404, "order_not_found")
    assert_error(create(client, {**refund_body, "order_id": MISSING_ID}), 404, "order_not_found")
    assert_error(client.get(f"/refunds/{MISSING_ID}"), 404, "refund_not_found")


def test_refund_amount_stays_integer_when_read(client):
    response = client.get(f"/refunds/{SEED_REFUND}")
    assert response.status_code == 200
    assert type(response.json()["amount"]) is int


def test_new_refund_cannot_exceed_order_amount(client, refund_body):
    assert_error(create(client, {**refund_body, "amount": 10001}), 409, "refund_limit_exceeded")


def test_pending_and_approved_refunds_share_order_budget(client, refund_body):
    first = create(client, {**refund_body, "amount": 6000}, "first-refund-key").json()
    client.post(f"/refunds/{first['id']}/approve")
    assert_error(
        create(client, {**refund_body, "amount": 4001}, "second-refund-key"),
        409,
        "refund_limit_exceeded",
    )


def test_rejected_refund_releases_order_budget(client, refund_body):
    first = create(client, {**refund_body, "amount": 10000}, "first-refund-key").json()
    assert client.post(f"/refunds/{first['id']}/reject").status_code == 200
    second = create(client, {**refund_body, "amount": 10000}, "second-refund-key")
    assert second.status_code == 201


def test_existing_seed_refund_counts_towards_limit(client, refund_body):
    assert_error(
        create(client, {**refund_body, "order_id": ORDER_PARTIAL, "amount": 5001}),
        409,
        "refund_limit_exceeded",
    )


@pytest.mark.parametrize(
    "first,second",
    [
        ("approve", "approve"),
        ("approve", "reject"),
        ("reject", "approve"),
        ("reject", "reject"),
    ],
)
def test_terminal_status_cannot_change(client, first, second):
    assert client.post(f"/refunds/{SEED_REFUND}/{first}").status_code == 200
    assert_error(client.post(f"/refunds/{SEED_REFUND}/{second}"), 409, "invalid_status")


def test_status_filter_and_pagination(client, refund_body):
    record = create(client, refund_body).json()
    client.post(f"/refunds/{record['id']}/approve")
    result = client.get("/refunds", params={"status": "approved", "limit": 1}).json()
    assert result["total"] == 1
    assert [row["id"] for row in result["items"]] == [record["id"]]
    empty = client.get("/refunds", params={"status": "approved", "limit": 1, "offset": 1}).json()
    assert empty["items"] == []
    assert empty["total"] == 1


@pytest.mark.parametrize(
    "query", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "unknown"}]
)
def test_list_query_validation(client, query):
    assert_error(client.get("/refunds", params=query), 422, "validation_error")


def test_offset_beyond_last_page_preserves_total(client):
    offset = 10**100
    response = client.get("/refunds", params={"offset": offset})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 1, "limit": 10, "offset": offset}


@pytest.mark.parametrize("body", [b'{"amount":', b"\xff"])
def test_malformed_json_uses_common_error_format(client, body):
    response = client.post(
        "/refunds",
        content=body,
        headers={"Content-Type": "application/json", "Idempotency-Key": "invalid-json-key"},
    )
    assert_error(response, 422, "validation_error")


def test_refund_and_idempotency_survive_restart(client, app, refund_body):
    first = create(client, refund_body)
    assert first.is_success
    restarted = create_app(app.state.store.db_path)
    with TestClient(restarted) as restarted_client:
        replay = create(restarted_client, refund_body)
        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]
        ids = [row["id"] for row in restarted_client.get("/refunds").json()["items"]]
        assert ids.count(first.json()["id"]) == 1


def test_concurrent_creates_cannot_over_refund(client, refund_body):
    def submit(index):
        return create(client, {**refund_body, "amount": 6000}, f"concurrent-key-{index}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]

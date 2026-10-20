"""Изолированная база для каждой проверки."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refund_api.app import create_app

ROOT = Path(__file__).resolve().parents[1]
ORDER_RUB = "11111111-1111-4111-8111-111111111111"
ORDER_PARTIAL = "22222222-2222-4222-8222-222222222222"
ORDER_UNPAID = "33333333-3333-4333-8333-333333333333"
ORDER_USD = "44444444-4444-4444-8444-444444444444"
SEED_REFUND = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MISSING_ID = "99999999-9999-4999-8999-999999999999"


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "refunds.sqlite3")


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def contract_path():
    return Path(os.getenv("CONTRACT_PATH", ROOT / "contracts/openapi.yaml"))


@pytest.fixture
def refund_body():
    return {
        "order_id": ORDER_RUB,
        "amount": 1000,
        "currency": "RUB",
        "reason": "Товар не подошёл",
    }

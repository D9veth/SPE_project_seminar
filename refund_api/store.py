import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class StoreError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id TEXT PRIMARY KEY,
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refunds (
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL REFERENCES orders(id),
                    amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS refunds_order_id ON refunds(order_id);
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    request_body TEXT NOT NULL,
                    refund_id TEXT NOT NULL REFERENCES refunds(id)
                );
                """
            )
        fixtures = Path(__file__).resolve().parent.parent / "fixtures"
        with self.transaction() as connection:
            if connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]:
                return
            orders = json.loads((fixtures / "orders.json").read_text(encoding="utf-8"))
            refunds = json.loads((fixtures / "refunds.json").read_text(encoding="utf-8"))
            connection.executemany(
                "INSERT INTO orders (id, amount, currency, status) "
                "VALUES (:id, :amount, :currency, :status)",
                orders,
            )
            connection.executemany(
                "INSERT INTO refunds (id, order_id, amount, currency, reason, status, created_at) "
                "VALUES (:id, :order_id, :amount, :currency, :reason, :status, :created_at)",
                refunds,
            )

    def get_order(self, order_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise StoreError(404, "order_not_found", "Заказ не найден")
        return dict(row)

    def get_refund(self, refund_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM refunds WHERE id = ?", (refund_id,)).fetchone()
        if row is None:
            raise StoreError(404, "refund_not_found", "Заявка не найдена")
        return dict(row)

    def create_refund(self, body: dict[str, Any], key: str) -> tuple[dict[str, Any], bool]:
        serialized_body = json.dumps(body, sort_keys=True, separators=(",", ":"))
        with self.transaction() as connection:
            previous = connection.execute(
                "SELECT request_body, refund_id FROM idempotency WHERE key = ?", (key,)
            ).fetchone()
            if previous is not None:
                row = connection.execute(
                    "SELECT * FROM refunds WHERE id = ?", (previous["refund_id"],)
                ).fetchone()
                return dict(row), False

            order = connection.execute(
                "SELECT * FROM orders WHERE id = ?", (body["order_id"],)
            ).fetchone()
            if order is None:
                raise StoreError(404, "order_not_found", "Заказ не найден")
            if order["status"] != "paid":
                raise StoreError(409, "order_not_paid", "Заказ не оплачен")

            refund = {
                "id": str(uuid4()),
                **body,
                "status": "pending",
                "created_at": datetime.now(UTC)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
            }
            connection.execute(
                "INSERT INTO refunds (id, order_id, amount, currency, reason, status, created_at) "
                "VALUES (:id, :order_id, :amount, :currency, :reason, :status, :created_at)",
                refund,
            )
            connection.execute(
                "INSERT INTO idempotency (key, request_body, refund_id) VALUES (?, ?, ?)",
                (key, serialized_body, refund["id"]),
            )
            return refund, True

    def list_refunds(self, status: str | None, limit: int, offset: int) -> dict[str, Any]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM refunds ORDER BY created_at ASC, id ASC"
            ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": len(rows),
            "limit": limit,
            "offset": offset,
        }

    def change_status(self, refund_id: str, status: str) -> dict[str, Any]:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM refunds WHERE id = ?", (refund_id,)).fetchone()
            if row is None:
                raise StoreError(404, "refund_not_found", "Заявка не найдена")
            connection.execute("UPDATE refunds SET status = ? WHERE id = ?", (status, refund_id))
            return {**dict(row), "status": status}

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from refund_api.models import RefundCreate, RefundStatus
from refund_api.store import Store, StoreError


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


def create_app(db_path: str | Path | None = None) -> FastAPI:
    store = Store(db_path or os.environ.get("REFUNDS_DB_PATH", "data/refunds.sqlite3"))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        yield

    app = FastAPI(
        title="Refund API", lifespan=lifespan, openapi_url=None, docs_url=None, redoc_url=None
    )
    app.state.store = store

    @app.exception_handler(StoreError)
    async def handle_store_error(_: Request, exc: StoreError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", "Проверьте параметры запроса")

    @app.exception_handler(HTTPException)
    async def handle_http_error(_: Request, exc: HTTPException) -> JSONResponse:
        if exc.status_code == 400:
            return error_response(422, "validation_error", "Проверьте параметры запроса")
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        response = error_response(exc.status_code, code, str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/orders/{order_id}")
    def get_order(order_id: UUID) -> dict:
        try:
            return store.get_order(str(order_id))
        except StoreError as exc:
            if exc.code != "order_not_found":
                raise
            return {"error": {"code": exc.code, "message": exc.message}}

    @app.post("/refunds")
    def create_refund(
        body: RefundCreate,
        idempotency_key: Annotated[str, Header(pattern=r"^[A-Za-z0-9_-]{8,64}$")],
    ) -> JSONResponse:
        refund, _ = store.create_refund(body.model_dump(mode="json"), idempotency_key)
        return JSONResponse(status_code=200, content=refund)

    @app.get("/refunds/{refund_id}")
    def get_refund(refund_id: UUID) -> dict:
        refund = store.get_refund(str(refund_id))
        return {**refund, "amount": str(refund["amount"])}

    @app.get("/refunds")
    def list_refunds(
        status: RefundStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        return store.list_refunds(status, limit, offset)

    @app.post("/refunds/{refund_id}/approve")
    def approve_refund(refund_id: UUID) -> dict:
        return store.change_status(str(refund_id), "approved")

    @app.post("/refunds/{refund_id}/reject")
    def reject_refund(refund_id: UUID) -> dict:
        return store.change_status(str(refund_id), "rejected")

    return app


app = create_app()

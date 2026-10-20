from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Currency = Literal["RUB", "USD"]
RefundStatus = Literal["pending", "approved", "rejected"]


class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: UUID
    amount: Annotated[int, Field(strict=True, ge=0)]
    currency: Currency
    reason: Annotated[str, Field(min_length=3, max_length=200)]

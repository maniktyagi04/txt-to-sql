from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class APIError(BaseModel):
    code: str = Field(..., examples=["INTERNAL_SERVER_ERROR"])
    message: str = Field(..., examples=["An unexpected error occurred."])
    field: str | None = Field(default=None, examples=["question"])
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    request_id: str | None = None
    status: str = Field(default="failed", examples=["failed"])
    errors: list[APIError]
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "request_id": "req_123",
            "status": "failed",
            "errors": [
                {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred.",
                    "field": None,
                    "details": None,
                }
            ],
            "warnings": [],
            "timestamp": "2026-06-02T00:00:00Z",
        }
    })

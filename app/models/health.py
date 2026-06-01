from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["healthy"] = Field(..., examples=["healthy"])

    model_config = ConfigDict(json_schema_extra={"example": {"status": "healthy"}})

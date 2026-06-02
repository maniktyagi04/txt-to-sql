from pydantic import BaseModel, ConfigDict, Field


class SchemaTableMetadata(BaseModel):
    table_name: str = Field(..., min_length=1, examples=["analytics.sales_orders"])
    description: str = Field(default="", examples=["Order-level sales facts."])
    columns: list[str] = Field(default_factory=list, examples=[["order_id", "region"]])
    tags: list[str] = Field(default_factory=list, examples=[["sales", "orders"]])


class RetrieveRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        examples=["What were total enterprise sales by region last quarter?"],
    )
    top_k: int | None = Field(default=None, ge=1, le=100)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What were total enterprise sales by region last quarter?",
                "top_k": 5,
            }
        }
    )


class TableRetrievalResult(BaseModel):
    table_name: str = Field(..., examples=["analytics.sales_orders"])
    score: float = Field(..., ge=0.0, le=1.0, examples=[0.91])
    reason: str = Field(
        ...,
        examples=[
            "The table description and columns match sales, region, and quarter terms."
        ],
    )


class RetrieveResponse(BaseModel):
    results: list[TableRetrievalResult]
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    top_k: int = Field(..., ge=1)
    model_name: str = Field(..., examples=["all-MiniLM-L6-v2"])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "results": [
                    {
                        "table_name": "analytics.sales_orders",
                        "score": 0.91,
                        "reason": "The table description and columns match sales, region, and quarter terms.",
                    }
                ],
                "confidence_score": 0.91,
                "top_k": 5,
                "model_name": "all-MiniLM-L6-v2",
            }
        }
    )

from pydantic import BaseModel, Field, ConfigDict
from app.models.retrieval import TableRetrievalResult


class GenerateSQLRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        examples=["What were total enterprise sales by region last quarter?"],
    )
    retrieved_tables: list[TableRetrievalResult] = Field(
        ...,
        examples=[
            [
                TableRetrievalResult(
                    table_name="analytics.sales_orders",
                    score=0.91,
                    reason="Matched schema metadata terms."
                )
            ]
        ]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What were total enterprise sales by region last quarter?",
                "retrieved_tables": [
                    {
                        "table_name": "analytics.sales_orders",
                        "score": 0.91,
                        "reason": "Matched schema metadata terms."
                    }
                ]
            }
        }
    )


class GenerateSQLResponse(BaseModel):
    sql: str = Field(..., examples=["SELECT so.region, SUM(so.enterprise_sales_amount) FROM analytics.sales_orders so GROUP BY so.region"])
    confidence: float = Field(..., ge=0.0, le=1.0, examples=[0.87])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sql": "SELECT so.region, SUM(so.enterprise_sales_amount) FROM analytics.sales_orders so GROUP BY so.region",
                "confidence": 0.87
            }
        }
    )

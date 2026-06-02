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
                    reason="Matched schema metadata terms.",
                    explanation="Matched schema metadata terms.",
                    confidence=0.91,
                )
            ]
        ],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What were total enterprise sales by region last quarter?",
                "retrieved_tables": [
                    {
                        "table_name": "analytics.sales_orders",
                        "score": 0.91,
                        "reason": "Matched schema metadata terms.",
                    }
                ],
            }
        }
    )


class GenerateSQLResponse(BaseModel):
    sql: str = Field(
        ...,
        examples=[
            "SELECT d.department_name, COUNT(s.student_id) FROM beaver.departments d JOIN beaver.students s ON d.department_id = s.department_id GROUP BY d.department_name"
        ],
    )
    confidence: float = Field(..., ge=0.0, le=1.0, examples=[0.87])
    explanation: str = Field(
        ...,
        examples=[
            "This query joins departments and students and counts students per department."
        ],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "sql": "SELECT d.department_name, COUNT(s.student_id) FROM beaver.departments d JOIN beaver.students s ON d.department_id = s.department_id GROUP BY d.department_name",
                "confidence": 0.87,
                "explanation": "This query joins departments and students and counts students per department.",
            }
        }
    )

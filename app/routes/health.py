from fastapi import APIRouter, Depends

from app.models.health import HealthResponse
from app.utils.config import Settings, get_settings

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the current health status for the API service.",
)
async def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="healthy")

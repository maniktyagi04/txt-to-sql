from fastapi import APIRouter

from app.routes.health import router as health_router
from app.routes.retrieval import router as retrieval_router
from app.routes.generation import router as generation_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(retrieval_router, tags=["Retrieval"])
api_router.include_router(generation_router, tags=["Generation"])

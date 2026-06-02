from fastapi import APIRouter

from app.routes.health import router as health_router
from app.routes.retrieval import router as retrieval_router
from app.routes.generation import router as generation_router
from app.routes.execution import router as execution_router
from app.routes.query import router as query_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["Health"])
api_router.include_router(retrieval_router, tags=["Retrieval"])
api_router.include_router(generation_router, tags=["Generation"])
api_router.include_router(execution_router, tags=["Execution"])
api_router.include_router(query_router, tags=["Pipeline"])

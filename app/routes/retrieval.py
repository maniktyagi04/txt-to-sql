from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.models.retrieval import RetrieveRequest, RetrieveResponse
from app.services.cache import get_cache
from app.services.retriever import (
    EmbeddingModelUnavailableError,
    RetrieverError,
    SchemaMetadataNotFoundError,
    SchemaRetriever,
)
from app.utils.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


@lru_cache
def get_retriever() -> SchemaRetriever:
    return SchemaRetriever(get_settings(), get_cache())


@router.post(
    "/retrieve",
    response_model=RetrieveResponse,
    summary="Retrieve relevant schema tables",
    description="Returns the top K semantically relevant tables for a natural language question.",
)
async def retrieve_tables(
    request: RetrieveRequest,
    retriever: SchemaRetriever = Depends(get_retriever),
) -> RetrieveResponse:
    try:
        results = await run_in_threadpool(
            retriever.retrieve,
            request.question,
            request.top_k,
        )
    except SchemaMetadataNotFoundError as exc:
        logger.error("schema_metadata_unavailable", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Schema metadata is unavailable.",
        ) from exc
    except EmbeddingModelUnavailableError as exc:
        logger.error("embedding_model_unavailable", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding model is unavailable.",
        ) from exc
    except RetrieverError as exc:
        logger.error("retriever_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Schema retrieval failed.",
        ) from exc

    selected_top_k = request.top_k or retriever.settings.default_retrieval_top_k
    selected_top_k = min(selected_top_k, retriever.settings.max_retrieval_top_k)

    return RetrieveResponse(
        results=results,
        confidence_score=retriever.confidence_score(results),
        top_k=selected_top_k,
        model_name=retriever.settings.embedding_model_name,
    )

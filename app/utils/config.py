from functools import lru_cache
from os import getenv
from typing import Literal

from pydantic import BaseModel, Field

Environment = Literal["local", "development", "staging", "production", "test"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseModel):
    app_name: str = Field(default="Enterprise Text-to-SQL API")
    app_version: str = Field(default="0.1.0")
    environment: Environment = Field(default="local")
    debug: bool = Field(default=False)

    docs_url: str | None = Field(default="/docs")
    redoc_url: str | None = Field(default="/redoc")
    openapi_url: str | None = Field(default="/openapi.json")

    log_level: LogLevel = Field(default="INFO")
    log_format: Literal["json", "plain"] = Field(default="json")

    embedding_model_name: str = Field(default="all-MiniLM-L6-v2")
    schema_metadata_path: str = Field(default="app/database/schema_metadata.json")
    schema_embedding_store_path: str = Field(
        default="app/database/embeddings/schema_embeddings.json"
    )
    default_retrieval_top_k: int = Field(default=5, ge=1, le=50)
    max_retrieval_top_k: int = Field(default=25, ge=1, le=100)

    gemini_api_key: str | None = Field(default=None)
    gemini_model_name: str = Field(default="gemini-2.5-flash")
    gemini_max_retries: int = Field(default=3, ge=0)
    gemini_timeout_seconds: float = Field(default=30.0, ge=1.0)


def _get_bool_env(name: str, default: bool) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "t", "yes", "y", "on"}


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=getenv("APP_NAME", "Enterprise Text-to-SQL API"),
        app_version=getenv("APP_VERSION", "0.1.0"),
        environment=getenv("ENVIRONMENT", "local"),
        debug=_get_bool_env("DEBUG", False),
        docs_url=getenv("DOCS_URL", "/docs"),
        redoc_url=getenv("REDOC_URL", "/redoc"),
        openapi_url=getenv("OPENAPI_URL", "/openapi.json"),
        log_level=getenv("LOG_LEVEL", "INFO").upper(),
        log_format=getenv("LOG_FORMAT", "json").lower(),
        embedding_model_name=getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2"),
        schema_metadata_path=getenv(
            "SCHEMA_METADATA_PATH",
            "app/database/schema_metadata.json",
        ),
        schema_embedding_store_path=getenv(
            "SCHEMA_EMBEDDING_STORE_PATH",
            "app/database/embeddings/schema_embeddings.json",
        ),
        default_retrieval_top_k=int(getenv("DEFAULT_RETRIEVAL_TOP_K", "5")),
        max_retrieval_top_k=int(getenv("MAX_RETRIEVAL_TOP_K", "25")),
        gemini_api_key=getenv("GEMINI_API_KEY") or getenv("GOOGLE_API_KEY"),
        gemini_model_name=getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
        gemini_max_retries=int(getenv("GEMINI_MAX_RETRIES", "3")),
        gemini_timeout_seconds=float(getenv("GEMINI_TIMEOUT_SECONDS", "30.0")),
    )

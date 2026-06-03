"""Enterprise Configuration Management using pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "development", "staging", "production", "test"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and dotenv file."""

    # App Info
    app_name: str = Field(default="Enterprise Text-to-SQL API")
    app_version: str = Field(default="0.1.0")
    environment: Environment = Field(default="local")
    debug: bool = Field(default=False)

    # API Routing
    docs_url: str | None = Field(default="/docs")
    redoc_url: str | None = Field(default="/redoc")
    openapi_url: str | None = Field(default="/openapi.json")

    # Logging
    log_level: LogLevel = Field(default="INFO")
    log_format: Literal["json", "plain"] = Field(default="json")

    # Schema Retrieval
    # Upgraded to BAAI/bge-small-en-v1.5 (ablation study: +77% Recall@5 vs all-MiniLM-L6-v2)
    embedding_model_name: str = Field(default="BAAI/bge-small-en-v1.5")
    schema_metadata_path: str = Field(default="app/database/schema_metadata.json")
    schema_embedding_store_path: str = Field(
        default="app/database/embeddings/schema_embeddings.json"
    )
    default_retrieval_top_k: int = Field(default=10, ge=1, le=50)
    max_retrieval_top_k: int = Field(default=25, ge=1, le=100)

    # Gemini LLM settings
    gemini_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    gemini_model_name: str = Field(default="gemini-2.5-flash")
    gemini_max_retries: int = Field(default=3, ge=0)
    gemini_timeout_seconds: float = Field(default=30.0, ge=1.0)

    # Caching
    redis_url: str | None = Field(default=None)
    cache_ttl_seconds: int = Field(default=3600, ge=0)  # Default 1 hour

    # Security & Production Settings
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])
    rate_limit_requests_per_minute: int = Field(default=60, ge=1)

    # BEAVER Database Configuration
    # Directory where the live BEAVER .db files live (relative to project root)
    beaver_db_dir: str = Field(default="app/database")
    # Ordered list of schema names to attach during query execution
    beaver_db_names: list[str] = Field(
        default_factory=lambda: ["dw", "nova", "neutron"]
    )
    # Source directory to copy BEAVER databases from (used by init_db).
    # Set BEAVER_DB_SOURCE_DIR env var to override (e.g. ~/Downloads/beaver_db).
    beaver_db_source_dir: str = Field(
        default="",
        description="Path to folder containing dw.db, nova.db, neutron.db source files.",
    )

    @model_validator(mode="after")
    def adjust_for_environment(self) -> Settings:
        if self.environment == "test":
            if self.schema_metadata_path == "app/database/schema_metadata.json":
                self.schema_metadata_path = "app/database/test_schema_metadata.json"
            if self.beaver_db_names == ["dw", "nova", "neutron"]:
                self.beaver_db_names = ["beaver"]
        return self

    # Enable reading from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Returns a cached instance of the settings singleton."""
    return Settings()

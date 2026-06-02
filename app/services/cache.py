"""Enterprise Caching Service supporting Redis and InMemory backends."""

from __future__ import annotations

import time
import json
import hashlib
from abc import ABC, abstractmethod
from typing import Any

from app.utils.config import Settings, get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class BaseCache(ABC):
    """Abstract Base Class for Caching Service."""

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Retrieve key from cache."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store key-value pair in cache with an optional TTL."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete key from cache."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all entries in cache."""
        pass

    @staticmethod
    def generate_key(prefix: str, *args: Any, **kwargs: Any) -> str:
        """Helper to generate a consistent hash key from arguments."""
        # Convert arguments to stable JSON-like representation
        serialized = json.dumps(
            {"args": args, "kwargs": sorted(kwargs.items())},
            sort_keys=True,
            default=str,
        )
        hasher = hashlib.sha256()
        hasher.update(serialized.encode("utf-8"))
        return f"{prefix}:{hasher.hexdigest()}"


class InMemoryCache(BaseCache):
    """In-memory fallback cache implementation for local or test environments."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}
        logger.info("in_memory_cache_initialized")

    def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None

        value, expiry = self._store[key]
        if expiry is not None and time.time() > expiry:
            # Expired
            self.delete(key)
            return None

        return value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        expiry = time.time() + ttl_seconds if ttl_seconds is not None else None
        self._store[key] = (value, expiry)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class RedisCache(BaseCache):
    """Redis cache implementation for production environments."""

    def __init__(self, redis_url: str) -> None:
        import redis
        self._redis_url = redis_url
        # Connect with client-side timeout defaults to prevent connection lockups
        self._client = redis.from_url(
            redis_url,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
            decode_responses=True,
        )
        logger.info("redis_cache_initialized", extra={"redis_url": redis_url})

    def get(self, key: str) -> Any | None:
        try:
            val = self._client.get(key)
            if val is None:
                return None
            return json.loads(val)
        except Exception as exc:
            logger.warning("redis_cache_get_failed", extra={"key": key, "error": str(exc)})
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        try:
            serialized = json.dumps(value)
            if ttl_seconds is not None:
                self._client.setex(key, ttl_seconds, serialized)
            else:
                self._client.set(key, serialized)
        except Exception as exc:
            logger.warning("redis_cache_set_failed", extra={"key": key, "error": str(exc)})

    def delete(self, key: str) -> None:
        try:
            self._client.delete(key)
        except Exception as exc:
            logger.warning("redis_cache_delete_failed", extra={"key": key, "error": str(exc)})

    def clear(self) -> None:
        try:
            self._client.flushdb()
        except Exception as exc:
            logger.warning("redis_cache_clear_failed", extra={"error": str(exc)})


# Centralized factory for cache injection
_cache_instance: BaseCache | None = None

def get_cache(settings: Settings = get_settings()) -> BaseCache:
    """Returns the configured cache instance (Singleton pattern)."""
    global _cache_instance
    if _cache_instance is None:
        if settings.redis_url:
            try:
                _cache_instance = RedisCache(settings.redis_url)
                # Quick ping check to ensure it's responsive
                _cache_instance._client.ping()
            except Exception as exc:
                logger.error(
                    "redis_connection_failed_fallback_to_in_memory",
                    extra={"error": str(exc)},
                )
                _cache_instance = InMemoryCache()
        else:
            _cache_instance = InMemoryCache()
    return _cache_instance

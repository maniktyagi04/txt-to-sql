from __future__ import annotations

import json
import math
import re
import time
from typing import Any

from app.services.cache import BaseCache
from app.utils.config import Settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------

class LLMServiceError(RuntimeError):
    """Base exception for LLM service failures."""


class LLMUnavailableError(LLMServiceError):
    """Raised when the Gemini API is unreachable or not configured."""


class LLMResponseParseError(LLMServiceError):
    """Raised when the model response cannot be parsed into the expected schema."""


class LLMMaxRetriesExceededError(LLMServiceError):
    """Raised when all retry attempts are exhausted."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class GenerationResult:
    """Holds the parsed SQL and confidence from the model."""

    __slots__ = ("sql", "confidence", "raw_response", "latency_ms", "attempt")

    def __init__(
        self,
        *,
        sql: str,
        confidence: float,
        raw_response: str,
        latency_ms: float,
        attempt: int,
    ) -> None:
        self.sql = sql
        self.confidence = confidence
        self.raw_response = raw_response
        self.latency_ms = latency_ms
        self.attempt = attempt


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

_MD_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_CONFIDENCE_CLAMP = (0.0, 1.0)


def _strip_markdown_fences(text: str) -> str:
    """Remove optional ```json ... ``` wrapping the model may add."""
    match = _MD_FENCE_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_response(raw: str) -> tuple[str, float]:
    """Parse the LLM raw text into (sql, confidence).

    Strategy:
    1. Strip any markdown fences.
    2. JSON-parse the result.
    3. Validate keys and types.
    """
    cleaned = _strip_markdown_fences(raw)

    try:
        payload: dict[str, Any] = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMResponseParseError(
            f"Model response is not valid JSON after stripping fences: {exc!s}"
        ) from exc

    sql = payload.get("sql")
    confidence_raw = payload.get("confidence")

    if not isinstance(sql, str) or not sql.strip():
        raise LLMResponseParseError(
            f"'sql' field is missing or empty in model response: {payload!r}"
        )

    if not isinstance(confidence_raw, (int, float)):
        # Attempt coercion — model might return a string
        try:
            confidence_raw = float(confidence_raw)
        except (TypeError, ValueError) as exc:
            raise LLMResponseParseError(
                f"'confidence' field is not numeric in model response: {payload!r}"
            ) from exc

    confidence = max(_CONFIDENCE_CLAMP[0], min(_CONFIDENCE_CLAMP[1], float(confidence_raw)))
    return sql.strip(), confidence


# ---------------------------------------------------------------------------
# Gemini LLM Service
# ---------------------------------------------------------------------------

class GeminiLLMService:
    """Wraps the google-generativeai SDK with retry logic, parsing, and logging."""

    def __init__(self, settings: Settings, cache: BaseCache | None = None) -> None:
        self.settings = settings
        self.cache = cache
        self._client: Any | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, prompt: str) -> GenerationResult:
        """Call Gemini with retry/backoff, parse the response, and return a result.

        Args:
            prompt: Fully-rendered prompt string from SQLPromptBuilder.

        Returns:
            GenerationResult with sql, confidence, latency, and attempt count.

        Raises:
            LLMUnavailableError: If the API key is absent or SDK is unavailable.
            LLMMaxRetriesExceededError: If all retries are exhausted.
            LLMResponseParseError: If the final response cannot be parsed.
        """
        # Check cache if available
        if self.cache:
            cache_key = BaseCache.generate_key("generate", prompt)
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                logger.info("llm_generation_cache_hit", extra={"model": self.settings.gemini_model_name})
                return GenerationResult(
                    sql=cached_data["sql"],
                    confidence=cached_data["confidence"],
                    raw_response=cached_data["raw_response"],
                    latency_ms=cached_data["latency_ms"],
                    attempt=cached_data["attempt"],
                )
            logger.info("llm_generation_cache_miss", extra={"model": self.settings.gemini_model_name})

        client = self._load_client()
        max_retries = self.settings.gemini_max_retries
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 2):  # +1 so 0 retries still gets 1 attempt
            t_start = time.monotonic()
            try:
                raw = self._call_api(client, prompt)
                latency_ms = (time.monotonic() - t_start) * 1_000

                sql, confidence = _parse_response(raw)

                logger.info(
                    "llm_generation_succeeded",
                    extra={
                        "model": self.settings.gemini_model_name,
                        "attempt": attempt,
                        "latency_ms": round(latency_ms, 2),
                        "confidence": confidence,
                        "sql_length": len(sql),
                    },
                )
                
                result = GenerationResult(
                    sql=sql,
                    confidence=confidence,
                    raw_response=raw,
                    latency_ms=latency_ms,
                    attempt=attempt,
                )

                # Cache the successful result
                if self.cache:
                    cache_key = BaseCache.generate_key("generate", prompt)
                    self.cache.set(
                        cache_key,
                        {
                            "sql": result.sql,
                            "confidence": result.confidence,
                            "raw_response": result.raw_response,
                            "latency_ms": result.latency_ms,
                            "attempt": result.attempt,
                        },
                        ttl_seconds=self.settings.cache_ttl_seconds,
                    )

                return result

            except LLMResponseParseError as exc:
                latency_ms = (time.monotonic() - t_start) * 1_000
                last_exc = exc
                logger.warning(
                    "llm_parse_error",
                    extra={
                        "attempt": attempt,
                        "latency_ms": round(latency_ms, 2),
                        "error": str(exc),
                    },
                )
                # Parse errors are retryable — the model may produce valid JSON on retry
                if attempt <= max_retries:
                    self._backoff(attempt)
                    continue
                break

            except LLMUnavailableError:
                raise

            except Exception as exc:
                latency_ms = (time.monotonic() - t_start) * 1_000
                last_exc = exc
                logger.warning(
                    "llm_api_error",
                    extra={
                        "attempt": attempt,
                        "latency_ms": round(latency_ms, 2),
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                if attempt <= max_retries:
                    self._backoff(attempt)
                    continue
                break

        raise LLMMaxRetriesExceededError(
            f"Gemini generation failed after {max_retries + 1} attempt(s). "
            f"Last error: {last_exc!s}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_client(self) -> Any:
        """Lazily initialise and cache the generativeai GenerativeModel."""
        if self._client is not None:
            return self._client

        try:
            import google.generativeai as genai  # type: ignore[import]
        except ImportError as exc:
            raise LLMUnavailableError(
                "google-generativeai package is not installed. "
                "Run: pip install google-generativeai>=0.8.0"
            ) from exc

        api_key = self.settings.gemini_api_key
        if not api_key:
            raise LLMUnavailableError(
                "GEMINI_API_KEY / GOOGLE_API_KEY environment variable is not set."
            )

        genai.configure(api_key=api_key)

        generation_config = genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        )

        self._client = genai.GenerativeModel(
            model_name=self.settings.gemini_model_name,
            generation_config=generation_config,
        )

        logger.info(
            "gemini_client_initialized",
            extra={"model": self.settings.gemini_model_name},
        )
        return self._client

    def _call_api(self, client: Any, prompt: str) -> str:
        """Execute the Gemini API call and return the raw text response."""
        response = client.generate_content(
            contents=prompt,
            request_options={"timeout": self.settings.gemini_timeout_seconds},
        )

        # Extract text safely — handle None candidates gracefully
        if not response.candidates:
            raise LLMResponseParseError("Gemini returned no candidates in the response.")

        parts = response.candidates[0].content.parts
        if not parts:
            raise LLMResponseParseError("Gemini candidate has no content parts.")

        raw = parts[0].text
        if not raw or not raw.strip():
            raise LLMResponseParseError("Gemini returned an empty text response.")

        logger.debug(
            "llm_raw_response",
            extra={"raw_length": len(raw)},
        )
        return raw

    @staticmethod
    def _backoff(attempt: int) -> None:
        """Exponential backoff: 2^(attempt-1) seconds, capped at 16 s."""
        delay = min(math.pow(2, attempt - 1), 16.0)
        logger.debug("llm_backoff", extra={"attempt": attempt, "delay_seconds": delay})
        time.sleep(delay)

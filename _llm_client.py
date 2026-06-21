import logging
import os
import re
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types


logger = logging.getLogger(__name__)


class LLMClient:
    """Shared Gemini client + text-parsing utilities for LLM-backed agents.

    Every LLM agent in this project talks to Google Gemini. The client is built
    once here from ``GEMINI_API_KEY`` and exposes ``_gemini_generate`` with a
    generous timeout and automatic retries so transient failures no longer drop
    silently into the rule-based fallbacks.
    """

    # Single Gemini model used across all agents.
    DEFAULT_MODEL = "gemini-3.1-flash-lite-preview"
    # google-genai expects the request timeout in milliseconds.
    GEMINI_TIMEOUT_MS = 60_000
    MAX_ATTEMPTS = 3

    def __init__(self) -> None:
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=self.GEMINI_TIMEOUT_MS),
            )
            if api_key
            else None
        )

    def _gemini_generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_output_tokens: int = 2048,
    ) -> str:
        """Call Gemini and return the raw text, retrying on transient errors.

        Raises ``RuntimeError`` if no API key is configured, or the last
        exception if every attempt fails.
        """
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY is missing in environment variables.")

        last_exc: Exception | None = None
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            try:
                response = self.client.models.generate_content(
                    model=model or self.DEFAULT_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    ),
                )
                return response.text or ""
            except Exception as exc:  # noqa: BLE001 - retry on any transient API error
                last_exc = exc
                logger.warning(
                    "Gemini call failed (attempt %d/%d): %s",
                    attempt,
                    self.MAX_ATTEMPTS,
                    exc,
                )
                if attempt < self.MAX_ATTEMPTS:
                    time.sleep(1.5 * attempt)
        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _extract_json_object(text: str) -> str:
        cleaned = LLMClient._strip_markdown_fences(text)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned

    @staticmethod
    def _attempt_suffix(attempt: int) -> str:
        """Filename suffix so decision-loop retries don't overwrite each other."""
        return "" if attempt <= 1 else f"_attempt{attempt}"

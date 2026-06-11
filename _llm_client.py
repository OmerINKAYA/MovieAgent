import re

from dotenv import load_dotenv


class LLMClient:
    """Shared text-parsing utilities for LLM-backed agents."""

    def __init__(self) -> None:
        load_dotenv()
        self.client = None

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

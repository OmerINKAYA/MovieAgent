import json
import logging
from typing import Any

from google.genai import types

from _llm_client import LLMClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ComparisonAgent(LLMClient):
    MODEL_NAME = "gemini-3.1-flash-lite"

    def run(self, discovery_output: dict[str, Any], preferred_genre: str) -> dict[str, Any]:
        movies = discovery_output.get("movies", [])
        logger.info(
            "ComparisonAgent started: preferred_genre=%s input_movies=%d",
            preferred_genre,
            len(movies),
        )

        if not self.client:
            return {
                "top3": [],
                "selection_logic": "",
                "preferred_genre": preferred_genre,
                "all_movies": movies,
                "metadata": {"error": "GEMINI_API_KEY is missing in environment variables."},
            }

        formatted_movies = [
            {
                "title": movie.get("title", ""),
                "genre_ids": movie.get("genre_ids", []),
                "vote_average": movie.get("vote_average", 0.0),
                "release_date": movie.get("release_date", ""),
            }
            for movie in movies
        ]

        prompt = (
            "Below is a filtered list of currently playing movies in Turkey and the user's preferred genre.\n"
            "Task:\n"
            "1) Select the best 3 movies based on genre match and vote_average.\n"
            "2) At least 2 of the selected 3 films must have a release_date in 2025 or later.\n"
            "   The third film can be older.\n"
            "3) Return only JSON.\n"
            "4) 'reason' must be in English and 1-2 sentences.\n"
            "5) 'selection_logic' must be in English and 2-3 sentences.\n"
            "6) rank values must be 1, 2, and 3.\n\n"
            "Return JSON in this schema:\n"
            "{\n"
            '  "top3": [\n'
            '    {"rank": 1, "title": "Movie Title", "reason": "..."},\n'
            '    {"rank": 2, "title": "Movie Title", "reason": "..."},\n'
            '    {"rank": 3, "title": "Movie Title", "reason": "..."}\n'
            "  ],\n"
            '  "selection_logic": "..."\n'
            "}\n\n"
            f"User preferred genre: {preferred_genre}\n"
            f"Movies JSON: {json.dumps(formatted_movies, ensure_ascii=False)}"
        )

        try:
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2048,
                ),
            )
            raw_text = response.text or ""
            cleaned = self._strip_markdown_fences(raw_text)
            parsed = json.loads(cleaned)

            output = {
                "top3": parsed.get("top3", []),
                "selection_logic": parsed.get("selection_logic", ""),
                "preferred_genre": preferred_genre,
                "all_movies": movies,
            }
            logger.info("ComparisonAgent completed: selected=%d", len(output["top3"]))
            return output
        except Exception as exc:
            logger.exception("ComparisonAgent failed")
            return {
                "top3": [],
                "selection_logic": "",
                "preferred_genre": preferred_genre,
                "all_movies": movies,
                "metadata": {"error": f"ComparisonAgent failed: {exc}"},
            }


if __name__ == "__main__":
    mock_discovery_output = {
        "movies": [
            {
                "id": 101,
                "title": "Action Horizon",
                "original_language": "en",
                "genre_ids": [28, 12],
                "vote_average": 7.9,
                "vote_count": 1500,
                "popularity": 200.1,
                "overview": "A high-stakes action adventure.",
                "release_date": "2026-03-15",
                "poster_path": "/action.jpg",
            },
            {
                "id": 102,
                "title": "Romantik Ruzgar",
                "original_language": "tr",
                "genre_ids": [10749, 18],
                "vote_average": 7.3,
                "vote_count": 640,
                "popularity": 134.9,
                "overview": "A heartfelt Turkish romantic drama.",
                "release_date": "2026-02-10",
                "poster_path": "/romance.jpg",
            },
            {
                "id": 103,
                "title": "Comedy Night",
                "original_language": "en",
                "genre_ids": [35],
                "vote_average": 6.8,
                "vote_count": 420,
                "popularity": 98.0,
                "overview": "A light and witty comedy.",
                "release_date": "2026-01-22",
                "poster_path": "/comedy.jpg",
            },
            {
                "id": 104,
                "title": "Anatolian Mystery",
                "original_language": "tr",
                "genre_ids": [9648, 53],
                "vote_average": 8.1,
                "vote_count": 890,
                "popularity": 160.3,
                "overview": "A mystery thriller set in central Anatolia.",
                "release_date": "2026-04-01",
                "poster_path": "/mystery.jpg",
            },
        ],
        "user_preferences": {},
        "metadata": {"total_fetched": 4, "total_after_filter": 4},
    }

    agent = ComparisonAgent()
    result = agent.run(mock_discovery_output, preferred_genre="Action")
    print(json.dumps(result, ensure_ascii=False, indent=2))

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

from _llm_client import LLMClient
from debug_logger import format_json, write_debug_file


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ComparisonAgent(LLMClient):
    MODEL_NAME = "gemini-3.1-flash-lite-preview"

    def __init__(self) -> None:
        super().__init__()
        api_key = os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=30_000))
            if api_key
            else None
        )

    def run(
        self,
        discovery_output: dict[str, Any],
        preferred_genre: str,
        run_id: str = "",
    ) -> dict[str, Any]:
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
                "source": movie.get("source", "tmdb"),
                "genre_ids": movie.get("genre_ids", []),
                "genre_names": movie.get("genre_names", []),
                "vote_average": movie.get("vote_average", 0.0),
                "vote_count": movie.get("vote_count", 0),
                "biletinial_rating": movie.get("biletinial_rating", 0.0),
                "biletinial_comment_count": movie.get("biletinial_comment_count", 0),
                "release_date": movie.get("release_date", ""),
                "overview": movie.get("overview", ""),
                "director": movie.get("director", ""),
                "duration": movie.get("duration", ""),
                "detail_url": movie.get("detail_url", ""),
                "playing_at_summary": {
                    "cinema_count": len(movie.get("playing_at", [])),
                    "cinemas": [
                        venue.get("cinema", "")
                        for venue in movie.get("playing_at", [])[:5]
                    ],
                },
            }
            for movie in movies
        ]

        prompt = (
            "Below is a filtered list of currently playing movies in Turkey and the user's preferred genre.\n"
            "Movies may come from Biletinial, which uses Turkish genre names and local audience ratings/comments.\n"
            "Task:\n"
            "1) Select the best 3 movies based on exact Biletinial genre match first, then local audience rating/comment count.\n"
            "2) Do not select movies without playing_at venue data. Be strict: a weak genre match is worse than a lower rating.\n"
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
        write_debug_file(
            run_id,
            "02_comparison_prompt.txt",
            "ComparisonAgent prompt sent to Gemini\n\n"
            f"Model: {self.MODEL_NAME}\n\n"
            f"{prompt}\n",
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
            write_debug_file(
                run_id,
                "03_comparison_llm_answer.txt",
                "ComparisonAgent raw LLM answer\n\n"
                f"Model: {self.MODEL_NAME}\n\n"
                f"{raw_text}\n",
            )
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
            write_debug_file(
                run_id,
                "03_comparison_error.txt",
                "ComparisonAgent failed before a valid parsed answer was produced.\n\n"
                f"Error: {exc}\n\n"
                f"Input movies:\n{format_json(formatted_movies)}\n",
            )
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

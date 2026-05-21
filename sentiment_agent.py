import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from google.genai import types

from _llm_client import LLMClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SentimentAgent(LLMClient):
    TMDB_BASE_URL = "https://api.themoviedb.org/3"
    MODEL_NAME = "gemini-3.1-flash-lite"

    def __init__(self) -> None:
        super().__init__()
        self.tmdb_api_key = os.getenv("TMDB_API_KEY")

    def _fetch_reviews(self, movie_id: int) -> list[dict[str, Any]]:
        if not self.tmdb_api_key:
            raise ValueError("TMDB_API_KEY is missing in environment variables.")

        response = requests.get(
            f"{self.TMDB_BASE_URL}/movie/{movie_id}/reviews",
            params={
                "api_key": self.tmdb_api_key,
                "language": "en-US",
                "page": 1,
            },
            timeout=20,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[:5]

    def run(self, comparison_output: dict[str, Any]) -> dict[str, Any]:
        top3 = comparison_output.get("top3", [])
        all_movies = comparison_output.get("all_movies", [])
        preferred_genre = comparison_output.get("preferred_genre", "")
        selection_logic = comparison_output.get("selection_logic", "")

        logger.info("SentimentAgent started: selected_movies=%d", len(top3))

        if not self.client:
            return {
                "enriched_top3": [],
                "preferred_genre": preferred_genre,
                "selection_logic": selection_logic,
                "metadata": {
                    "reviews_fetched": {},
                    "error": "GEMINI_API_KEY is missing in environment variables.",
                },
            }

        title_to_movie = {movie.get("title"): movie for movie in all_movies}
        reviews_by_title: dict[str, list[dict[str, Any]]] = {}
        reviews_fetched: dict[str, int] = {}
        no_review_context: dict[str, dict[str, Any]] = {}

        def _fetch_for_item(item: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
            title = item.get("title", "")
            movie = title_to_movie.get(title, {})
            movie_id = movie.get("id")
            if not movie_id:
                return title, []
            return title, self._fetch_reviews(int(movie_id))

        try:
            with ThreadPoolExecutor(max_workers=len(top3) or 1) as executor:
                fetch_results = list(executor.map(_fetch_for_item, top3))
            for title, reviews in fetch_results:
                reviews_by_title[title] = reviews
                reviews_fetched[title] = len(reviews)
                if len(reviews) == 0:
                    movie = title_to_movie.get(title, {})
                    no_review_context[title] = {
                        "vote_average": float(movie.get("vote_average", 0.0) or 0.0),
                        "overview": movie.get("overview", ""),
                    }

            prompt_payload = {
                "instruction": (
                    "Analyze the English user reviews for the 3 movies below. "
                    "For each movie, set sentiment to positive/mixed/negative, "
                    "Write the recommendation explanation in English with 2-3 sentences, and "
                    "extract up to 3 short English snippets from reviews. "
                    "Return only JSON and use only the enriched_top3 key. "
                    "For movies with no reviews, write the explanation using vote_average and overview."
                ),
                "expected_schema": {
                    "enriched_top3": [
                        {
                            "rank": 1,
                            "title": "Movie Title",
                            "sentiment": "positive",
                            "explanation": "English explanation",
                            "review_snippets": ["snippet 1", "snippet 2", "snippet 3"],
                        }
                    ]
                },
                "selected_top3": top3,
                "no_review_context": no_review_context,
                "reviews_by_title": {
                    title: [
                        {
                            "author": review.get("author", ""),
                            "content": review.get("content", ""),
                            "created_at": review.get("created_at", ""),
                        }
                        for review in reviews
                    ]
                    for title, reviews in reviews_by_title.items()
                },
            }

            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=json.dumps(prompt_payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "enriched_top3": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "rank": {"type": "integer"},
                                        "title": {"type": "string"},
                                        "sentiment": {"type": "string"},
                                        "explanation": {"type": "string"},
                                        "review_snippets": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": [
                                        "rank",
                                        "title",
                                        "sentiment",
                                        "explanation",
                                        "review_snippets",
                                    ],
                                },
                            }
                        },
                        "required": ["enriched_top3"],
                    },
                ),
            )
            if isinstance(response.parsed, dict):
                parsed = response.parsed
            else:
                raw_text = response.text or ""
                cleaned = self._extract_json_object(raw_text)
                parsed = json.loads(cleaned)

            output = {
                "enriched_top3": parsed.get("enriched_top3", []),
                "preferred_genre": preferred_genre,
                "selection_logic": selection_logic,
                "metadata": {"reviews_fetched": reviews_fetched},
            }

            for item in output["enriched_top3"]:
                title = item.get("title", "")
                if reviews_fetched.get(title, 0) == 0:
                    vote_average = float(
                        no_review_context.get(title, {}).get("vote_average", 0.0) or 0.0
                    )
                    if vote_average >= 7.0:
                        item["sentiment"] = "positive"
                    elif vote_average >= 5.0:
                        item["sentiment"] = "mixed"
                    else:
                        item["sentiment"] = "negative"
                    item["review_snippets"] = []

            logger.info("SentimentAgent completed: enriched_movies=%d", len(output["enriched_top3"]))
            return output
        except requests.RequestException as exc:
            logger.exception("TMDB API request failed in SentimentAgent")
            return {
                "enriched_top3": [],
                "preferred_genre": preferred_genre,
                "selection_logic": selection_logic,
                "metadata": {
                    "reviews_fetched": reviews_fetched,
                    "error": f"TMDB API request failed: {exc}",
                },
            }
        except Exception as exc:
            logger.exception("SentimentAgent failed")
            return {
                "enriched_top3": [],
                "preferred_genre": preferred_genre,
                "selection_logic": selection_logic,
                "metadata": {
                    "reviews_fetched": reviews_fetched,
                    "error": f"SentimentAgent failed: {exc}",
                },
            }


if __name__ == "__main__":
    mock_comparison_output = {
        "top3": [
            {"rank": 1, "title": "Action Horizon", "reason": "High-octane pacing makes it a strong action pick."},
            {"rank": 2, "title": "Anatolian Mystery", "reason": "Thriller elements are dominant throughout."},
            {"rank": 3, "title": "Romantik Ruzgar", "reason": "Emotional tone is handled successfully."},
        ],
        "selection_logic": "Selection was made based on genre fit and vote average.",
        "preferred_genre": "Action",
        "all_movies": [
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
        ],
    }

    agent = SentimentAgent()
    result = agent.run(mock_comparison_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))

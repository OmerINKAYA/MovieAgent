import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import requests
from dotenv import load_dotenv


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DiscoveryAgent:
    TMDB_BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self, max_pages: int = 5) -> None:
        load_dotenv()
        self.api_key = os.getenv("TMDB_API_KEY")
        self.max_pages = max_pages

    def _fetch_now_playing_page(self, page: int) -> list[dict[str, Any]]:
        if not self.api_key:
            raise ValueError("TMDB_API_KEY is missing in environment variables.")

        response = requests.get(
            f"{self.TMDB_BASE_URL}/movie/now_playing",
            params={
                "api_key": self.api_key,
                "region": "TR",
                "page": page,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])

    @staticmethod
    def _normalize_movie(movie: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": movie.get("id"),
            "title": movie.get("title", ""),
            "original_language": movie.get("original_language", ""),
            "genre_ids": movie.get("genre_ids", []),
            "vote_average": float(movie.get("vote_average", 0.0) or 0.0),
            "vote_count": int(movie.get("vote_count", 0) or 0),
            "popularity": float(movie.get("popularity", 0.0) or 0.0),
            "overview": movie.get("overview", ""),
            "release_date": movie.get("release_date", ""),
            "poster_path": movie.get("poster_path"),
        }

    @staticmethod
    def _passes_filters(movie: dict[str, Any], cutoff_date: str) -> bool:
        return (
            movie.get("vote_average", 0.0) >= 5.0
            and movie.get("vote_count", 0) >= 50
            and movie.get("original_language") in {"en", "tr"}
            and movie.get("release_date", "") >= cutoff_date
        )

    def run(self) -> dict[str, Any]:
        logger.info("DiscoveryAgent started")
        all_movies: list[dict[str, Any]] = []
        cutoff_date = (datetime.today() - timedelta(days=45)).strftime("%Y-%m-%d")

        try:
            with ThreadPoolExecutor(max_workers=self.max_pages) as executor:
                pages = list(executor.map(self._fetch_now_playing_page, range(1, self.max_pages + 1)))
            for page_movies in pages:
                all_movies.extend(self._normalize_movie(movie) for movie in page_movies)

            filtered_movies = [movie for movie in all_movies if self._passes_filters(movie, cutoff_date)]
            filtered_movies.sort(key=lambda x: x["vote_average"], reverse=True)

            output = {
                "movies": filtered_movies,
                "user_preferences": {},
                "metadata": {
                    "total_fetched": len(all_movies),
                    "total_after_filter": len(filtered_movies),
                },
            }
            logger.info(
                "DiscoveryAgent completed: total_fetched=%d total_after_filter=%d",
                output["metadata"]["total_fetched"],
                output["metadata"]["total_after_filter"],
            )
            return output
        except requests.RequestException as exc:
            logger.exception("TMDB API request failed")
            return {
                "movies": [],
                "user_preferences": {},
                "metadata": {
                    "total_fetched": len(all_movies),
                    "total_after_filter": 0,
                    "error": f"TMDB API request failed: {exc}",
                },
            }
        except Exception as exc:
            logger.exception("DiscoveryAgent failed unexpectedly")
            return {
                "movies": [],
                "user_preferences": {},
                "metadata": {
                    "total_fetched": len(all_movies),
                    "total_after_filter": 0,
                    "error": f"DiscoveryAgent failed: {exc}",
                },
            }


if __name__ == "__main__":
    agent = DiscoveryAgent()
    result = agent.run()

    print("Metadata:", result.get("metadata", {}))
    print("Top 3 Movies:")
    for movie in result.get("movies", [])[:3]:
        print(f"- {movie.get('title', 'Unknown')} (score: {movie.get('vote_average', 0.0)})")

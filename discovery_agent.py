import logging
from typing import Any

from dotenv import load_dotenv

from biletinial_scraper import BiletinialScraper


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DiscoveryAgent:
    def __init__(self) -> None:
        load_dotenv()

    def run(self) -> dict[str, Any]:
        logger.info("DiscoveryAgent started")
        try:
            scraper_output = BiletinialScraper().run()
            all_movies = scraper_output.get("movies", [])
            movies = [movie for movie in all_movies if movie.get("playing_at")]
            metadata = {
                **scraper_output.get("metadata", {}),
                "total_after_salon_filter": len(movies),
            }
            return {
                "all_movies": all_movies,
                "movies": movies,
                "user_preferences": {},
                "metadata": metadata,
            }
        except Exception as exc:
            logger.exception("Biletinial discovery failed")
            return {
                "all_movies": [],
                "movies": [],
                "user_preferences": {},
                "metadata": {
                    "source": "biletinial",
                    "total_fetched": 0,
                    "total_after_filter": 0,
                    "total_after_salon_filter": 0,
                    "error": f"Biletinial discovery failed: {exc}",
                },
            }


if __name__ == "__main__":
    agent = DiscoveryAgent()
    result = agent.run()

    print("Metadata:", result.get("metadata", {}))
    print("Top 3 Movies:")
    for movie in result.get("movies", [])[:3]:
        print(f"- {movie.get('title', 'Unknown')} (score: {movie.get('vote_average', 0.0)})")

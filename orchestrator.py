import logging
import time
from collections.abc import Callable
from typing import Any

from comparison_agent import ComparisonAgent
from debug_logger import format_json, start_run, write_debug_file
from distance_utils import add_distances_to_playing_at, parse_user_location
from discovery_agent import DiscoveryAgent
from evaluation_agent import EvaluationAgent
from sentiment_agent import SentimentAgent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _run_with_timing(agent_name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed = time.perf_counter() - start
    logger.info("%s completed in %.4f seconds", agent_name, elapsed)
    return result


def _attach_showtime_context(
    enriched_top3: list[dict[str, Any]],
    all_movies: list[dict[str, Any]],
    user_location: dict[str, float] | None,
) -> list[dict[str, Any]]:
    movie_by_title = {movie.get("title", ""): movie for movie in all_movies}
    output = []
    for item in enriched_top3:
        movie = movie_by_title.get(item.get("title", ""), {})
        playing_at = movie.get("playing_at", [])
        if not playing_at:
            continue
        playing_at_with_distance, nearest = add_distances_to_playing_at(playing_at, user_location)
        output.append(
            {
                **item,
                "detail_url": movie.get("detail_url", ""),
                "poster_path": movie.get("poster_path", ""),
                "playing_at": playing_at_with_distance,
                "nearest_cinema": nearest,
            }
        )
    return output


def run(preferred_genre: str, user_location: dict[str, Any] | None = None) -> dict[str, Any]:
    logger.info("Orchestrator started: preferred_genre=%s", preferred_genre)
    run_id = start_run(preferred_genre)
    logger.info("Debug logs will be written to llm_logs/%s", run_id)
    parsed_user_location = parse_user_location(user_location)

    discovery_agent = DiscoveryAgent()
    comparison_agent = ComparisonAgent()
    sentiment_agent = SentimentAgent()
    evaluation_agent = EvaluationAgent()

    discovery_output = _run_with_timing("DiscoveryAgent", discovery_agent.run)
    write_debug_file(
        run_id,
        "00_all_biletinial_films.txt",
        "All films fetched from Biletinial before DiscoveryAgent filters\n\n"
        f"Preferred genre: {preferred_genre}\n\n"
        f"Metadata:\n{format_json(discovery_output.get('metadata', {}))}\n\n"
        f"Movies:\n{format_json(discovery_output.get('all_movies', []))}\n",
    )
    write_debug_file(
        run_id,
        "01_discovery_films.txt",
        "Filtered films from Biletinial DiscoveryAgent\n\n"
        f"Preferred genre: {preferred_genre}\n\n"
        f"Metadata:\n{format_json(discovery_output.get('metadata', {}))}\n\n"
        f"Movies:\n{format_json(discovery_output.get('movies', []))}\n",
    )
    comparison_output = _run_with_timing(
        "ComparisonAgent",
        comparison_agent.run,
        discovery_output,
        preferred_genre,
        run_id=run_id,
    )
    sentiment_output = _run_with_timing(
        "SentimentAgent",
        sentiment_agent.run,
        comparison_output,
        run_id=run_id,
    )
    evaluation_output = _run_with_timing(
        "EvaluationAgent",
        evaluation_agent.run,
        sentiment_output,
        comparison_output,
        run_id=run_id,
    )
    enriched_top3 = _attach_showtime_context(
        sentiment_output.get("enriched_top3", []),
        comparison_output.get("all_movies", []),
        parsed_user_location,
    )
    logger.info("Orchestrator completed")
    return {
        "enriched_top3": enriched_top3,
        "preferred_genre": sentiment_output.get("preferred_genre", preferred_genre),
        "selection_logic": sentiment_output.get("selection_logic", ""),
        "reviews_fetched": sentiment_output.get("metadata", {}).get("reviews_fetched", {}),
        "overall_score": evaluation_output.get("overall_score", 0.0),
        "per_film_scores": evaluation_output.get("per_film_scores", []),
        "pipeline_feedback": evaluation_output.get("pipeline_feedback", ""),
        "metadata": {
            "discovery": discovery_output.get("metadata", {}),
            "sentiment": sentiment_output.get("metadata", {}),
            "evaluation": evaluation_output.get("metadata", {}),
            "location": {
                "used": parsed_user_location is not None,
                "provided": user_location is not None,
            },
        },
    }

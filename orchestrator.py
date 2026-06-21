import logging
import time
from collections.abc import Callable
from typing import Any

from comparison_agent import ComparisonAgent
from debug_logger import format_json, start_run, write_debug_file
from distance_utils import add_distances_to_playing_at, haversine_km, parse_user_location
from discovery_agent import DiscoveryAgent
from evaluation_agent import EvaluationAgent
from sentiment_agent import SentimentAgent


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Autonomous decision loop tuning.
# After the Evaluation agent scores a selection, the orchestrator decides whether
# the result is good enough or whether it should drop the weak picks and ask the
# Comparison agent for a different set of films.
MAX_SELECTION_ATTEMPTS = 3
SCORE_ACCEPT_THRESHOLD = 7.0  # on a 0-10 scale


def _normalized_overall(score: Any) -> float:
    """Evaluation scores live on a 0-10 scale, but the LLM occasionally answers
    on a 0-1 scale. Normalize so the accept threshold means the same thing."""
    if not isinstance(score, (int, float)):
        return 0.0
    value = float(score)
    return value * 10.0 if 0.0 < value <= 1.0 else value


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


def _collect_all_theaters(
    all_movies: list[dict[str, Any]],
    user_location: dict[str, float] | None,
) -> list[dict[str, Any]]:
    """Flatten every now-playing movie's venues into a deduped list of theaters
    that have coordinates, attaching distance from the user when known."""
    seen: set[tuple[float, float]] = set()
    theaters: list[dict[str, Any]] = []
    for movie in all_movies:
        for venue in movie.get("playing_at", []):
            lat = venue.get("lat")
            lon = venue.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                continue
            key = (round(float(lat), 5), round(float(lon), 5))
            if key in seen:
                continue
            seen.add(key)
            theater = {
                "cinema": str(venue.get("cinema", "") or "Cinema"),
                "address": str(venue.get("address", "") or ""),
                "lat": float(lat),
                "lon": float(lon),
            }
            if user_location:
                theater["distance_km"] = round(
                    haversine_km(user_location["lat"], user_location["lon"], float(lat), float(lon)),
                    2,
                )
            theaters.append(theater)
    return theaters


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
    candidate_titles = {
        movie.get("title", "") for movie in discovery_output.get("movies", [])
    }

    excluded_titles: set[str] = set()
    decision_log: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for attempt in range(1, MAX_SELECTION_ATTEMPTS + 1):
        comparison_output = _run_with_timing(
            "ComparisonAgent",
            comparison_agent.run,
            discovery_output,
            preferred_genre,
            run_id=run_id,
            exclude_titles=excluded_titles,
            attempt=attempt,
        )
        sentiment_output = _run_with_timing(
            "SentimentAgent",
            sentiment_agent.run,
            comparison_output,
            run_id=run_id,
            attempt=attempt,
        )
        evaluation_output = _run_with_timing(
            "EvaluationAgent",
            evaluation_agent.run,
            sentiment_output,
            comparison_output,
            run_id=run_id,
            attempt=attempt,
        )

        top3 = comparison_output.get("top3", [])
        selected_titles = [item.get("title", "") for item in top3]
        overall = _normalized_overall(evaluation_output.get("overall_score", 0.0))
        attempt_record = {
            "attempt": attempt,
            "selected": selected_titles,
            "excluded_before": sorted(excluded_titles),
            "overall_score": round(overall, 2),
        }

        # Keep the best-scoring attempt so a worse re-roll never replaces a good one.
        if best is None or overall > best["overall"]:
            best = {
                "overall": overall,
                "comparison_output": comparison_output,
                "sentiment_output": sentiment_output,
                "evaluation_output": evaluation_output,
            }

        # --- Autonomous decision: accept, or re-select and try again ---------
        if not top3:
            attempt_record["decision"] = "stop_no_selection"
            decision_log.append(attempt_record)
            break

        if overall >= SCORE_ACCEPT_THRESHOLD:
            attempt_record["decision"] = "accept_above_threshold"
            decision_log.append(attempt_record)
            break

        if attempt == MAX_SELECTION_ATTEMPTS:
            attempt_record["decision"] = "accept_attempts_exhausted"
            decision_log.append(attempt_record)
            break

        # Drop the films that scored below the bar (or all of them if the score
        # is uniformly low) so the next round must propose different movies.
        per_film_scores = evaluation_output.get("per_film_scores", [])
        weak_titles = {
            score.get("title", "")
            for score in per_film_scores
            if _normalized_overall(score.get("score", 0.0)) < SCORE_ACCEPT_THRESHOLD
        }
        if not weak_titles:
            weak_titles = set(selected_titles)

        next_excluded = excluded_titles | weak_titles
        remaining = candidate_titles - next_excluded
        if len(remaining) < 3:
            attempt_record["decision"] = "accept_insufficient_candidates"
            decision_log.append(attempt_record)
            break

        attempt_record["decision"] = "retry_exclude_weak"
        attempt_record["dropping"] = sorted(weak_titles - excluded_titles)
        decision_log.append(attempt_record)
        excluded_titles = next_excluded
        logger.info(
            "Decision loop: attempt %d scored %.2f (< %.1f); re-selecting without %s",
            attempt,
            overall,
            SCORE_ACCEPT_THRESHOLD,
            sorted(weak_titles),
        )

    assert best is not None
    comparison_output = best["comparison_output"]
    sentiment_output = best["sentiment_output"]
    evaluation_output = best["evaluation_output"]

    write_debug_file(
        run_id,
        "08_decision_loop.txt",
        "Orchestrator autonomous decision loop\n\n"
        f"Preferred genre: {preferred_genre}\n"
        f"Accept threshold: {SCORE_ACCEPT_THRESHOLD} / 10\n"
        f"Max attempts: {MAX_SELECTION_ATTEMPTS}\n"
        f"Chosen overall score: {round(best['overall'], 2)}\n\n"
        f"{format_json(decision_log)}\n",
    )

    enriched_top3 = _attach_showtime_context(
        sentiment_output.get("enriched_top3", []),
        comparison_output.get("all_movies", []),
        parsed_user_location,
    )
    logger.info("Orchestrator completed")
    return {
        "enriched_top3": enriched_top3,
        "all_theaters": _collect_all_theaters(
            comparison_output.get("all_movies", []), parsed_user_location
        ),
        "preferred_genre": sentiment_output.get("preferred_genre", preferred_genre),
        "selection_logic": sentiment_output.get("selection_logic", ""),
        "reviews_fetched": sentiment_output.get("metadata", {}).get("reviews_fetched", {}),
        "overall_score": evaluation_output.get("overall_score", 0.0),
        "per_film_scores": evaluation_output.get("per_film_scores", []),
        "pipeline_feedback": evaluation_output.get("pipeline_feedback", ""),
        "metadata": {
            "discovery": discovery_output.get("metadata", {}),
            "comparison": comparison_output.get("metadata", {}),
            "sentiment": sentiment_output.get("metadata", {}),
            "evaluation": evaluation_output.get("metadata", {}),
            "decision_loop": {
                "attempts": len(decision_log),
                "accept_threshold": SCORE_ACCEPT_THRESHOLD,
                "chosen_overall_score": round(best["overall"], 2),
                "log": decision_log,
            },
            "location": {
                "used": parsed_user_location is not None,
                "provided": user_location is not None,
            },
        },
    }

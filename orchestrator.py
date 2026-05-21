import logging
import time
from collections.abc import Callable
from typing import Any

from comparison_agent import ComparisonAgent
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


def run(preferred_genre: str) -> dict[str, Any]:
    logger.info("Orchestrator started: preferred_genre=%s", preferred_genre)

    discovery_agent = DiscoveryAgent()
    comparison_agent = ComparisonAgent()
    sentiment_agent = SentimentAgent()
    evaluation_agent = EvaluationAgent()

    discovery_output = _run_with_timing("DiscoveryAgent", discovery_agent.run)
    comparison_output = _run_with_timing(
        "ComparisonAgent",
        comparison_agent.run,
        discovery_output,
        preferred_genre,
    )
    sentiment_output = _run_with_timing(
        "SentimentAgent",
        sentiment_agent.run,
        comparison_output,
    )
    evaluation_output = _run_with_timing(
        "EvaluationAgent",
        evaluation_agent.run,
        sentiment_output,
        comparison_output,
    )
    logger.info("Orchestrator completed")
    return {
        "enriched_top3": sentiment_output.get("enriched_top3", []),
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
        },
    }

import json
import logging
from typing import Any

from google.genai import types

from _llm_client import LLMClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EvaluationAgent(LLMClient):
    MODEL_NAME = "gemini-3.1-flash-lite"

    @staticmethod
    def _coerce_output(parsed: dict[str, Any]) -> dict[str, Any]:
        return {
            "overall_score": float(parsed.get("overall_score", 0.0) or 0.0),
            "per_film_scores": parsed.get("per_film_scores", []),
            "pipeline_feedback": parsed.get("pipeline_feedback", ""),
        }

    @staticmethod
    def _fallback_evaluation(
        sentiment_output: dict[str, Any],
        comparison_output: dict[str, Any],
        parse_error: str = "",
    ) -> dict[str, Any]:
        top3 = comparison_output.get("top3", [])
        all_movies = comparison_output.get("all_movies", [])
        enriched_top3 = sentiment_output.get("enriched_top3", [])

        movie_by_title = {m.get("title", ""): m for m in all_movies}
        enriched_by_title = {m.get("title", ""): m for m in enriched_top3}
        sentiment_bonus = {"positive": 1.5, "mixed": 0.8, "negative": 0.2}

        per_film_scores = []
        for item in top3:
            title = item.get("title", "")
            movie = movie_by_title.get(title, {})
            enriched = enriched_by_title.get(title, {})
            vote_avg = float(movie.get("vote_average", 0.0) or 0.0)
            sentiment = str(enriched.get("sentiment", "")).lower()
            explanation = str(enriched.get("explanation", "")).strip()

            score = min(10.0, max(0.0, (vote_avg * 0.9) + sentiment_bonus.get(sentiment, 0.4)))
            feedback = "Genre fit and overall audience score look balanced."
            if sentiment == "mixed":
                feedback = "Audience reception is mixed; managing expectations is important."
            elif sentiment == "negative":
                feedback = "Audience satisfaction is low; alternatives may be stronger."
            elif not explanation:
                feedback = "Explanation content is limited, so the assessment is cautious."

            per_film_scores.append(
                {
                    "title": title,
                    "score": round(score, 1),
                    "feedback": feedback,
                }
            )

        overall = round(
            sum(item["score"] for item in per_film_scores) / len(per_film_scores), 1
        ) if per_film_scores else 0.0

        if parse_error:
            pipeline_feedback = (
                "LLM evaluation output could not be parsed; rule-based fallback scoring was used. "
                "The recommendation chain was still produced and per-film scores were calculated."
            )
        else:
            pipeline_feedback = (
                "Fallback evaluation mode was used. "
                "The recommendation chain was produced and per-film scores were calculated."
            )

        return {
            "overall_score": overall,
            "per_film_scores": per_film_scores,
            "pipeline_feedback": pipeline_feedback,
            "metadata": {"warning": f"fallback_evaluation_used: {parse_error}" if parse_error else "fallback_evaluation_used"},
        }

    def run(
        self,
        sentiment_output: dict[str, Any],
        comparison_output: dict[str, Any],
    ) -> dict[str, Any]:
        enriched_top3 = sentiment_output.get("enriched_top3", [])
        top3 = comparison_output.get("top3", [])
        logger.info(
            "EvaluationAgent started: comparison_top3=%d sentiment_top3=%d",
            len(top3),
            len(enriched_top3),
        )

        if not self.client:
            return {
                "overall_score": 0.0,
                "per_film_scores": [],
                "pipeline_feedback": "",
                "metadata": {"error": "GEMINI_API_KEY is missing in environment variables."},
            }

        prompt_payload = {
            "instruction": (
                "Audit the decision chain below and evaluate genre relevance, explanation quality, "
                "and sentiment consistency. "
                "Negative or mixed sentiment does not automatically mean the selection is bad; "
                "sentiment reflects critic/user reviews, while selection is based on genre match and vote average. "
                "Prioritize genre relevance and explanation quality in scoring over sentiment. "
                "Only penalize when genre match is poor or the explanation is inaccurate. "
                "Return only JSON. Write all feedback fields in English."
            ),
            "expected_schema": {
                "overall_score": 0.0,
                "per_film_scores": [
                    {"title": "Movie Title", "score": 0.0, "feedback": "English feedback"}
                ],
                "pipeline_feedback": "English 2-3 sentences",
            },
            "comparison_output": comparison_output,
            "sentiment_output": sentiment_output,
        }

        try:
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=json.dumps(prompt_payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=1024,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "overall_score": {"type": "number"},
                            "per_film_scores": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "score": {"type": "number"},
                                        "feedback": {"type": "string"},
                                    },
                                    "required": ["title", "score", "feedback"],
                                },
                            },
                            "pipeline_feedback": {"type": "string"},
                        },
                        "required": ["overall_score", "per_film_scores", "pipeline_feedback"],
                    },
                ),
            )
            if isinstance(response.parsed, dict):
                parsed = response.parsed
            else:
                raw_text = response.text or ""
                cleaned = self._extract_json_object(raw_text)
                try:
                    parsed = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    logger.warning("EvaluationAgent JSON parsing failed, using fallback evaluation: %s", exc)
                    return self._fallback_evaluation(
                        sentiment_output=sentiment_output,
                        comparison_output=comparison_output,
                        parse_error=str(exc),
                    )

            output = self._coerce_output(parsed)
            logger.info(
                "EvaluationAgent completed: overall_score=%.2f films_scored=%d",
                output["overall_score"],
                len(output["per_film_scores"]),
            )
            return output
        except Exception as exc:
            logger.exception("EvaluationAgent failed")
            return {
                "overall_score": 0.0,
                "per_film_scores": [],
                "pipeline_feedback": "",
                "metadata": {"error": f"EvaluationAgent failed: {exc}"},
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
            {"id": 101, "title": "Action Horizon", "vote_average": 7.9},
            {"id": 104, "title": "Anatolian Mystery", "vote_average": 8.1},
            {"id": 102, "title": "Romantik Ruzgar", "vote_average": 7.3},
        ],
    }

    mock_sentiment_output = {
        "enriched_top3": [
            {
                "rank": 1,
                "title": "Action Horizon",
                "sentiment": "positive",
                "explanation": "The film meets genre expectations with its high-tempo action.",
                "review_snippets": ["Great pacing.", "Explosive action scenes."],
            },
            {
                "rank": 2,
                "title": "Anatolian Mystery",
                "sentiment": "mixed",
                "explanation": "Atmosphere is strong, though pacing slows in some sections.",
                "review_snippets": ["Strong atmosphere.", "A bit slow in the middle."],
            },
            {
                "rank": 3,
                "title": "Romantik Ruzgar",
                "sentiment": "positive",
                "explanation": "A warm production that stands out for its emotional storytelling.",
                "review_snippets": ["Heartwarming story.", "Good lead chemistry."],
            },
        ],
        "preferred_genre": "Action",
        "selection_logic": "Selection was made based on genre fit and vote average.",
        "metadata": {"reviews_fetched": {"Action Horizon": 5, "Anatolian Mystery": 4, "Romantik Ruzgar": 5}},
    }

    agent = EvaluationAgent()
    result = agent.run(mock_sentiment_output, mock_comparison_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))

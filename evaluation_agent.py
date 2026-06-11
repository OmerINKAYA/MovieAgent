import json
import logging
import os
from typing import Any

from openai import OpenAI

from _llm_client import LLMClient
from debug_logger import format_json, write_debug_file


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EvaluationAgent(LLMClient):
    MODEL_NAME = "nvidia/llama-3.3-nemotron-super-49b-v1"
    LLM_TIMEOUT_SECONDS = 20.0

    def __init__(self) -> None:
        super().__init__()
        api_key = os.getenv("NVIM_API_KEY")
        self.client = (
            OpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key,
                timeout=self.LLM_TIMEOUT_SECONDS,
                max_retries=0,
            )
            if api_key
            else None
        )

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
        run_id: str = "",
    ) -> dict[str, Any]:
        top3 = comparison_output.get("top3", [])
        all_movies = comparison_output.get("all_movies", [])
        enriched_top3 = sentiment_output.get("enriched_top3", [])

        movie_by_title = {m.get("title", ""): m for m in all_movies}
        enriched_by_title = {m.get("title", ""): m for m in enriched_top3}
        preferred_genre = str(comparison_output.get("preferred_genre", "")).strip().lower()
        sentiment_bonus = {"positive": 0.8, "mixed": -0.6, "negative": -1.8}

        per_film_scores = []
        for item in top3:
            title = item.get("title", "")
            movie = movie_by_title.get(title, {})
            enriched = enriched_by_title.get(title, {})
            vote_avg = float(movie.get("vote_average", 0.0) or 0.0)
            if movie.get("source") == "biletinial" and vote_avg <= 5.0:
                vote_avg *= 2
            sentiment = str(enriched.get("sentiment", "")).lower()
            explanation = str(enriched.get("explanation", "")).strip()
            genres = [str(genre).strip().lower() for genre in movie.get("genre_names", [])]
            genre_match = bool(preferred_genre and preferred_genre in genres)
            comment_count = int(movie.get("biletinial_comment_count", 0) or 0)
            comment_confidence = 0.7 if comment_count >= 100 else 0.3 if comment_count >= 20 else -0.4

            score = min(
                10.0,
                max(
                    0.0,
                    (vote_avg * 0.62)
                    + (2.0 if genre_match else -3.0)
                    + sentiment_bonus.get(sentiment, -0.4)
                    + comment_confidence,
                ),
            )
            feedback = "Genre fit, Biletinial comments, and local audience score were judged strictly."
            if not genre_match:
                feedback = "Genre match is weak for the requested preference, so the film is penalized heavily."
            if sentiment == "mixed":
                feedback = "Audience reception is mixed in Biletinial comments; managing expectations is important."
            elif sentiment == "negative":
                feedback = "Audience satisfaction is low or comments contain meaningful complaints; alternatives may be stronger."
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

        output = {
            "overall_score": overall,
            "per_film_scores": per_film_scores,
            "pipeline_feedback": pipeline_feedback,
            "metadata": {"warning": f"fallback_evaluation_used: {parse_error}" if parse_error else "fallback_evaluation_used"},
        }
        write_debug_file(
            run_id,
            "07_evaluation_fallback_answer.txt",
            "EvaluationAgent fallback output\n\n"
            f"Reason: {parse_error or 'fallback_evaluation_used'}\n\n"
            f"{format_json(output)}\n",
        )
        return output

    def run(
        self,
        sentiment_output: dict[str, Any],
        comparison_output: dict[str, Any],
        run_id: str = "",
    ) -> dict[str, Any]:
        enriched_top3 = sentiment_output.get("enriched_top3", [])
        top3 = comparison_output.get("top3", [])
        selected_titles = {item.get("title", "") for item in top3}
        selected_movies = [
            movie
            for movie in comparison_output.get("all_movies", [])
            if movie.get("title", "") in selected_titles
        ]
        slim_comparison_output = {
            "top3": top3,
            "selection_logic": comparison_output.get("selection_logic", ""),
            "preferred_genre": comparison_output.get("preferred_genre", ""),
            "selected_movies": [
                {
                    "title": movie.get("title", ""),
                    "genre_names": movie.get("genre_names", []),
                    "vote_average": movie.get("vote_average", 0.0),
                    "vote_count": movie.get("vote_count", 0),
                    "biletinial_rating": movie.get("biletinial_rating", 0.0),
                    "biletinial_comment_count": movie.get("biletinial_comment_count", 0),
                    "overview": movie.get("overview", ""),
                    "playing_at_count": len(movie.get("playing_at", [])),
                }
                for movie in selected_movies
            ],
        }
        logger.info(
            "EvaluationAgent started: comparison_top3=%d sentiment_top3=%d",
            len(top3),
            len(enriched_top3),
        )

        if not self.client:
            return self._fallback_evaluation(
                sentiment_output=sentiment_output,
                comparison_output=comparison_output,
                parse_error="NVIM_API_KEY is missing.",
                run_id=run_id,
            )

        prompt_payload = {
            "instruction": (
                "Audit the decision chain below and evaluate genre relevance, explanation quality, "
                "and sentiment consistency. "
                "Negative or mixed sentiment does not automatically mean the selection is bad; "
                "sentiment reflects critic/user reviews, while selection is based on genre match and vote average. "
                "Be strict and harsh: heavily penalize weak genre matches, shallow explanations, "
                "low Biletinial comment confidence, and repeated complaints in comments. "
                "A film should not receive a high score unless it clearly matches the preferred genre "
                "and Biletinial comments support the recommendation. "
                "Return only JSON. Write all feedback fields in English."
            ),
            "expected_schema": {
                "overall_score": 0.0,
                "per_film_scores": [
                    {"title": "Movie Title", "score": 0.0, "feedback": "English feedback"}
                ],
                "pipeline_feedback": "English 2-3 sentences",
            },
            "comparison_output": slim_comparison_output,
            "sentiment_output": sentiment_output,
        }
        write_debug_file(
            run_id,
            "06_evaluation_prompt.txt",
            "EvaluationAgent prompt payload sent to NVIDIA\n\n"
            f"Model: {self.MODEL_NAME}\n\n"
            f"{format_json(prompt_payload)}\n",
        )

        try:
            response = self.client.chat.completions.create(
                model=self.MODEL_NAME,
                messages=[{"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)}],
                temperature=0.2,
                max_tokens=2048,
            )
            raw_text = response.choices[0].message.content or ""
            write_debug_file(
                run_id,
                "07_evaluation_llm_answer.txt",
                "EvaluationAgent raw LLM answer\n\n"
                f"Model: {self.MODEL_NAME}\n\n"
                f"{raw_text}\n",
            )
            cleaned = self._extract_json_object(raw_text)
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as exc:
                logger.warning("EvaluationAgent JSON parsing failed, using fallback evaluation: %s", exc)
                return self._fallback_evaluation(
                    sentiment_output=sentiment_output,
                    comparison_output=comparison_output,
                    parse_error=str(exc),
                    run_id=run_id,
                )

            output = self._coerce_output(parsed)
            logger.info(
                "EvaluationAgent completed: overall_score=%.2f films_scored=%d",
                output["overall_score"],
                len(output["per_film_scores"]),
            )
            return output
        except Exception as exc:
            logger.warning("EvaluationAgent failed; using fallback evaluation: %s", exc)
            write_debug_file(
                run_id,
                "07_evaluation_error.txt",
                "EvaluationAgent failed before a valid parsed answer was produced.\n\n"
                f"Error: {exc}\n\n"
                f"Comparison output:\n{format_json(comparison_output)}\n\n"
                f"Sentiment output:\n{format_json(sentiment_output)}\n",
            )
            return self._fallback_evaluation(
                sentiment_output=sentiment_output,
                comparison_output=comparison_output,
                parse_error=f"EvaluationAgent failed: {exc}",
                run_id=run_id,
            )


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

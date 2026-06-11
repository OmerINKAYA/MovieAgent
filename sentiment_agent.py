import json
import logging
import os
from typing import Any

from openai import OpenAI

from _llm_client import LLMClient
from debug_logger import format_json, write_debug_file


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SentimentAgent(LLMClient):
    MODEL_NAME = "meta/llama-3.3-70b-instruct"
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
    def _sentiment_from_vote_average(vote_average: float) -> str:
        if 0.0 <= vote_average <= 5.0:
            if vote_average >= 4.2:
                return "positive"
            if vote_average >= 3.2:
                return "mixed"
            return "negative"
        if vote_average >= 7.0:
            return "positive"
        if vote_average >= 5.0:
            return "mixed"
        return "negative"

    def _fallback_sentiment(
        self,
        top3: list[dict[str, Any]],
        all_movies: list[dict[str, Any]],
        preferred_genre: str,
        selection_logic: str,
        reviews_fetched: dict[str, int] | None = None,
        warning: str = "fallback_sentiment_used",
        run_id: str = "",
    ) -> dict[str, Any]:
        movie_by_title = {movie.get("title", ""): movie for movie in all_movies}
        enriched_top3 = []

        for index, item in enumerate(top3, start=1):
            title = item.get("title", "")
            movie = movie_by_title.get(title, {})
            vote_average = float(movie.get("vote_average", 0.0) or 0.0)
            comments = movie.get("biletinial_comments", [])
            comment_ratings = [
                float(comment.get("rating"))
                for comment in comments
                if isinstance(comment.get("rating"), (int, float))
            ]
            if comment_ratings:
                vote_average = sum(comment_ratings) / len(comment_ratings)
            overview = str(movie.get("overview", "")).strip()
            reason = str(item.get("reason", "")).strip()
            local_score = movie.get("biletinial_rating") or vote_average
            local_count = movie.get("biletinial_comment_count") or len(comments)
            review_snippets = [
                str(comment.get("content", "")).strip()
                for comment in comments[:3]
                if str(comment.get("content", "")).strip()
            ]
            if comments:
                details = (
                    f"Biletinial audience data was used: local score {local_score:.1f}/5 "
                    f"from {local_count} comments. Comment quality and genre fit should be judged strictly. "
                    f"{reason or overview}"
                ).strip()
            else:
                details = reason or overview or "Local rating and available metadata were used for this recommendation."

            enriched_top3.append(
                {
                    "rank": item.get("rank", index),
                    "title": title,
                    "sentiment": self._sentiment_from_vote_average(vote_average),
                    "explanation": details,
                    "review_snippets": review_snippets,
                }
            )

        output = {
            "enriched_top3": enriched_top3,
            "preferred_genre": preferred_genre,
            "selection_logic": selection_logic,
            "metadata": {
                "reviews_fetched": reviews_fetched or {},
                "warning": warning,
            },
        }
        write_debug_file(
            run_id,
            "05_sentiment_fallback_answer.txt",
            "SentimentAgent fallback output\n\n"
            f"Reason: {warning}\n\n"
            f"{format_json(output)}\n",
        )
        return output

    def run(self, comparison_output: dict[str, Any], run_id: str = "") -> dict[str, Any]:
        top3 = comparison_output.get("top3", [])
        all_movies = comparison_output.get("all_movies", [])
        preferred_genre = comparison_output.get("preferred_genre", "")
        selection_logic = comparison_output.get("selection_logic", "")

        logger.info("SentimentAgent started: selected_movies=%d", len(top3))

        if not self.client:
            return self._fallback_sentiment(
                top3=top3,
                all_movies=all_movies,
                preferred_genre=preferred_genre,
                selection_logic=selection_logic,
                warning="NVIM_API_KEY is missing; fallback sentiment was used.",
                run_id=run_id,
            )

        title_to_movie = {movie.get("title"): movie for movie in all_movies}
        reviews_by_title: dict[str, list[dict[str, Any]]] = {}
        reviews_fetched: dict[str, int] = {}
        no_review_context: dict[str, dict[str, Any]] = {}

        try:
            for item in top3:
                title = item.get("title", "")
                movie = title_to_movie.get(title, {})
                reviews = movie.get("biletinial_comments", [])
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
                    "Analyze the user reviews/comments for the 3 movies below. "
                    "Reviews are from Biletinial and may be in Turkish or English. "
                    "For each movie, set sentiment to positive/mixed/negative, "
                    "Write the recommendation explanation in English with 2-3 sentences, and "
                    "extract up to 3 short snippets from reviews in their original language. "
                    "Be strict: do not call sentiment positive unless comments clearly support it. "
                    "Mention meaningful complaints when comments contain them. "
                    "Return only JSON and use only the enriched_top3 key. "
                    "For movies with no reviews, write the explanation using local rating and overview."
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
                            "rating": review.get("rating"),
                            "created_at": review.get("created_at", ""),
                            "venue": review.get("venue", ""),
                        }
                        for review in reviews
                    ]
                    for title, reviews in reviews_by_title.items()
                },
            }
            write_debug_file(
                run_id,
                "04_sentiment_prompt.txt",
                "SentimentAgent prompt payload sent to NVIDIA\n\n"
                f"Model: {self.MODEL_NAME}\n\n"
                f"{format_json(prompt_payload)}\n",
            )

            response = self.client.chat.completions.create(
                model=self.MODEL_NAME,
                messages=[{"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)}],
                temperature=0.4,
                max_tokens=2048,
            )
            raw_text = response.choices[0].message.content or ""
            write_debug_file(
                run_id,
                "05_sentiment_llm_answer.txt",
                "SentimentAgent raw LLM answer\n\n"
                f"Model: {self.MODEL_NAME}\n\n"
                f"{raw_text}\n",
            )
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
        except Exception as exc:
            logger.warning("SentimentAgent failed; using fallback sentiment: %s", exc)
            write_debug_file(
                run_id,
                "05_sentiment_error.txt",
                "SentimentAgent failed before a valid parsed answer was produced.\n\n"
                f"Error: {exc}\n\n"
                f"Top 3 from comparison:\n{format_json(top3)}\n\n"
                f"Reviews fetched:\n{format_json(reviews_fetched)}\n",
            )
            return self._fallback_sentiment(
                top3=top3,
                all_movies=all_movies,
                preferred_genre=preferred_genre,
                selection_logic=selection_logic,
                reviews_fetched=reviews_fetched,
                warning=f"SentimentAgent failed; fallback sentiment was used: {exc}",
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

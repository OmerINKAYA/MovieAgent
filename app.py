import html
import logging
from typing import Any

import gradio as gr
from dotenv import load_dotenv

import orchestrator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


GENRE_CHOICES = [
    "Action",
    "Drama",
    "Comedy",
    "Thriller",
    "Horror",
    "Romance",
    "Science Fiction",
    "Animation",
]


_SENTIMENT_COLORS: dict[str, tuple[str, str]] = {
    "positive": ("#dcfce7", "#166534"),
    "mixed": ("#fef9c3", "#854d0e"),
    "negative": ("#fee2e2", "#991b1b"),
}
_SENTIMENT_DEFAULT_COLORS = ("#e5e7eb", "#374151")


def _sentiment_badge(sentiment: str) -> str:
    normalized = (sentiment or "").strip().lower()
    bg, fg = _SENTIMENT_COLORS.get(normalized, _SENTIMENT_DEFAULT_COLORS)
    label = html.escape(sentiment or "unknown")
    return (
        f'<span style="display:inline-block;padding:4px 10px;border-radius:999px;'
        f'background:{bg};color:{fg};font-size:12px;font-weight:700;text-transform:capitalize;">'
        f"{label}</span>"
    )


def _normalize_score(score: float) -> float:
    """Scale a [0, 1] score to [0, 10]; leave scores already on a 10-point scale unchanged."""
    return score * 10 if score <= 1.0 else score


def _build_results_html(result: dict[str, Any]) -> str:
    enriched_top3 = result.get("enriched_top3", [])
    per_film_scores = result.get("per_film_scores", [])
    score_map = {item.get("title", ""): item for item in per_film_scores}

    cards: list[str] = []
    for movie in enriched_top3[:3]:
        title = html.escape(movie.get("title", "Unknown"))
        sentiment = _sentiment_badge(movie.get("sentiment", "unknown"))
        explanation = html.escape(movie.get("explanation", ""))
        score = score_map.get(movie.get("title", ""), {}).get("score")
        if isinstance(score, (int, float)):
            score_text = f"{int(round(_normalize_score(float(score))))}/10"
        else:
            score_text = "N/A"

        cards.append(
            f"""
            <div style="border:1px solid #e5e7eb;border-radius:12px;padding:16px;background:#ffffff;color:#1a1a1a;">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                <h3 style="margin:0;font-size:1.1rem;font-weight:700;color:#1a1a1a;">{title}</h3>
                {sentiment}
              </div>
              <p style="margin:10px 0 8px 0;line-height:1.45;color:#333333;">{explanation}</p>
              <p style="margin:0;color:#555555;"><strong style="color:#1a1a1a;">Evaluation Score:</strong> {score_text}</p>
            </div>
            """
        )

    overall = result.get("overall_score", 0.0)
    if not isinstance(overall, (int, float)):
        overall = 0.0
    pipeline_feedback = html.escape(result.get("pipeline_feedback", ""))

    return f"""
    <div style="display:grid;gap:12px;">
      {''.join(cards) if cards else '<p>No movie results available.</p>'}
      <div style="border-top:1px solid #e5e7eb;padding-top:12px;">
        <p style="margin:0 0 6px 0;"><strong>Overall Score:</strong> {int(round(_normalize_score(overall)))}/10</p>
        <p style="margin:0;"><strong>Pipeline Feedback:</strong> {pipeline_feedback}</p>
      </div>
    </div>
    """


def find_movies(preferred_genre: str) -> tuple[str, str]:
    try:
        result = orchestrator.run(preferred_genre)
        metadata = result.get("metadata", {})
        error_messages = []
        for stage in ("discovery", "sentiment", "evaluation"):
            stage_error = metadata.get(stage, {}).get("error")
            if stage_error:
                error_messages.append(f"{stage}: {stage_error}")

        if error_messages:
            return "", "Error: " + " | ".join(error_messages)

        return _build_results_html(result), ""
    except Exception as exc:
        logger.exception("App failed while finding movies")
        return "", f"Error: {exc}"


with gr.Blocks(title="Movie Recommender Agent") as demo:
    gr.Markdown("## Movie Recommender Agent")
    with gr.Row():
        genre_dropdown = gr.Dropdown(
            choices=GENRE_CHOICES,
            value="Action",
            label="Preferred Genre",
        )
        find_button = gr.Button("Find Movies", variant="primary")

    error_box = gr.Markdown("")
    results_html = gr.HTML()

    find_button.click(
        fn=find_movies,
        inputs=[genre_dropdown],
        outputs=[results_html, error_box],
    )


if __name__ == "__main__":
    demo.launch()

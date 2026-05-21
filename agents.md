# Multi-Agent Movie Recommendation System

## Project Overview

A multi-agent AI pipeline that recommends currently playing movies in Turkey based on the user's genre preference. The user selects a genre, and the system fetches real-time data from TMDB, analyzes it through a chain of 4 agents, and returns top 3 recommendations with Turkish explanations and a quality evaluation score.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| LLM | Google Gemini (`gemini-3.1-flash-lite`) |
| LLM SDK | `google-genai` (new SDK, NOT `google.generativeai`) |
| Movie Data | TMDB API (free tier) |
| Framework | LangChain (orchestration) |
| UI | Gradio |
| Deploy | HuggingFace Spaces |

---

## Environment Variables

```
TMDB_API_KEY    — TMDB API key
GEMINI_API_KEY  — Google Gemini API key
```

Always read API keys from environment variables. Never hardcode them.

---

## Agent Architecture

### Agent 1 — Discovery Agent (`discovery_agent.py`)
- **LLM:** No
- **Input:** None (reads from TMDB API directly)
- **What it does:** Fetches currently playing movies in Turkey from TMDB `/movie/now_playing` with `region=TR`. Paginates up to 5 pages. Filters by min vote_average 5.0, min vote_count 50, original_language in ["en", "tr"]. Sorts by vote_average descending.
- **Output dict:**
```python
{
    "movies": [ # list of movie dicts
        {
            "id": int,
            "title": str,
            "original_language": str,
            "genre_ids": list[int],
            "vote_average": float,
            "vote_count": int,
            "popularity": float,
            "overview": str,
            "release_date": str,
            "poster_path": str | None
        }
    ],
    "user_preferences": {},   # passthrough, populated later
    "metadata": {
        "total_fetched": int,
        "total_after_filter": int
    }
}
```

---

### Agent 2 — Comparison Agent (`comparison_agent.py`)
- **LLM:** Yes (1 call)
- **Input:** Discovery Agent output dict + `preferred_genre: str`
- **What it does:** Sends the filtered movie list and the user's genre preference to the LLM. The LLM selects the top 3 most suitable films based on genre match and vote_average. Returns structured JSON.
- **LLM config:** `temperature=0.3`, `max_output_tokens=2048`
- **Output dict:**
```python
{
    "top3": [
        {
            "rank": int,        # 1, 2, or 3
            "title": str,
            "reason": str       # Turkish, 1-2 sentences
        }
    ],
    "selection_logic": str,     # Turkish, 2-3 sentences
    "preferred_genre": str,
    "all_movies": list[dict]    # full movie list, passthrough for Agent 3
}
```

---

### Agent 3 — Sentiment & Explanation Agent (`sentiment_agent.py`)
- **LLM:** Yes (1 call)
- **Input:** Comparison Agent output dict
- **What it does:** For each of the 3 selected films, fetches up to 5 English reviews from TMDB `/movie/{movie_id}/reviews`. Sends all reviews to the LLM in a single call. LLM analyzes sentiment and generates a Turkish recommendation explanation per film.
- **LLM config:** `temperature=0.4`, `max_output_tokens=2048`
- **Output dict:**
```python
{
    "enriched_top3": [
        {
            "rank": int,
            "title": str,
            "sentiment": str,           # "positive" | "mixed" | "negative"
            "explanation": str,         # Turkish, 2-3 sentences
            "review_snippets": list[str] # up to 3 short English snippets
        }
    ],
    "preferred_genre": str,
    "selection_logic": str,             # passthrough from Agent 2
    "metadata": {
        "reviews_fetched": dict         # {title: count}
    }
}
```

---

### Agent 4 — Evaluation Agent (`evaluation_agent.py`)
- **LLM:** Yes (1 call)
- **Input:** Sentiment Agent output dict + Comparison Agent output dict
- **What it does:** Audits the entire decision chain. Evaluates genre relevance, explanation quality, and sentiment consistency. Produces a quality score and feedback.
- **LLM config:** `temperature=0.2`, `max_output_tokens=1024`
- **Output dict:**
```python
{
    "overall_score": float,     # 0.0 - 10.0
    "per_film_scores": [
        {
            "title": str,
            "score": float,
            "feedback": str     # Turkish, 1-2 sentences
        }
    ],
    "pipeline_feedback": str    # Turkish, 2-3 sentences
}
```

---

## Data Flow

```
User (preferred_genre)
        │
        ▼
DiscoveryAgent.run()
        │  {"movies": [...], "metadata": {...}}
        ▼
ComparisonAgent.run(discovery_output, preferred_genre)
        │  {"top3": [...], "all_movies": [...]}
        ▼
SentimentAgent.run(comparison_output)
        │  {"enriched_top3": [...]}
        ▼
EvaluationAgent.run(sentiment_output, comparison_output)
        │  {"overall_score": ..., "pipeline_feedback": ...}
        ▼
Orchestrator → Gradio UI
```

---

## File Structure

```
project/
├── agents.md               ← this file
├── discovery_agent.py
├── comparison_agent.py
├── sentiment_agent.py
├── evaluation_agent.py
├── orchestrator.py
├── app.py                  ← Gradio UI
└── requirements.txt
```

---

## Code Conventions

- Each agent lives in its own file with a class named after the agent (e.g. `DiscoveryAgent`)
- Every agent class has a `run()` method as the main entry point
- LLM responses must always be JSON — strip markdown fences before parsing
- Log agent start, input size, and output summary using Python `logging` (INFO level)
- Never raise unhandled exceptions — catch API errors and return meaningful messages
- Use `google-genai` SDK: `from google import genai` and `from google.genai import types`
- Model name for all LLM calls: `gemini-3.1-flash-lite`

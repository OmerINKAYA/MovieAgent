# Multi-Agent Movie Recommendation System

## Project Overview

A multi-agent AI pipeline that recommends currently playing movies in İstanbul cinemas based on the user's genre preference. The user selects a genre, and the system scrapes real-time data from Biletinial, analyzes it through a chain of 4 agents inside an autonomous decision loop, and returns the top 3 recommendations with English explanations and a quality evaluation score.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| LLM (all agents) | Google Gemini (`gemini-3.1-flash-lite-preview`) via `google-genai` SDK |
| Movie Data | Biletinial İstanbul listings (HTML scraping, `biletinial_scraper.py`) |
| Orchestration | Plain Python orchestrator with an autonomous decision loop (`orchestrator.py`) |
| UI | Custom HTML/CSS/JS served by FastAPI (`server.py`, `static/`) |
| Deploy | HuggingFace Spaces (Docker) |

---

## Environment Variables

```
GEMINI_API_KEY  — Google Gemini API key (used by Comparison, Sentiment, and Evaluation agents)
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
- **LLM:** Yes (1 call) — `gemini-2.5-flash-lite` via `google-genai` SDK
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
- **LLM:** Yes (1 call) — `gemini-3.1-flash-lite-preview`
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
- **LLM:** Yes (1 call) — `gemini-3.1-flash-lite-preview`
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
DiscoveryAgent.run()                         (once)
        │  {"movies": [...], "metadata": {...}}
        ▼
┌─────────── decision loop (≤ MAX_SELECTION_ATTEMPTS) ───────────┐
│ ComparisonAgent.run(discovery, genre, exclude_titles, attempt) │
│        │  {"top3": [...], "all_movies": [...]}                 │
│        ▼                                                       │
│ SentimentAgent.run(comparison_output, attempt)                 │
│        │  {"enriched_top3": [...]}                             │
│        ▼                                                       │
│ EvaluationAgent.run(sentiment, comparison, attempt)            │
│        │  {"overall_score": ..., "per_film_scores": [...]}     │
│        ▼                                                       │
│ overall_score ≥ SCORE_ACCEPT_THRESHOLD ?                       │
│   yes → accept and exit loop                                   │
│   no  → exclude the weak films, retry with a new selection     │
└────────────────────────────────────────────────────────────────┘
        │  (best-scoring attempt is kept)
        ▼
Orchestrator → FastAPI JSON → custom web UI
```

The orchestrator owns the autonomous decision: it reads the Evaluation agent's
score and decides whether to accept the picks or drop the weak films and ask
Comparison for a different set. See `08_decision_loop.txt` per run and
`metadata.decision_loop` in the API response.

---

## File Structure

```
project/
├── agents.md               ← this file
├── _llm_client.py          ← shared Gemini client + parsing helpers
├── biletinial_scraper.py   ← Biletinial scraping (the data tool)
├── discovery_agent.py
├── comparison_agent.py
├── sentiment_agent.py
├── evaluation_agent.py
├── orchestrator.py         ← runs the agents + autonomous decision loop
├── server.py               ← FastAPI backend
├── static/                 ← custom HTML/CSS/JS UI
└── requirements.txt
```

---

## Code Conventions

- Each agent lives in its own file with a class named after the agent (e.g. `DiscoveryAgent`)
- Every agent class has a `run()` method as the main entry point
- LLM responses must always be JSON — strip markdown fences before parsing
- Log agent start, input size, and output summary using Python `logging` (INFO level)
- Never raise unhandled exceptions — catch API errors and return meaningful messages
- The `LLMClient` base class builds the shared Gemini client from `GEMINI_API_KEY` and exposes `_gemini_generate(...)` (60 s timeout, automatic retries) plus the static JSON-parsing helpers. Agents do not create their own clients.
- Every LLM agent calls `self._gemini_generate(prompt, model=self.MODEL_NAME, ...)` and parses the JSON from the returned text.
- When an LLM call ultimately fails, agents fall back to rule-based behavior instead of raising.

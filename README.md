---
title: Movie Recommender Agent
sdk: docker
app_port: 7860
---

# Multi-Agent Movie Recommendation System

A multi-agent app that recommends movies currently playing in cinemas in İstanbul. The user picks a genre; the system scrapes live showtimes, ratings, and audience comments from [Biletinial](https://biletinial.com), runs the data through a chain of four agents, and returns the top 3 films with an English explanation, an audience-sentiment label, a quality score, and interactive cinema maps. If the user shares a location, each film also ranks its cinemas by distance.

## Architecture at a glance

```
Browser (static SPA) → FastAPI (server.py) → orchestrator.run()
        └─ Discovery → Comparison → Sentiment → Evaluation ─┐
              ▲  re-select without the weak films           │
              └──────── score < threshold ◄────────────────┘
```

All LLM reasoning runs on **Google Gemini** (`gemini-3.1-flash-lite-preview`).

## Frontend

A custom responsive (web + mobile) frontend in plain HTML/CSS/JS, served by a small **FastAPI** backend — there is no Gradio.

- `server.py` — FastAPI app. Serves the UI and exposes `GET /api/genres` and `POST /api/recommend`. Shapes the orchestrator output into JSON for the UI and surfaces stage errors.
- `static/index.html`, `static/styles.css`, `static/app.js` — the UI. Genres load from the API; results render as movie cards (poster, sentiment badge, score ring, closest cinemas, expandable showtimes). Cinemas are plotted on Leaflet/OpenStreetMap maps, and the location picker is revealed by the "Search with my location" toggle.

Genres are shown to the user in English but sent to the pipeline as Turkish values (e.g. `Action → Aksiyon`), because the Comparison agent matches against Biletinial's Turkish genre names.

Run locally:

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in your keys
uvicorn server:app --reload # or: python server.py
# open http://127.0.0.1:7860
```

## 4-Agent pipeline

The orchestrator (`orchestrator.py`) runs the agents in order, times each stage, writes per-run debug logs under `llm_logs/`, attaches distance/cinema context, and returns the final result.

| Agent | File | Responsibility | LLM |
|---|---|---|---|
| Discovery | `discovery_agent.py` | Runs the Biletinial scraper, keeps only films that have showtime (`playing_at`) data | No |
| Comparison | `comparison_agent.py` | Picks the best 3 films by genre match first, then audience rating / comment count | Google Gemini (`gemini-3.1-flash-lite-preview`) |
| Sentiment | `sentiment_agent.py` | Reads each film's Biletinial comments, assigns sentiment (positive / mixed / negative) and writes the English explanation | Google Gemini (`gemini-3.1-flash-lite-preview`) |
| Evaluation | `evaluation_agent.py` | Audits the whole decision chain and returns an overall score plus per-film scores and feedback | Google Gemini (`gemini-3.1-flash-lite-preview`) |

`_llm_client.py` builds the shared Gemini client (60 s timeout, automatic retries) and holds the JSON/markdown-parsing helpers used by every LLM agent.

## Autonomous decision loop

The orchestrator doesn't just run the agents once — it **decides whether the result is good enough**. After the Evaluation agent scores a selection (0–10), the orchestrator:

1. **Accepts** the picks if the overall score is at/above the threshold (`SCORE_ACCEPT_THRESHOLD = 7.0`).
2. Otherwise **drops the films that scored below the bar** and asks the Comparison agent for a different set, excluding everything already rejected.
3. Repeats up to `MAX_SELECTION_ATTEMPTS = 3` times, then keeps the **best-scoring attempt**.

Each run's decisions are recorded in `llm_logs/<run>/08_decision_loop.txt` and in the API response under `metadata.decision_loop`. This is the project's required autonomous decision loop and its LLM-in-the-loop evaluation framework: the Evaluation agent judges whether the first system succeeded, and the orchestrator acts on that judgement.

## Data source

There is **no TMDB dependency**. All movie data comes from scraping Biletinial's İstanbul cinema listings (`biletinial_scraper.py`):

- The listing page plus the `GetMoreItems` endpoint are paginated to collect up to ~80 films.
- Each film's detail page is parsed for genres, overview, director, duration, age rating, release date, and audience rating.
- Audience comments are fetched via `GetFilmComments`.
- Showtimes per cinema are fetched per available date via the seance endpoints, and each venue's address and lat/lon are scraped (and cached) from its venue page.

Because this is HTML scraping, the parsing regexes can break if Biletinial changes its markup.

## Resilience / fallbacks

Every LLM agent uses the same `GEMINI_API_KEY` and the shared client retries failed calls before giving up. If the key is missing or all retries fail, the app still degrades gracefully:

- **Comparison** reports an error and returns no top 3 when the key is missing.
- **Sentiment** falls back to a rule-based sentiment derived from the audience score.
- **Evaluation** falls back to a rule-based scoring formula (genre match, audience score, sentiment, comment confidence) when the response can't be parsed.

## Location feature

The UI includes an optional Leaflet/OpenStreetMap picker. When "Search with my location" is enabled and the user taps a point on the map, the coordinates are sent to `POST /api/recommend`, distances to each cinema are computed with the haversine formula (`distance_utils.py`), and the closest cinemas are ranked and highlighted per film.

## Environment variables

Read from the environment (or a local `.env`, loaded with `python-dotenv`):

```
GEMINI_API_KEY  — Google Gemini key, used by the Comparison, Sentiment, and Evaluation agents
```

Optional:

```
MOVIE_AGENT_DEBUG_LOG_DIR  — directory for per-run debug logs (defaults to ./llm_logs)
```

## HuggingFace Spaces setup

This is configured as a **Docker** Space (the front matter sets `sdk: docker` and `app_port: 7860`). A Docker Space requires a `Dockerfile` at the repo root that installs `requirements.txt` and starts the server on port 7860, e.g. `uvicorn server:app --host 0.0.0.0 --port 7860`. Add `GEMINI_API_KEY` under **Settings → Variables and secrets** (never commit `.env`).

## Dependencies

```
fastapi            # web backend
uvicorn[standard]  # ASGI server
google-genai       # Gemini SDK (Comparison / Sentiment / Evaluation agents)
requests           # Biletinial scraping
python-dotenv      # loads .env
```

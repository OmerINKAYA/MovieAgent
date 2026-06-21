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
        └─ Discovery → Comparison → Sentiment → Evaluation ─┘
```

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
| Sentiment | `sentiment_agent.py` | Reads each film's Biletinial comments, assigns sentiment (positive / mixed / negative) and writes the English explanation | NVIDIA NIM (`meta/llama-3.3-70b-instruct`) |
| Evaluation | `evaluation_agent.py` | Audits the whole decision chain and returns an overall score plus per-film scores and feedback | NVIDIA NIM (`nvidia/llama-3.3-nemotron-super-49b-v1`) |

`_llm_client.py` holds shared JSON/markdown-parsing helpers used by the LLM agents.

## Data source

There is **no TMDB dependency**. All movie data comes from scraping Biletinial's İstanbul cinema listings (`biletinial_scraper.py`):

- The listing page plus the `GetMoreItems` endpoint are paginated to collect up to ~80 films.
- Each film's detail page is parsed for genres, overview, director, duration, age rating, release date, and audience rating.
- Audience comments are fetched via `GetFilmComments`.
- Showtimes per cinema are fetched per available date via the seance endpoints, and each venue's address and lat/lon are scraped (and cached) from its venue page.

Because this is HTML scraping, the parsing regexes can break if Biletinial changes its markup.

## Resilience / fallbacks

The app degrades gracefully when an LLM key is missing or an API call fails:

- **Comparison** needs `GEMINI_API_KEY`. Without it the stage reports an error and returns no top 3.
- **Sentiment** falls back to a rule-based sentiment derived from the audience score when `NVIM_API_KEY` is missing or the call fails.
- **Evaluation** falls back to a rule-based scoring formula (genre match, audience score, sentiment, comment confidence) when the key is missing or the response can't be parsed.

## Location feature

The UI includes an optional Leaflet/OpenStreetMap picker. When "Search with my location" is enabled and the user taps a point on the map, the coordinates are sent to `POST /api/recommend`, distances to each cinema are computed with the haversine formula (`distance_utils.py`), and the closest cinemas are ranked and highlighted per film.

## Environment variables

Read from the environment (or a local `.env`, loaded with `python-dotenv`):

```
GEMINI_API_KEY  — Google Gemini key, required by the Comparison agent
NVIM_API_KEY    — NVIDIA NIM key, used by the Sentiment and Evaluation agents (optional; falls back if absent)
```

Optional:

```
MOVIE_AGENT_DEBUG_LOG_DIR  — directory for per-run debug logs (defaults to ./llm_logs)
```

## HuggingFace Spaces setup

This is configured as a **Docker** Space (the front matter sets `sdk: docker` and `app_port: 7860`). A Docker Space requires a `Dockerfile` at the repo root that installs `requirements.txt` and starts the server on port 7860, e.g. `uvicorn server:app --host 0.0.0.0 --port 7860`. Add `GEMINI_API_KEY` and `NVIM_API_KEY` under **Settings → Variables and secrets** (never commit `.env`).

## Dependencies

```
fastapi            # web backend
uvicorn[standard]  # ASGI server
google-genai       # Gemini SDK (Comparison agent)
openai             # OpenAI-compatible client for NVIDIA NIM (Sentiment / Evaluation agents)
requests           # Biletinial scraping
python-dotenv      # loads .env
```

---
title: Movie Recommender Agent
sdk: docker
app_port: 7860
---

# Multi-Agent Movie Recommendation System

A multi-agent app that recommends movies currently playing in cinemas in İstanbul. The user picks a genre; the system scrapes live showtimes, ratings, and audience comments from [Biletinial](https://biletinial.com), runs the data through a chain of four agents, and returns the top 3 films with an English explanation, an audience-sentiment label, a quality score, and interactive cinema maps. If the user shares a location, each film also ranks its cinemas by distance.

## Executive summary

This project turns a live cinema-listings website into a self-checking recommendation engine. A single user input — a genre — flows through a deterministic data layer and four cooperating agents, and comes back as three vetted film recommendations with reasons, audience sentiment, a quality score, and maps to the nearest screenings.

The design rests on three ideas. First, **real data over a static API**: every recommendation is grounded in what is actually showing in İstanbul today, scraped directly from Biletinial (showtimes, audience ratings, and real viewer comments) with no TMDB or third-party movie database in the loop. Second, **a labour-divided agent chain**: Discovery gathers and filters, Comparison selects the best three by genre fit, Sentiment reads the audience comments and writes the explanation, and Evaluation audits the whole decision. Only the last three use an LLM (Google Gemini); Discovery is pure code. Third — and what makes this more than a prompt chain — **an autonomous decision loop**: the orchestrator reads the Evaluation agent's 0–10 score, and if the picks fall short of the acceptance threshold it drops the weak films and asks Comparison for a different set, retrying up to three times and keeping the best-scoring attempt. The Evaluation agent is the system judging its own work, and the orchestrator acts on that judgement.

Reliability is a first-class concern throughout. Every LLM agent degrades to a rule-based fallback if the API key is missing or a call ultimately fails, so the pipeline always returns a usable answer rather than an error. Scraping results are cached for 24 hours, LLM calls retry on transient failures, and every run writes a full step-by-step debug trace (prompts, raw answers, and the decision log) to disk. The result is delivered through a lightweight FastAPI backend and a custom plain HTML/CSS/JS frontend with Leaflet maps — no Gradio, no heavy frontend framework — and ships as a Docker image suitable for HuggingFace Spaces.

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

## Practitioner notes

These are the things worth knowing before you change, deploy, or debug this code — the parts that aren't obvious from the architecture diagram.

**The scraper is the most fragile component, and the cache hides it.** `biletinial_scraper.py` parses Biletinial's HTML with hand-written regexes against specific markup (`eventListContainer`, `yds_genres_link`, `yn_cinema`, the `İzleyici Puanı` rating block, etc.). If Biletinial changes its templates, these silently return empty results rather than throwing, and the downstream agents will just see fewer films. When recommendations suddenly look thin or wrong, suspect the scraper first. Note that results are cached for 24 hours under `cache/biletinial_istanbul_80.json`, so during development you may be debugging stale data — delete the cache file (or pass `use_cache=False`) to force a fresh scrape.

**A full cold scrape is slow and sequential.** For up to ~80 films the scraper fetches the listing, then for each film a detail page, its comments, its available seance dates, and a seance page per date, plus a venue page per cinema. There is no concurrency. The 24-hour cache and the in-memory venue cache are what make this practical — the first uncached request can take a while, so don't mistake that latency for a hang. If you ever need to speed this up, parallelising the per-film enrichment is the highest-leverage change.

**`agents.md` is partially out of date — trust the code, not that file.** It still describes an earlier TMDB-based design (`region=TR`, `gemini-2.5-flash-lite`, Turkish-language reasons, vote-count filters). The shipped system scrapes Biletinial, runs every LLM agent on `gemini-3.1-flash-lite-preview`, and produces English `reason`/`explanation`/`feedback` text. Use `agents.md` for the high-level intent and the data-flow diagram, but rely on the source files for actual behaviour, field names, and model strings.

**Genre values are Turkish on purpose.** The UI shows English labels but sends Turkish values (`Action → Aksiyon`) because Comparison matches against Biletinial's Turkish genre names. If you add a genre in `server.py`'s `GENRE_CHOICES`, the value must match Biletinial's spelling exactly, or genre matching (and the Evaluation agent's genre-fit penalty) will silently fail for it.

**Fallbacks mean failures are quiet by design.** A missing or broken `GEMINI_API_KEY` does not crash the app: Comparison returns an empty top 3 (and surfaces an error to the UI), while Sentiment and Evaluation fall back to rule-based scoring derived from the audience rating, sentiment, and comment count. This is great for resilience but means a degraded run can look like a successful one. To confirm the LLMs actually ran, check the per-run files in `llm_logs/<run>/` — `fallback_*` filenames and `warning` fields in the output indicate the rule-based path was taken.

**Score scales are normalised in two places.** The Evaluation LLM is asked for 0–10 but occasionally answers 0–1; `orchestrator._normalized_overall` and `server._normalize_score` both rescale so the `7.0` accept threshold and the displayed score stay consistent. If you change the scoring scale, update both.

**Every run leaves a full audit trail.** The orchestrator writes numbered debug files per run (`00_all_biletinial_films` → `08_decision_loop`), including each agent's exact prompt, the raw LLM answer, and the decision log. This is the fastest way to understand why a particular recommendation was made or why the loop retried. In Docker these go to `/tmp/llm_logs` (set via `MOVIE_AGENT_DEBUG_LOG_DIR` in the Dockerfile) because the working directory may be read-only on Spaces.

**There is no automated test suite.** Each agent file has an `if __name__ == "__main__"` block with mock inputs for manual smoke-testing (e.g. `python comparison_agent.py`), and `discovery_agent.py` will hit the live site. These are handy for isolating a single stage, but treat them as smoke tests, not coverage — there are no assertions guarding regressions.

## Dependencies

```
fastapi            # web backend
uvicorn[standard]  # ASGI server
google-genai       # Gemini SDK (Comparison / Sentiment / Evaluation agents)
requests           # Biletinial scraping
python-dotenv      # loads .env
```

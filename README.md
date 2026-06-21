---
title: Movie Recommender Agent
sdk: docker
app_port: 7860
---

# Multi-Agent Movie Recommendation System

This project is a multi-agent movie recommendation app. The user selects a genre, and the system fetches now-playing movies in Turkey from TMDB, evaluates candidates through four agents, and returns top recommendations with Turkish explanations and quality scoring.

## Frontend

A custom responsive (web + mobile) frontend built with plain HTML/CSS/JS, served by a small **FastAPI** backend:

- `server.py` — FastAPI app: serves the UI and exposes `GET /api/genres` and `POST /api/recommend`.
- `static/index.html`, `static/styles.css`, `static/app.js` — the UI. Cinemas are shown on Leaflet/OpenStreetMap maps; the location picker is revealed by the "Search with my location" toggle.

Run locally:

```bash
uvicorn server:app --reload     # or: python server.py
# open http://127.0.0.1:7860
```

## 4-Agent Architecture

The pipeline runs in this order:

```
User (genre) → Discovery → Comparison → Sentiment → Evaluation → UI
```

| Agent | Responsibility | LLM |
|---|---|---|
| Discovery Agent | Fetches `/movie/now_playing` for `region=TR`, paginates, filters by score/language | No |
| Comparison Agent | Chooses top 3 films from filtered list based on genre relevance and rating | Yes |
| Sentiment Agent | Fetches TMDB reviews for selected films and generates sentiment + Turkish explanations | Yes |
| Evaluation Agent | Audits full decision chain and returns overall/per-film quality feedback | Yes |

## HuggingFace Spaces Setup

Deploy as a **Docker** Space (the frontend is FastAPI, not Gradio). Key files:
- `server.py` as the app entrypoint (serves on port 7860)
- `static/` for the HTML/CSS/JS frontend
- `requirements.txt` for dependencies

Before running the Space, add these secrets in **Settings → Variables and secrets**:

```
TMDB_API_KEY
GEMINI_API_KEY
```

The app reads these keys from environment variables (or local `.env` with `python-dotenv`).

## Dependencies

```
google-genai
requests
gradio
python-dotenv
langchain
```

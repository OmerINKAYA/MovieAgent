---
title: Movie Recommender Agent
sdk: gradio
sdk_version: "4.0"
app_file: app.py
---

# Multi-Agent Movie Recommendation System

This project is a multi-agent movie recommendation app. The user selects a genre, and the system fetches now-playing movies in Turkey from TMDB, evaluates candidates through four agents, and returns top recommendations with Turkish explanations and quality scoring.

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

Use these repository files:
- `app.py` as the Gradio entrypoint
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

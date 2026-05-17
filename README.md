---
title: Movie Recommender Agent
sdk: gradio
sdk_version: "4.0"
app_file: app.py
---

# 🎬 Multi-Agent Movie Recommendation System

A multi-agent AI pipeline that recommends currently playing movies in Turkey based on the user's genre preference. Built as a university project.

## How It Works

The user selects a genre. Four agents run in sequence:

```
User (genre) → Discovery → Comparison → Sentiment → Evaluation → UI
```

| Agent | Task | LLM |
|---|---|---|
| Discovery | Fetches now-playing movies from TMDB for Turkey, filters by score and language | ❌ |
| Comparison | Selects top 3 films based on genre match and vote average | ✅ |
| Sentiment & Explanation | Fetches TMDB reviews, analyzes sentiment, generates Turkish explanations | ✅ |
| Evaluation | Audits the full decision chain, gives a quality score | ✅ |

## Tech Stack

- **LLM:** Google Gemini (`gemini-3-flash-preview`) via `google-genai` SDK
- **Movie Data:** TMDB API (free tier, `region=TR`)
- **UI:** Gradio
- **Deploy:** HuggingFace Spaces

## Local Setup

```bash
git clone https://github.com/OmerINKAYA/MovieAgent.git
cd MovieAgent

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
TMDB_API_KEY=your_tmdb_api_key
GEMINI_API_KEY=your_gemini_api_key
```

Run the app:

```bash
python app.py
```

## HuggingFace Spaces Deploy

This project is designed to run on HuggingFace Spaces. Before deploying, add the following secrets under **Settings → Variables and secrets**:

```
TMDB_API_KEY
GEMINI_API_KEY
```

Do **not** push your `.env` file or API keys to the repository.

## Project Structure

```
project/
├── agents.md
├── discovery_agent.py
├── comparison_agent.py
├── sentiment_agent.py
├── evaluation_agent.py
├── orchestrator.py
├── app.py
├── requirements.txt
└── README.md
```

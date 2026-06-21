"""FastAPI backend that serves the custom frontend and exposes the
movie-recommendation pipeline as a JSON API.

Replaces the old Gradio app. Run with:

    uvicorn server:app --reload
    # or
    python server.py
"""

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import orchestrator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# English label shown in the UI -> Turkish value sent to the pipeline.
# The comparison agent matches against Biletinial's Turkish genre names, so the
# value must stay Turkish even though we display English to the user.
GENRE_CHOICES = [
    ("Action", "Aksiyon"),
    ("Animation", "Animasyon"),
    ("Family", "Aile"),
    ("Documentary", "Belgesel"),
    ("Biography", "Biyografi"),
    ("Science Fiction", "Bilim Kurgu"),
    ("Drama", "Dram"),
    ("Fantasy", "Fantastik"),
    ("Thriller", "Gerilim"),
    ("Mystery", "Gizem"),
    ("Comedy", "Komedi"),
    ("Horror", "Korku"),
    ("Adventure", "Macera"),
    ("Music", "Müzik"),
    ("Musical", "Müzikal"),
    ("Detective", "Polisiye"),
    ("Romance", "Romantik"),
    ("War", "Savaş"),
    ("Crime", "Suç"),
    ("History", "Tarihi"),
]


app = FastAPI(title="Movie Recommender Agent")


class Location(BaseModel):
    lat: float
    lon: float


class RecommendRequest(BaseModel):
    genre: str
    use_location: bool = False
    location: Location | None = None


# --------------------------------------------------------------------------- #
# Result shaping helpers
# --------------------------------------------------------------------------- #
def _normalize_score(score: Any) -> int | None:
    """Scale a [0, 1] score to [0, 10]; leave 10-point scores unchanged."""
    if not isinstance(score, (int, float)):
        return None
    value = score * 10 if score <= 1.0 else score
    return int(round(value))


def _map_link(venue: dict[str, Any]) -> str:
    """Google Maps link for a venue — by coordinates when available, else a text search."""
    lat = venue.get("lat")
    lon = venue.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"

    query = quote_plus(
        " ".join(
            part
            for part in [str(venue.get("cinema", "")), str(venue.get("address", "")), "İstanbul"]
            if part
        )
    )
    return f"https://www.google.com/maps/search/?api=1&query={query}"


def _unique_mappable_venues(venues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, float | None, float | None]] = set()
    unique: list[dict[str, Any]] = []
    for venue in venues:
        lat = venue.get("lat")
        lon = venue.get("lon")
        key = (
            str(venue.get("cinema", "")),
            float(lat) if isinstance(lat, (int, float)) else None,
            float(lon) if isinstance(lon, (int, float)) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(venue)
    return unique


def _closest_venues(venues: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    with_distance = [
        venue
        for venue in _unique_mappable_venues(venues)
        if isinstance(venue.get("distance_km"), (int, float))
    ]
    return sorted(with_distance, key=lambda venue: float(venue["distance_km"]))[:limit]


def _top_venues(venues: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    """Up to `limit` unique cinemas, closest first when distances are known."""
    unique = _unique_mappable_venues(venues)
    if any(isinstance(v.get("distance_km"), (int, float)) for v in unique):
        unique.sort(
            key=lambda v: float(v["distance_km"])
            if isinstance(v.get("distance_km"), (int, float))
            else float("inf")
        )
    return unique[:limit]


def _slim_theater(venue: dict[str, Any]) -> dict[str, Any]:
    """Minimal theater entry for map pins."""
    return {
        "cinema": str(venue.get("cinema", "") or "Cinema"),
        "lat": float(venue["lat"]),
        "lon": float(venue["lon"]),
        "distance_km": float(venue["distance_km"]) if isinstance(venue.get("distance_km"), (int, float)) else None,
    }


def _mappable_theaters(venues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Unique theaters from a venue list that have coordinates, as slim pins."""
    return [
        _slim_theater(v)
        for v in _unique_mappable_venues(venues)
        if isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lon"), (int, float))
    ]


def _shape_venue(venue: dict[str, Any]) -> dict[str, Any]:
    lat = venue.get("lat")
    lon = venue.get("lon")
    saloons = []
    for saloon in venue.get("saloons", []):
        saloons.append(
            {
                "saloon": str(saloon.get("saloon", "") or "Salon"),
                "format": str(saloon.get("format", "") or ""),
                "times": [str(time) for time in saloon.get("times", [])],
            }
        )
    return {
        "cinema": str(venue.get("cinema", "") or "Cinema"),
        "address": str(venue.get("address", "") or ""),
        "date": str(venue.get("date", "") or ""),
        "distance_km": float(venue["distance_km"]) if isinstance(venue.get("distance_km"), (int, float)) else None,
        "lat": float(lat) if isinstance(lat, (int, float)) else None,
        "lon": float(lon) if isinstance(lon, (int, float)) else None,
        "map_link": _map_link(venue),
        "saloons": saloons,
    }


def _shape_result(result: dict[str, Any], location_warning: str = "") -> dict[str, Any]:
    enriched_top3 = result.get("enriched_top3", [])
    score_map = {item.get("title", ""): item for item in result.get("per_film_scores", [])}

    movies: list[dict[str, Any]] = []
    for movie in enriched_top3[:3]:
        venues = movie.get("playing_at", []) or []
        title = str(movie.get("title", "Unknown"))
        movies.append(
            {
                "title": title,
                "sentiment": str(movie.get("sentiment", "unknown") or "unknown"),
                "explanation": str(movie.get("explanation", "") or ""),
                "score": _normalize_score(score_map.get(title, {}).get("score")),
                "poster": str(movie.get("poster_path", "") or ""),
                "closest": [
                    {"cinema": str(v.get("cinema", "Unknown")), "distance_km": float(v["distance_km"])}
                    for v in _closest_venues(venues)
                ],
                "venues": [_shape_venue(v) for v in _top_venues(venues, limit=3)],
                "theaters": _mappable_theaters(venues),
                "total_venues": len(_unique_mappable_venues(venues)),
            }
        )

    metadata = result.get("metadata", {})
    location_meta = metadata.get("location", {})
    return {
        "ok": True,
        "genre": result.get("preferred_genre", ""),
        "overall_score": _normalize_score(result.get("overall_score", 0.0)),
        "pipeline_feedback": str(result.get("pipeline_feedback", "") or ""),
        "location_used": bool(location_meta.get("used")),
        "location_warning": location_warning,
        "movies": movies,
        "all_theaters": [_slim_theater(t) for t in result.get("all_theaters", [])],
    }


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/api/genres")
def genres() -> dict[str, Any]:
    return {
        "genres": [{"label": label, "value": value} for label, value in GENRE_CHOICES],
        "default": GENRE_CHOICES[0][1],
    }


@app.post("/api/recommend")
def recommend(req: RecommendRequest) -> dict[str, Any]:
    location_warning = ""
    user_location: dict[str, float] | None = None

    if req.use_location:
        if req.location is None:
            return {"ok": False, "error": "Please pick your location on the map first."}
        user_location = {"lat": req.location.lat, "lon": req.location.lon}

    try:
        result = orchestrator.run(req.genre, user_location=user_location)
    except Exception as exc:  # noqa: BLE001 - surface any pipeline failure to the UI
        logger.exception("Pipeline failed while finding movies")
        return {"ok": False, "error": f"Something went wrong: {exc}"}

    metadata = result.get("metadata", {})
    stage_errors = [
        f"{stage}: {metadata.get(stage, {}).get('error')}"
        for stage in ("discovery", "comparison", "sentiment", "evaluation")
        if metadata.get(stage, {}).get("error")
    ]
    if stage_errors:
        return {"ok": False, "error": " | ".join(stage_errors)}

    if not result.get("enriched_top3"):
        return {
            "ok": False,
            "error": "No movies were found right now. The cinema listing source may be temporarily unavailable — please try again.",
        }

    return _shape_result(result, location_warning)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=7860, reload=False)

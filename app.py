import html
import json
import logging
from typing import Any
from urllib.parse import quote_plus

import gradio as gr
from dotenv import load_dotenv

import orchestrator


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


GENRE_CHOICES = [
    "Aksiyon",
    "Animasyon",
    "Aile",
    "Belgesel",
    "Bilim Kurgu",
    "Dram",
    "Fantastik",
    "Gerilim",
    "Komedi",
    "Korku",
    "Macera",
    "Romantik",
    "Savaş",
    "Suç",
    "Tarih",
]

LOCATION_HEAD = """
<script>
window.movieAgentSelectedLocation = null;
window.addEventListener("message", function(event) {
  if (!event.data || event.data.type !== "movie-agent-location") return;
  window.movieAgentSelectedLocation = {lat: event.data.lat, lon: event.data.lon};
  const status = document.getElementById("selected-location-status");
  if (status) {
    status.textContent = `Selected location: ${event.data.lat.toFixed(5)}, ${event.data.lon.toFixed(5)}`;
  }
});
</script>
"""


def _location_selector_html() -> str:
    srcdoc = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map { height: 100%; margin: 0; }
    .hint { position:absolute; z-index:500; top:10px; left:10px; background:white; padding:8px 10px; border-radius:6px; font:14px sans-serif; box-shadow:0 2px 8px #0002; }
  </style>
</head>
<body>
  <div class="hint">Click your location in İstanbul</div>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const map = L.map('map').setView([41.015, 29.02], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }).addTo(map);
    let marker = null;
    map.on('click', (event) => {
      const lat = event.latlng.lat;
      const lon = event.latlng.lng;
      if (marker) marker.setLatLng(event.latlng);
      else marker = L.marker(event.latlng).addTo(map);
      marker.bindPopup('Selected location').openPopup();
      window.parent.postMessage({type: 'movie-agent-location', lat, lon}, '*');
    });
  </script>
</body>
</html>
"""
    return (
        '<div style="display:grid;gap:8px;margin:8px 0 16px 0;">'
        '<p id="selected-location-status" style="margin:0;color:#4b5563;">'
        'If location search is enabled, click your location on the map before finding movies.'
        '</p>'
        f'<iframe srcdoc="{html.escape(srcdoc, quote=True)}" width="100%" height="320" '
        'style="border:1px solid #d1d5db;border-radius:8px;" loading="lazy"></iframe>'
        '</div>'
    )


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


def _parse_location_json(location_json: str) -> tuple[dict[str, float] | None, str]:
    if not location_json:
        return None, ""

    try:
        data = json.loads(location_json)
    except json.JSONDecodeError:
        return None, "Location could not be read from the browser."

    if isinstance(data, dict) and data.get("error"):
        return None, f"Location unavailable: {data.get('error')}"

    try:
        return {"lat": float(data["lat"]), "lon": float(data["lon"])}, ""
    except (KeyError, TypeError, ValueError):
        return None, "Location data was incomplete."


def _map_link(venue: dict[str, Any]) -> str:
    lat = venue.get("lat")
    lon = venue.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=16/{lat}/{lon}"

    query = quote_plus(
        " ".join(
            part
            for part in [
                str(venue.get("cinema", "")),
                str(venue.get("address", "")),
                "İstanbul",
            ]
            if part
        )
    )
    return f"https://www.openstreetmap.org/search?query={query}"


def _map_iframe(venue: dict[str, Any]) -> str:
    lat = venue.get("lat")
    lon = venue.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return ""

    bbox = f"{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}"
    src = (
        "https://www.openstreetmap.org/export/embed.html"
        f"?bbox={bbox}&layer=mapnik&marker={lat},{lon}"
    )
    return (
        f'<iframe src="{html.escape(src)}" width="100%" height="220" '
        'style="border:1px solid #d1d5db;border-radius:8px;margin-top:10px;" '
        'loading="lazy"></iframe>'
    )


def _unique_mappable_venues(venues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, float | None, float | None]] = set()
    unique = []
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


def _multi_marker_map_iframe(venues: list[dict[str, Any]], movie_title: str) -> str:
    markers = []
    for venue in _unique_mappable_venues(venues):
        lat = venue.get("lat")
        lon = venue.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        markers.append(
            {
                "lat": float(lat),
                "lon": float(lon),
                "cinema": str(venue.get("cinema", "")),
                "address": str(venue.get("address", "")),
                "distance": venue.get("distance_km"),
            }
        )

    if not markers:
        return ""

    center_lat = sum(marker["lat"] for marker in markers) / len(markers)
    center_lon = sum(marker["lon"] for marker in markers) / len(markers)
    markers_json = json.dumps(markers, ensure_ascii=False)
    srcdoc = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>html, body, #map {{ height: 100%; margin: 0; }}</style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const markers = {markers_json};
    const map = L.map('map').setView([{center_lat}, {center_lon}], 11);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap'
    }}).addTo(map);
    const group = L.featureGroup();
    markers.forEach((item) => {{
      const distance = typeof item.distance === 'number' ? `<br>${{item.distance.toFixed(2)}} km away` : '';
      const marker = L.marker([item.lat, item.lon]).bindPopup(`<strong>${{item.cinema}}</strong><br>${{item.address || ''}}${{distance}}`);
      marker.addTo(group);
    }});
    group.addTo(map);
    if (markers.length > 1) map.fitBounds(group.getBounds().pad(0.2));
  </script>
</body>
</html>
"""
    return (
        f'<iframe title="{html.escape(movie_title)} cinema map" '
        f'srcdoc="{html.escape(srcdoc, quote=True)}" width="100%" height="360" '
        'style="border:1px solid #d1d5db;border-radius:8px;margin:10px 0;" loading="lazy"></iframe>'
    )


def _format_saloons(venue: dict[str, Any]) -> str:
    rows = []
    for saloon in venue.get("saloons", []):
        name = html.escape(str(saloon.get("saloon", "Salon")))
        version = html.escape(str(saloon.get("format", "")))
        times = ", ".join(str(time) for time in saloon.get("times", []))
        rows.append(
            f"<li><strong>{name}</strong>"
            f"{f' ({version})' if version else ''}: "
            f"{html.escape(times) if times else 'No listed time'}</li>"
        )
    return "<ul style=\"margin:8px 0 0 18px;padding:0;\">" + "".join(rows) + "</ul>" if rows else ""


def _build_playing_at_html(movie: dict[str, Any]) -> str:
    venues = movie.get("playing_at", [])
    if not venues:
        return ""

    closest = _closest_venues(venues)
    closest_text = ""
    if closest:
        closest_rows = "".join(
            f"<li>{html.escape(str(venue.get('cinema', 'Unknown')))}"
            f" - {float(venue['distance_km']):.2f} km</li>"
            for venue in closest
        )
        closest_text = (
            '<div style="margin:8px 0;color:#166534;">'
            '<strong>Closest cinema saloons:</strong>'
            f'<ol style="margin:6px 0 0 20px;padding:0;">{closest_rows}</ol>'
            '</div>'
        )

    big_map = _multi_marker_map_iframe(venues, str(movie.get("title", "Film")))
    venue_cards = []
    for index, venue in enumerate(venues[:8]):
        cinema = html.escape(str(venue.get("cinema", "Unknown cinema")))
        date = html.escape(str(venue.get("date", "")))
        address = html.escape(str(venue.get("address", "")))
        distance = venue.get("distance_km")
        distance_text = f" · {distance:.2f} km" if isinstance(distance, (int, float)) else ""
        link = html.escape(_map_link(venue))
        venue_cards.append(
            f"""
            <div style="border:1px solid #e5e7eb;border-radius:8px;padding:12px;margin-top:10px;background:#fafafa;">
              <p style="margin:0;"><strong>{cinema}</strong>{html.escape(distance_text)}</p>
              {f'<p style="margin:4px 0 0 0;color:#4b5563;">{address}</p>' if address else ''}
              {f'<p style="margin:4px 0 0 0;color:#4b5563;">{date}</p>' if date else ''}
              {_format_saloons(venue)}
              <p style="margin:8px 0 0 0;"><a href="{link}" target="_blank" rel="noopener">Open in map</a></p>
            </div>
            """
        )

    more_text = ""
    if len(venues) > 8:
        more_text = f'<p style="margin:8px 0 0 0;color:#6b7280;">Showing 8 of {len(venues)} cinema entries.</p>'

    return closest_text + big_map + "".join(venue_cards) + more_text


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
                <details style="flex:1;">
                  <summary style="cursor:pointer;font-size:1.1rem;font-weight:700;color:#1a1a1a;">{title}</summary>
                  {_build_playing_at_html(movie)}
                </details>
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
    location_warning = html.escape(result.get("location_warning", ""))

    return f"""
    <div style="display:grid;gap:12px;">
      {f'<p style="margin:0;color:#854d0e;background:#fef9c3;padding:10px;border-radius:8px;">{location_warning}</p>' if location_warning else ''}
      {''.join(cards) if cards else '<p>No movie results available.</p>'}
      <div style="border-top:1px solid #e5e7eb;padding-top:12px;">
        <p style="margin:0 0 6px 0;"><strong>Overall Score:</strong> {int(round(_normalize_score(overall)))}/10</p>
        <p style="margin:0;"><strong>Pipeline Feedback:</strong> {pipeline_feedback}</p>
      </div>
    </div>
    """


def find_movies(preferred_genre: str, use_location: bool, location_json: str) -> tuple[str, str]:
    try:
        user_location, location_warning = _parse_location_json(location_json) if use_location else (None, "")
        if use_location and not user_location:
            return "", location_warning or "Please click your location on the map first."
        result = orchestrator.run(preferred_genre, user_location=user_location)
        if use_location and not user_location and not location_warning:
            location_warning = "Location was requested but was not provided by the browser."
        if location_warning:
            result["location_warning"] = location_warning
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
            value="Aksiyon",
            label="Preferred Genre",
        )
        find_button = gr.Button("Find Movies", variant="primary")
    use_location_checkbox = gr.Checkbox(label="Search with my location", value=False)
    gr.HTML(_location_selector_html())
    location_state = gr.Textbox(visible=False, value="")

    error_box = gr.Markdown("")
    results_html = gr.HTML()

    find_button.click(
        fn=find_movies,
        inputs=[genre_dropdown, use_location_checkbox, location_state],
        outputs=[results_html, error_box],
        js="""
        async (genre, useLocation, locationJson) => {
            if (!useLocation) {
                return [genre, useLocation, ""];
            }
            if (!window.movieAgentSelectedLocation) {
                return [genre, useLocation, JSON.stringify({error: "Please click your location on the map first."})];
            }
            return [genre, useLocation, JSON.stringify(window.movieAgentSelectedLocation)];
        }
        """,
    )


if __name__ == "__main__":
    demo.launch(head=LOCATION_HEAD)

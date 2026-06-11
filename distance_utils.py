import math
from typing import Any


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_user_location(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None

    try:
        lat = float(value.get("lat"))
        lon = float(value.get("lon"))
    except (TypeError, ValueError):
        return None

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon}


def add_distances_to_playing_at(
    playing_at: list[dict[str, Any]],
    user_location: dict[str, float] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not user_location:
        return playing_at, None

    enriched = []
    nearest: dict[str, Any] | None = None
    for venue in playing_at:
        item = {**venue}
        lat = item.get("lat")
        lon = item.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            distance = haversine_km(user_location["lat"], user_location["lon"], float(lat), float(lon))
            item["distance_km"] = round(distance, 2)
            if nearest is None or item["distance_km"] < nearest.get("distance_km", float("inf")):
                nearest = item
        enriched.append(item)

    return enriched, nearest

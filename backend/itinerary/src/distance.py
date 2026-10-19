"""Travel distance/time matrix between destinations (WBS 3.2).

get_matrix() tries three sources in this order:
1. JSON cache in data/cache/      - free and instant
2. Google Distance Matrix API     - real road data, costs money, needs a key
3. Haversine "fake" matrix        - straight line x road factor, offline, APPROX
   (with config.USE_REGION_SPEEDS on, hill-country legs are driven slower; see road_speed_kmh)

Matrix shape (same for every source):
    matrix[origin_id][dest_id] = {"distance_km": ..., "duration_min": ..., "source": ...}
"source" is "google" or "haversine", so approximate values are always labelled.
"""

import hashlib
import json
import math
import os
import urllib.parse
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv

from src import config
from src.models import Location, TripRequest

Matrix = dict[str, dict[str, dict]]

EARTH_RADIUS_KM = 6371.0


class MissingApiKeyError(RuntimeError):
    """Raised when Google is requested but no API key is configured."""


class GoogleMatrixError(RuntimeError):
    """Raised when the Google API rejects a whole request."""


# ---------- Haversine (offline) ----------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (straight-line) distance between two points, in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _entry(distance_km: float, duration_min: float, source: str) -> dict:
    return {
        "distance_km": round(distance_km, 3),
        "duration_min": round(duration_min, 2),
        "source": source,
    }


def road_speed_kmh(place: Location, fallback_kmh: float = config.AVG_ROAD_SPEED_KMH) -> float:
    """Road speed around a place: its region's speed, or the fallback average outside every region."""
    for _name, lat_min, lat_max, lng_min, lng_max, speed in config.ROAD_SPEED_REGIONS:
        if lat_min <= place.lat <= lat_max and lng_min <= place.lng <= lng_max:
            return speed
    return fallback_kmh


def _driving_min(a: Location, b: Location, km: float, avg_speed_kmh: float) -> float:
    """Driving time for km of road: one average speed, or half the road in each end's region."""
    if not config.USE_REGION_SPEEDS:
        return km / avg_speed_kmh * 60
    half = km / 2
    return (half / road_speed_kmh(a, avg_speed_kmh) + half / road_speed_kmh(b, avg_speed_kmh)) * 60


def _fake_entry(a: Location, b: Location, avg_speed_kmh: float, road_factor: float) -> dict:
    """Estimated road distance and driving time between two places."""
    if a.id == b.id:
        return _entry(0.0, 0.0, "haversine")
    km = haversine_km(a.lat, a.lng, b.lat, b.lng) * road_factor
    return _entry(km, _driving_min(a, b, km, avg_speed_kmh), "haversine")


def build_fake_matrix(
    destinations: Sequence[Location],
    avg_speed_kmh: float = config.AVG_ROAD_SPEED_KMH,
    road_factor: float = config.ROAD_DISTANCE_FACTOR,
) -> Matrix:
    """Offline matrix for every ordered pair: haversine x road factor, time from average speed."""
    if avg_speed_kmh <= 0:
        raise ValueError("avg_speed_kmh must be > 0")
    return {
        a.id: {b.id: _fake_entry(a, b, avg_speed_kmh, road_factor) for b in destinations}
        for a in destinations
    }


# ---------- Google Distance Matrix API ----------

def _read_api_key() -> str:
    """Load .env and return the key, or raise a clear error."""
    load_dotenv(config.BASE_DIR / ".env")
    key = os.getenv(config.GOOGLE_API_KEY_ENV)
    if not key:
        raise MissingApiKeyError(
            f"{config.GOOGLE_API_KEY_ENV} is not set. Add it to .env, or use use_google=False."
        )
    return key


def _batches(items: Sequence, size: int) -> list[Sequence]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _fetch_batch(origins: Sequence[Location], targets: Sequence[Location], api_key: str) -> dict:
    """One HTTP request to the Distance Matrix API (driving, metric)."""
    params = {
        "origins": "|".join(f"{d.lat},{d.lng}" for d in origins),
        "destinations": "|".join(f"{d.lat},{d.lng}" for d in targets),
        "mode": "driving",
        "units": "metric",
        "key": api_key,
    }
    url = f"{config.GOOGLE_MATRIX_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=config.GOOGLE_TIMEOUT_S) as response:
        data = json.load(response)
    if data.get("status") != "OK":
        raise GoogleMatrixError(
            f"Distance Matrix API returned {data.get('status')}: {data.get('error_message', '')}"
        )
    return data


def _google_entry(origin: Location, target: Location, element: dict) -> dict:
    """Convert one API element; fall back to the haversine estimate if Google has no route."""
    if origin.id == target.id:
        return _entry(0.0, 0.0, "google")
    if element.get("status") == "OK":
        return _entry(element["distance"]["value"] / 1000, element["duration"]["value"] / 60, "google")
    return _fake_entry(origin, target, config.AVG_ROAD_SPEED_KMH, config.ROAD_DISTANCE_FACTOR)


def get_google_matrix(destinations: Sequence[Location], api_key: str | None = None) -> Matrix:
    """Real road matrix from Google, requested in blocks that stay within the per-request limit."""
    api_key = api_key or _read_api_key()
    matrix: Matrix = {d.id: {} for d in destinations}
    for origins in _batches(destinations, config.GOOGLE_BATCH_SIZE):
        for targets in _batches(destinations, config.GOOGLE_BATCH_SIZE):
            data = _fetch_batch(origins, targets, api_key)
            for origin, row in zip(origins, data["rows"]):
                for target, element in zip(targets, row["elements"]):
                    matrix[origin.id][target.id] = _google_entry(origin, target, element)
    return matrix


# ---------- Cache ----------

def _fake_tag() -> str:
    """Fake results depend on the config estimates, so they are part of the cache key."""
    tag = f"haversine-speed{config.AVG_ROAD_SPEED_KMH}-factor{config.ROAD_DISTANCE_FACTOR}"
    if config.USE_REGION_SPEEDS:  # flag off keeps the old tag, so old cache files still match
        regions = hashlib.sha256(repr(config.ROAD_SPEED_REGIONS).encode()).hexdigest()[:8]
        tag += f"-regions{regions}"
    return tag


def _place_keys(places: Sequence[Location]) -> list[str]:
    """Sorted "id@lat,lng" keys, so a moved place (e.g. a new START point) misses the cache."""
    return sorted(f"{p.id}@{p.lat},{p.lng}" for p in places)


def _cache_path(cache_dir: Path, ids: list[str], tag: str) -> Path:
    """File name from the source and the *set* of place keys (order does not matter)."""
    digest = hashlib.sha256(f"{tag}|{','.join(ids)}".encode()).hexdigest()[:16]
    return cache_dir / f"{tag.split('-')[0]}_{digest}.json"


def _load_cache(path: Path, ids: list[str]) -> Matrix | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["matrix"] if data.get("ids") == ids else None


def _save_cache(path: Path, ids: list[str], tag: str, matrix: Matrix) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ids": ids, "tag": tag, "matrix": matrix}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_matrix(
    destinations: Sequence[Location],
    use_google: bool = False,
    cache_dir: str | Path = config.CACHE_DIR,
    api_key: str | None = None,
) -> Matrix:
    """Cache first; on a miss use Google (if enabled) or the fake matrix, then save to cache."""
    ids = _place_keys(destinations)
    tag = "google" if use_google else _fake_tag()
    path = _cache_path(Path(cache_dir), ids, tag)

    cached = _load_cache(path, ids)
    if cached is not None:
        return cached

    if use_google:
        matrix = get_google_matrix(destinations, api_key)
    else:
        matrix = build_fake_matrix(destinations)
    _save_cache(path, ids, tag, matrix)
    return matrix


# ---------- Start point ----------

def start_location(trip: TripRequest) -> Location:
    """The trip's start point as a Location with id START, so it can join the matrix."""
    return Location(id=config.START_NODE_ID, lat=trip.start_lat, lng=trip.start_lng)


def get_matrix_with_start(
    destinations: Sequence[Location],
    trip: TripRequest,
    **kwargs,
) -> Matrix:
    """Same as get_matrix(), with the START point added as an extra row and column."""
    if any(d.id == config.START_NODE_ID for d in destinations):
        raise ValueError(f"destination id {config.START_NODE_ID!r} is reserved for the start point")
    return get_matrix([start_location(trip), *destinations], **kwargs)

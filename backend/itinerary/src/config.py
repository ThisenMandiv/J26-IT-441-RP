"""Configurable constants for the itinerary optimizer.

All weights and estimated values live here so they can be tuned (or later
learned from preference data) without rewriting the pipeline.
Values marked APPROX are placeholder estimates, not measured data.
"""

from datetime import time
from pathlib import Path

# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DESTINATIONS_FILE = DATA_DIR / "destinations.json"
CACHE_DIR = DATA_DIR / "cache"  # Google Distance Matrix results are cached here

# --- Sri Lanka bounding box (used to validate coordinates) ---
SL_MIN_LAT = 5.85
SL_MAX_LAT = 9.90
SL_MIN_LNG = 79.50
SL_MAX_LNG = 81.95

# --- Default trip settings ---
DEFAULT_DAY_START = time(8, 0)
DEFAULT_DAY_END = time(18, 0)
DEFAULT_VISIT_DURATION_MIN = 60  # APPROX: used if a destination has no estimate

# --- Offline travel estimate (haversine fake matrix) ---
AVG_ROAD_SPEED_KMH = 40.0  # APPROX: typical Sri Lankan road average
ROAD_DISTANCE_FACTOR = 1.3  # APPROX: road distance / straight-line distance

# --- Google Distance Matrix API (key is read from .env, never stored here) ---
GOOGLE_API_KEY_ENV = "GOOGLE_MAPS_API_KEY"
GOOGLE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GOOGLE_BATCH_SIZE = 10  # 10 origins x 10 destinations = 100 elements, the per-request limit
GOOGLE_TIMEOUT_S = 30

# --- Travel cost ---
TRAVEL_COST_PER_KM_LKR = 100.0  # APPROX: hired car / tuk-tuk rate

# --- Joint objective weights (sum to 1.0; tune or learn later) ---
WEIGHT_DISTANCE = 0.25
WEIGHT_COST = 0.25
WEIGHT_TIME = 0.25
WEIGHT_OPENING_HOURS = 0.25

# --- Budget ---
BUDGET_OVERRUN_TOLERANCE = 0.0  # fraction over the daily budget before flagging

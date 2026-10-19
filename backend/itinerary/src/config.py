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

# --- Graph edge weight (WBS 3.3) ---
START_NODE_ID = "START"  # graph/matrix id of the trip's start point
# Edge weight combines travel time and travel cost, reusing the objective weights above.
EDGE_WEIGHTS = {"time": WEIGHT_TIME, "cost": WEIGHT_COST}
# Scales turn minutes and LKR into comparable unit-free numbers.
EDGE_TIME_SCALE_MIN = 60.0  # one hour of driving = 1.0
# APPROX: cost of one hour of driving at the average speed (40 km/h x 100 LKR/km = 4000 LKR) = 1.0
EDGE_COST_SCALE_LKR = AVG_ROAD_SPEED_KMH * TRAVEL_COST_PER_KM_LKR

# --- A* heuristic bounds (WBS 3.4) ---
# The heuristic must never overestimate, so it assumes the best case for every km.
MAX_PLAUSIBLE_SPEED_KMH = 100.0  # Sri Lankan expressway speed limit: no leg is faster on average
# Must be <= every per-km rate used to build edges. Lower it if cheaper transport is added.
MIN_TRAVEL_COST_PER_KM_LKR = TRAVEL_COST_PER_KM_LKR

# --- Day scheduling (WBS 3.6) ---
MAX_WAIT_MIN = 60  # APPROX: longest the traveller will wait for a place to open

# --- Plan objective (src/objective.py) ---
# One number per complete itinerary: reward minus penalties (higher is better).
# Each raw total is divided by its scale first, so the weights compare like with like.
# APPROX: hand-picked starting values, to be tuned (or learned) later.
OBJECTIVE_WEIGHTS = {
    "score": 10.0,  # reward per point of destination score (each place scores 0..1)
    "travel_time": 1.0,  # penalty per hour of driving
    "spend": 1.0,  # penalty per 10,000 LKR planned (entry + travel)
    "wait": 1.0,  # penalty per hour spent waiting for places to open
    "unscheduled": 2.0,  # penalty per place that could not be scheduled
    "overrun": 5.0,  # penalty per 10,000 LKR over the daily budgets
}
# Weight settings used by scripts/evaluate.py, so results are not tied to one choice.
# APPROX: chosen once by hand before any evaluation run, not tuned on the results.
EVALUATION_WEIGHT_SETTINGS = {
    "default": OBJECTIVE_WEIGHTS,
    # a traveller who mostly cares about money: spending and overruns cost 3x more
    "budget": {**OBJECTIVE_WEIGHTS, "spend": 3.0, "overrun": 15.0},
    # a traveller who hates sitting in a car or waiting: 3x travel and waiting penalties
    "time": {**OBJECTIVE_WEIGHTS, "travel_time": 3.0, "wait": 3.0},
}
OBJECTIVE_TIME_SCALE_MIN = 60.0  # 1 hour = 1.0
OBJECTIVE_MONEY_SCALE_LKR = 10_000.0  # 10,000 LKR = 1.0

# Coverage floor: a plan should visit at least this share of the input places.
# Every place short of the floor costs COVERAGE_PENALTY extra (on top of "unscheduled"),
# so a plan that visits (almost) nothing can never win just by avoiding all costs.
# The same under every weight setting: it is a sanity rule, not a traveller preference.
# APPROX: chosen so the sequential plan beats the empty plan in all 15 scenarios x
# 3 weight settings (worst case S10 "budget": empty was 63 points ahead without the floor).
COVERAGE_FLOOR = 0.3  # share of input places
COVERAGE_PENALTY = 20.0  # per place below the floor

# --- Joint optimizer (src/joint.py) ---
JOINT_MAX_ITERATIONS = 2000  # candidate changes tried per restart
JOINT_SEED = 42  # fixed random seed, so results are repeatable
JOINT_DROP_POOL = 3  # "drop" picks among this many lowest-value scheduled stops
JOINT_RESTARTS = 5  # restart 0 starts from the sequential plan, the others from random visit orders
# Simulated annealing: sometimes accept a worse change to escape local optima.
# Probability of accepting a change that lowers the score by d: exp(-d / T).
# T falls geometrically from START to END over each restart. Set USE_ANNEALING = False
# for plain hill climbing (only strictly better changes are kept).
JOINT_USE_ANNEALING = True
JOINT_ANNEAL_START_TEMP = 2.0  # APPROX: a 2-point loss is accepted ~37% of the time at the start
JOINT_ANNEAL_END_TEMP = 0.01  # near the end it is effectively hill climbing

# --- Exact benchmark (src/exact.py) ---
EXACT_MAX_PLACES = 8  # exhaustive search is only run on trips this small

# --- Budget ---
BUDGET_OVERRUN_TOLERANCE = 0.0  # fraction over the daily budget before flagging
BUDGET_RESERVE_PCT = 0.10  # APPROX: share of the total kept back for unplanned spending
BUDGET_SPLIT_METHOD = "proportional"  # "proportional" (to planned cost) or "equal"

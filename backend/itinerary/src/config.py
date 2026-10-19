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

# --- Regional road speeds (version 5, src/distance.py) ---
# Off = one AVG_ROAD_SPEED_KMH for every leg, as before. On = a place's road speed comes
# from the first region box it falls in; places outside every box (the coast and the
# plains) keep AVG_ROAD_SPEED_KMH, so that average stays the fallback. A leg is assumed
# to run half in each end's region: time = km/2 / speed(a) + km/2 / speed(b).
# Only the haversine estimate uses this; Google times are real and already include hills.
USE_REGION_SPEEDS = False
# (name, lat_min, lat_max, lng_min, lng_max, speed_kmh)
ROAD_SPEED_REGIONS = [
    # APPROX: central highlands box (Kandy, Nuwara Eliya, Ella, Horton Plains, Adam's Peak);
    # winding, steep roads. Speed is a hand-picked estimate, not measured.
    ("hill country", 6.55, 7.45, 80.45, 81.15, 25.0),
]

# --- Google Distance Matrix API (key is read from .env, never stored here) ---
GOOGLE_API_KEY_ENV = "GOOGLE_MAPS_API_KEY"
GOOGLE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
GOOGLE_BATCH_SIZE = 10  # 10 origins x 10 destinations = 100 elements, the per-request limit
GOOGLE_TIMEOUT_S = 30

# --- Travel cost ---
TRAVEL_COST_PER_KM_LKR = 100.0  # APPROX: hired car / tuk-tuk rate

# --- Transport modes per leg (version 5, src/transport.py) ---
# Off = every leg is driven at TRAVEL_COST_PER_KM_LKR, exactly as before version 5.
# On  = each leg uses the mode with the lowest weighted cost under the traveller's objective
#       weights: w_travel_time x hours + w_spend x LKR / OBJECTIVE_MONEY_SCALE_LKR.
# A mode's time = driving time (from the matrix) x AVG_ROAD_SPEED_KMH / its speed_kmh,
# plus wait_min (e.g. waiting for a bus). The car's speed equals AVG_ROAD_SPEED_KMH, so a
# car leg takes exactly the old driving time and costs exactly the old rate.
# max_km: the mode is not offered for longer legs (None = no limit).
USE_TRANSPORT_MODES = False
TRANSPORT_MODES = {
    # hired car with driver, the pre-version-5 assumption (same speed and rate as above)
    "car": {"speed_kmh": AVG_ROAD_SPEED_KMH, "cost_per_km_lkr": TRAVEL_COST_PER_KM_LKR,
            "wait_min": 0, "max_km": None},
    # APPROX: public bus. Slower (stops, no overtaking), plus an average wait at the stand.
    # Fare per traveller; Sri Lankan long-distance fares are roughly 3-5 LKR/km.
    "bus": {"speed_kmh": 25.0, "cost_per_km_lkr": 5.0, "wait_min": 15, "max_km": None},
    # APPROX: walking pace, free, only for short legs
    "walk": {"speed_kmh": 4.5, "cost_per_km_lkr": 0.0, "wait_min": 0, "max_km": 3.0},
}

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
# Must be <= every per-km rate used to build edges. With transport modes off only the car
# rate is used. With them on, the cheapest mode sets the bound (walking is free, so the
# cost part of the heuristic becomes 0: weaker, but never an overestimate).
# routing.haversine_heuristic reads transport.min_cost_per_km(), which picks the right one
# at call time, so switching the flag on at run time can never make A* inadmissible.
MIN_TRAVEL_COST_PER_KM_LKR = TRAVEL_COST_PER_KM_LKR  # modes off
MIN_TRAVEL_COST_PER_KM_LKR_MODES = min(TRAVEL_COST_PER_KM_LKR,
                                       *(m["cost_per_km_lkr"] for m in TRANSPORT_MODES.values()))

# --- Day scheduling (WBS 3.6) ---
MAX_WAIT_MIN = 60  # APPROX: longest the traveller will wait for a place to open

# --- Lunch break (version 5, src/scheduler.py) ---
# Off = no lunch, as before. On = every day that reaches the window gets one lunch stop
# (a non-destination stop in DayPlan.lunch) that STARTS between WINDOW_START and WINDOW_END:
#   - free inside the window            -> lunch now, where the traveller is
#   - free before it, but the next visit would end after WINDOW_END
#                                       -> lunch first, at WINDOW_START. The idle time until then
#                                          counts as waiting in the objective and, like waiting for
#                                          a place to open, may be at most MAX_WAIT_MIN; otherwise
#                                          that stop is retried later in the day
#   - the day's last stop ends inside the window -> lunch after it
# A day whose activity ends before the window (or starts after it) has no lunch stop.
USE_LUNCH_BREAK = False
LUNCH_WINDOW_START = time(12, 30)  # APPROX: earliest lunch start
LUNCH_WINDOW_END = time(13, 30)  # APPROX: latest lunch start
LUNCH_DURATION_MIN = 45  # APPROX
LUNCH_COST_LKR = 1500.0  # APPROX: rice and curry at a local restaurant, one traveller

# --- Per-day start times and evening drives (version 5, src/scheduler.py) ---
# Per-day start times are a traveller input: TripRequest.day_starts (None = day_start
# every day, as before). Evening drive: when the morning drive makes a day's FIRST stop
# infeasible (e.g. it closes at noon), the traveller may drive there the evening before,
# if the previous day's last activity + that drive ends by day_end + the limit. They
# then start the day at the place. TripRequest.evening_drive_limit_min sets the limit per
# trip; None = EVENING_DRIVE_LIMIT_MIN when USE_EVENING_DRIVE is on, else 0 (no evening drives).
USE_EVENING_DRIVE = False
EVENING_DRIVE_LIMIT_MIN = 120  # APPROX: at most 2 hours of driving after day_end

# --- Evaluation verdict (version 6, scripts/evaluate.py) ---
# Off = the joint-vs-sequential verdict judges waiting by wait_min (waiting for places to
# open only), as in v1-v5. On = it uses total_wait_min instead (that plus idle time before
# lunch), which is the waiting the objective counts. Only the verdict changes, never a plan.
# Needs rows with total_wait_min (scripts/evaluate_v5.py adds it).
VERDICT_USE_TOTAL_WAIT = False

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

# Opening-hour conflicts: every scheduled stop that breaks its place's opening hours
# (starts before opening, ends after closing, or is cut short) costs CONFLICT_PENALTY.
# Only plans built WITHOUT the hours check (the naive baseline) can have such stops, so
# this stops them from earning reward for visiting a closed place.
# Rule for the value: one visit can add at most w_score x 1.0 + w_unscheduled + COVERAGE_PENALTY
# (= 10 + 2 + 20 = 32 under every evaluation weight setting, 52 with COVERAGE_PENALTY = 40 in
# the sensitivity check), so a penalty above that means a conflicting visit can never raise
# the score. APPROX: 60 was picked from that rule, not tuned on results.
# Same under every weight setting: like the coverage floor, it is a sanity rule, not a preference.
CONFLICT_PENALTY = 60.0  # per scheduled stop with at least one opening-hour conflict

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
# Block move (v4): take 2..JOINT_BLOCK_MAX_LEN consecutive stops of one day and move them,
# in the same order, to another day or position. One change then keeps a nearby group of
# places together, where single moves break the day's timing one stop at a time.
# Off = exactly the v3 optimizer (same random choices, same plans).
JOINT_USE_BLOCK_MOVES = False
JOINT_BLOCK_MAX_LEN = 4  # APPROX: about one day's worth of stops in these trips

# --- Exact benchmark (src/exact.py) ---
EXACT_MAX_PLACES = 8  # exhaustive search is only run on trips this small

# --- Daily living costs (version 5, src/scheduler.make_day_plan and src/budget.py) ---
# Off = a day costs only entry fees + travel, as before. On = every day (also an empty
# one: the traveller still eats and sleeps) adds food and "other" costs, and every day
# except the last adds one night of accommodation (an n-day trip has n-1 nights; the trip
# starts at the start point on the morning of day 1). Budget reports then split the cost
# into accommodation / transport / food / activities / other (budget.cost_breakdown).
# Food: FOOD_PER_DAY_LKR covers breakfast, dinner and snacks. Lunch is always counted too:
# as the lunch stop's cost when USE_LUNCH_BREAK is on, otherwise as LUNCH_COST_LKR per day.
USE_DAILY_COSTS = False
ACCOMMODATION_PER_NIGHT_LKR = 5000.0  # APPROX: budget guesthouse or small hotel, one room
FOOD_PER_DAY_LKR = 2500.0  # APPROX: breakfast, dinner, water and snacks, one traveller
OTHER_PER_DAY_LKR = 500.0  # APPROX: tips, small purchases

# --- Budget ---
BUDGET_OVERRUN_TOLERANCE = 0.0  # fraction over the daily budget before flagging
BUDGET_RESERVE_PCT = 0.10  # APPROX: share of the total kept back for unplanned spending
BUDGET_SPLIT_METHOD = "proportional"  # "proportional" (to planned cost) or "equal"

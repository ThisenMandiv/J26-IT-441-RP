# Component 2: Budget-Aware Multi-Day Itinerary Optimizer

Project J26-IT-441 (AI-Powered Smart Travel Planning & Navigation System for Sri Lanka), SLIIT final-year research project. This folder is my component only. Other components (recommendation, offline nav, cloud sync) belong to teammates, so never touch files outside backend/itinerary.

## What it does

Input: ranked destinations from Component 1 (id, name, lat, lng, category, cost_lkr, visit_duration_min, opening_time, closing_time, score) plus a trip request (num_days, total_budget_lkr, start point, daily start/end time).
Output: a day-by-day itinerary (ordered stops, arrival/departure times, travel time and cost between stops, daily cost, budget overrun flags).

## Novelty (what I am marked on)

Dijkstra, A\*, TSP approximation and greedy scheduling are established. My contribution is the JOINT CONSTRAINT MODEL: one objective function optimizing distance, cost, time and opening hours together, plus day-wise budget distribution and overrun detection. Always keep a SEQUENTIAL BASELINE (optimize distance first, then check hours and budget) to compare against.

## Pipeline (my WBS)

3.1 input validation -> 3.2 distance/time matrix (Google Distance Matrix API, cached) -> 3.3 weighted graph (NetworkX) -> 3.4 Dijkstra and A\* -> 3.5 TSP approximation -> 3.6 greedy day scheduling + opening-hours check -> 3.7 day-wise budget allocation and overrun alerts -> 3.8 tests.

## Tech stack

Python 3.13, NetworkX, pandas, NumPy, Pydantic, pytest, matplotlib, FastAPI (later, POST /itinerary). OR-Tools only as an optional benchmark.

## Rules

- Build the classical optimizer first. Do not add ML until I ask in a specific task. ML may come later (learning objective weights from preference data), so keep all weights and estimated values (visit duration, travel time) in one place (src/config.py, src/objective.py) so they can be replaced later without rewriting the pipeline.
- Work in small steps and do only what I ask in each task.
- Keep code simple and readable: type hints, short comments, small functions.
- Every module needs pytest tests. Run them and show me the result.
- Google Maps API key goes in .env, never in code. Cache API results in data/cache/. Provide a haversine-based fake matrix so everything runs offline with no key.
- Data in data/ is mock data. Say clearly when values are approximate.
- After each task, explain each new file in plain language, because I must defend it in my viva.

## Evaluation

Total travel-time reduction (%), budget-adherence rate, opening-hour conflict rate. Compare against manually planned itineraries and the sequential baseline.


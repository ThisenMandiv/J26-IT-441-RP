# Itinerary optimizer API (Component 2)

HTTP layer over the budget-aware multi-day itinerary optimizer. The API adds no planning
logic of its own: every plan comes from `src/` (sequential baseline or joint local search),
and every number in a response is the optimizer's own output (`tests/test_api.py` checks this).

> **Data honesty.** Travel times are offline estimates (straight-line distance x 1.3 at APPROX
> road speeds) unless the server has a Google key. Transport fares, food, accommodation and other
> living costs are APPROX values from `src/config.py`. The example places below are MOCK data
> from `data/destinations.json`. Every response repeats this in `warnings`.

## Run locally

From `backend/itinerary`:

```powershell
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

- Interactive docs (generated from the models): <http://127.0.0.1:8000/docs>
- Health check: `curl http://127.0.0.1:8000/health`
- Tests: `venv\Scripts\python.exe -m pytest tests/test_api.py`

**Google Maps (optional).** Put `GOOGLE_MAPS_API_KEY=...` in `backend/itinerary/.env` on the server
(copy `.env.example`; `.env` is git-ignored). Only that file is read. The key is never sent to
clients. Without it, or if a Google request fails, the API uses the offline estimate and says so
with `"travel_times": "estimated"` (and a warning). Google results are cached in `data/cache/`.

## Endpoints

| Method | Path          | What it does |
|--------|---------------|--------------|
| GET    | `/health`     | Service is up; where travel times will come from; profiles |
| POST   | `/itinerary`  | Trip + candidate places → day-by-day plan |
| POST   | `/reoptimize` | The user's edited plan (reordered, stop added or removed) → improved plan, searched **from that plan** |
| POST   | `/validate`   | A plan as it stands → opening-hour, timing and budget problems. The plan is not changed |

### Options (`options` object, all optional)

| Field          | Values | Default | Used by |
|----------------|--------|---------|---------|
| `method`       | `"joint"`, `"sequential"` | `"joint"` | /itinerary |
| `profile`      | `"realistic"`, `"basic"` | `"realistic"` | all |
| `weights`      | `"default"`, `"budget"`, `"time"` | `"default"` | all (in /validate only for the transport mode per leg) |
| `seed`         | integer | `42` | /itinerary (joint), /reoptimize |
| `time_limit_s` | `0 < t <= 60` | `10` | /itinerary (joint), /reoptimize |

- **Profiles.** `realistic` turns on every version 5 rule for this request only: transport modes
  (car / bus / walk per leg), slower hill-country roads, the lunch break, evening drives, and daily
  living costs (food, accommodation, other). `basic` uses the config defaults (all of these off),
  which reproduces the v1–v4 evaluation setting. Per-day start times (`trip.day_starts`) are a
  traveller input and work under both profiles. No config default is changed by a request.
- **Weights presets** are `config.EVALUATION_WEIGHT_SETTINGS`: `budget` = spending x3 and overruns
  x3; `time` = travel time x3 and waiting x3.
- **Time limit.** Joint search stops at `time_limit_s` and returns the best plan found so far,
  with `status.search_time_capped: true` and a warning. A capped result may differ between two
  identical requests, because how far the search gets depends on server speed. An uncapped
  result is fully repeatable for the same seed. On the 15 mock places a full joint search takes
  about 1–2 s on the development laptop, so the 10 s cap is a safety limit and is rarely hit.
- **Joint vs sequential.** Joint never returns a plan that scores lower than the sequential plan.
  When it finds nothing better, it returns the sequential plan and adds a warning that says so.
  On small trips this is common.

Requests run one at a time (a lock keeps one request's profile flags away from another's).

## Component 1 contract (input)

`destinations` is the ranked list from Component 1. Each record:

| Field                | Type          | Rule |
|----------------------|---------------|------|
| `id`                 | string        | unique in the request; `"START"` is reserved |
| `name`               | string        | |
| `lat`, `lng`         | number        | inside Sri Lanka (lat 5.85–9.90, lng 79.50–81.95) |
| `category`           | string        | e.g. `heritage`, `nature` (shown on the day cards) |
| `cost_lkr`           | number        | entry fee per traveller, `>= 0` |
| `visit_duration_min` | integer       | `> 0` |
| `opening_time`       | `"HH:MM"`     | |
| `closing_time`       | `"HH:MM"`     | after `opening_time` |
| `score`              | number        | `0..1`, Component 1's ranking score |

`trip` (the trip form):

| Field                     | Type | Default | Rule |
|---------------------------|------|---------|------|
| `num_days`                | int  | | `>= 1` |
| `total_budget_lkr`        | number | | `> 0`; and at least the living costs (realistic profile, see Errors) |
| `start_lat`, `start_lng`  | number | | inside Sri Lanka |
| `day_start`, `day_end`    | `"HH:MM"` | `08:00`, `18:00` | `day_end` after `day_start` |
| `day_starts`              | list of `"HH:MM"` | `null` | one per day, each before `day_end` |
| `evening_drive_limit_min` | int | `null` | `null` = config default (120 min under realistic, 0 under basic) |

## POST /itinerary

Request (MOCK places, abbreviated to three):

```json
{
  "trip": {"num_days": 2, "total_budget_lkr": 60000, "start_lat": 7.2906, "start_lng": 80.6337,
           "day_start": "08:00", "day_end": "18:00"},
  "destinations": [
    {"id": "D02", "name": "Temple of the Sacred Tooth Relic, Kandy", "lat": 7.2936, "lng": 80.6413,
     "category": "religious", "cost_lkr": 2000, "visit_duration_min": 90,
     "opening_time": "05:30", "closing_time": "20:00", "score": 0.92},
    {"id": "D05", "name": "Gregory Lake, Nuwara Eliya", "lat": 6.9566, "lng": 80.7779,
     "category": "nature", "cost_lkr": 200, "visit_duration_min": 90,
     "opening_time": "07:00", "closing_time": "18:30", "score": 0.75},
    {"id": "D06", "name": "Horton Plains National Park", "lat": 6.8023, "lng": 80.8070,
     "category": "nature", "cost_lkr": 7500, "visit_duration_min": 240,
     "opening_time": "06:00", "closing_time": "16:00", "score": 0.84}
  ],
  "options": {"method": "joint", "weights": "default", "seed": 42}
}
```

Response (real output for that request; `runtime_s` rounded; day 2 shortened):

```json
{
  "travel_times": "estimated",
  "summary": {"days": 2, "total_budget_lkr": 60000.0, "total_cost_lkr": 31337.2, "total_km": 76.372,
              "total_travel_time_min": 185.0, "stops": 3, "places_requested": 3, "places_unscheduled": 0},
  "days": [
    {
      "day": 1, "start_time": "08:00:00", "end_time": "13:55:00",
      "entries": [
        {"type": "visit", "destination_id": "D02", "name": "Temple of the Sacred Tooth Relic, Kandy",
         "category": "religious", "arrival_time": "08:03:00", "wait_min": 0.0, "visit_start": "08:03:00",
         "departure_time": "09:33:00", "travel_time_min": 3.0, "travel_km": 1.173, "transport_mode": "car",
         "evening_drive": false, "travel_cost_lkr": 117.3, "entry_cost_lkr": 2000.0, "cost_lkr": 2117.3,
         "score": 0.92},
        {"type": "visit", "destination_id": "D05", "name": "Gregory Lake, Nuwara Eliya",
         "category": "nature", "arrival_time": "11:40:00", "wait_min": 0.0, "visit_start": "11:40:00",
         "departure_time": "13:10:00", "travel_time_min": 127.0, "travel_km": 52.507, "transport_mode": "car",
         "evening_drive": false, "travel_cost_lkr": 5250.7, "entry_cost_lkr": 200.0, "cost_lkr": 5450.7,
         "score": 0.75},
        {"type": "lunch", "start_time": "13:10:00", "end_time": "13:55:00", "wait_min": 0.0, "cost_lkr": 1500.0}
      ],
      "stops": 2, "travel_time_min": 130.0, "travel_km": 53.68, "cost_lkr": 17068.0,
      "cost_breakdown": {"accommodation": 5000.0, "transport": 5368.0, "food": 4000.0,
                         "activities": 2200.0, "other": 500.0},
      "allocated_lkr": 29411.43, "overrun_lkr": 0.0, "over_budget": false
    },
    {
      "day": 2, "start_time": "08:00:00", "end_time": "13:40:00",
      "entries": ["... Horton Plains 08:55-12:55, then lunch 12:55-13:40 ..."],
      "stops": 1, "travel_time_min": 55.0, "travel_km": 22.692, "cost_lkr": 14269.2,
      "cost_breakdown": {"accommodation": 0.0, "transport": 2269.2, "food": 4000.0,
                         "activities": 7500.0, "other": 500.0},
      "allocated_lkr": 24588.57, "overrun_lkr": 0.0, "over_budget": false
    }
  ],
  "budget": {
    "total_budget_lkr": 60000.0, "planned_total_lkr": 31337.2,
    "breakdown": {"accommodation": 5000.0, "transport": 7637.2, "food": 8000.0,
                  "activities": 9700.0, "other": 1000.0},
    "daily_allocation": [
      {"day": 1, "allocated_lkr": 29411.43, "planned_lkr": 17068.0, "overrun_lkr": 0.0, "over_budget": false},
      {"day": 2, "allocated_lkr": 24588.57, "planned_lkr": 14269.2, "overrun_lkr": 0.0, "over_budget": false}
    ],
    "reserve_lkr": 6000.0, "allocated_plus_reserve_lkr": 60000.0, "split_method": "proportional",
    "overrun_lkr": 0.0, "uses_reserve": false
  },
  "status": {"over_budget": false, "days_over_budget": [], "uses_reserve": false, "overrun_lkr": 0.0,
             "opening_hour_conflicts": [], "unscheduled": [], "search_time_capped": false},
  "objective": {"total": 18.883,
                "terms": {"score": 25.1, "travel_time": -3.0833, "spend": -3.1337, "wait": -0.0,
                          "unscheduled": -0.0, "overrun": -0.0, "coverage": -0.0, "conflict": -0.0},
                "start_total": 18.883},
  "run": {"method": "joint", "profile": "realistic", "weights": "default", "seed": 42,
          "time_limit_s": 10.0, "runtime_s": 0.4},
  "warnings": [
    "The joint search found no plan scoring higher than the sequential plan, so this is the sequential plan.",
    "Travel times and distances are offline estimates (straight-line distance x 1.3 at APPROX road speeds), not real road data.",
    "Transport fares, food, accommodation and other living costs are APPROX estimates (src/config.py), not quoted prices."
  ]
}
```

What the fields mean:

- `days[].entries` has visits and lunch in time order. Lunch is its own entry (`"type": "lunch"`).
  `travel_*` on a visit is the leg from the previous place: the start point on day 1, otherwise
  where the traveller ended the day before. `evening_drive: true` means that leg was driven the
  evening before, so the traveller is already there when the day starts.
- `budget.daily_allocation` + `budget.reserve_lkr` = `budget.total_budget_lkr`, always. The reserve
  is 10 % (APPROX), and `allocated_plus_reserve_lkr` shows the sum. The default `proportional` split gives each day a share
  matching its planned cost, so either every day is over its allocation or none is. A day "over
  budget" while the trip is not means the plan only fits by using the reserve.
- `status` flags are computed from the plan: `opening_hour_conflicts` is an independent re-check
  of every visit (always empty for these planners). `unscheduled` gives the scheduler's or the
  search's real reason for each place left out.
- `objective.start_total` is the sequential plan's score (joint), or the edited plan's score
  (/reoptimize). `objective.total >= start_total` always.

## POST /reoptimize

The user's edited plan: `day_orders` (ids per day, in order), plus optional `add` and `remove`.
The joint local search (same moves, same objective) starts from **that** plan. It runs one
restart only, because random restarts would throw the user's order away. A stop in `remove` is
taken out of the trip and never put back. A place in `destinations` that is not in the plan
may be inserted by the search. A stop the user added may be dropped if the plan scores higher
without it, and a warning then says so.

```json
{
  "trip": {"num_days": 2, "total_budget_lkr": 60000, "start_lat": 7.2906, "start_lng": 80.6337},
  "destinations": ["... the same Component 1 records ..."],
  "day_orders": [["D05", "D02"], []],
  "add": [{"destination_id": "D06", "day": 2, "position": 1}],
  "remove": [],
  "options": {"weights": "default", "seed": 42, "time_limit_s": 10}
}
```

The response has the same shape as /itinerary, with `run.method = "joint (from your plan)"`.
It is guaranteed to score at least as well as the (repaired) edited plan, **not** as well as a
fresh /itinerary. In the smoke test, reversing day 1 of a 15-place joint plan (score 28.12)
made it infeasible, and reoptimizing it reached only 19.04: one restart from a poor start can
get stuck. Compare `objective.total` with the earlier plan's before replacing it.
If the edited plan breaks a rule as given (a place closed on arrival, the day runs out), the
greedy scheduler keeps the user's order but moves stops that do not fit to later days. The
first warning then lists what moved, e.g. `"... the search started from the closest feasible
plan in your order (D06 day 1 -> day 2)."`

## POST /validate

Checks a plan without changing it. The `days` of an /itinerary response can be posted back
unchanged (extra fields are ignored). Each entry needs only:

- visit: `{"type": "visit", "destination_id", "arrival_time", "departure_time", "wait_min" (default 0)}`
- lunch: `{"type": "lunch", "start_time", "end_time"}`

```json
{
  "trip": {"num_days": 1, "total_budget_lkr": 40000, "start_lat": 7.2906, "start_lng": 80.6337},
  "destinations": ["... Component 1 records for D02 and D04 ..."],
  "days": [{"day": 1, "entries": [
    {"type": "visit", "destination_id": "D02", "arrival_time": "08:10", "departure_time": "09:40"},
    {"type": "visit", "destination_id": "D04", "arrival_time": "09:50", "departure_time": "10:50"}]}],
  "options": {"profile": "realistic"}
}
```

Response fields: `valid` (no opening-hour or timing conflicts, and the trip fits the total
budget), `opening_hour_conflicts`, `timing_conflicts` (an arrival the travel time makes
impossible, overlaps with lunch, outside the day window), `budget` (same shape as above),
`days_over_budget`, `over_budget`, `travel_times`, `warnings`. For the request above,
`timing_conflicts` contains `"day 1, D04: arrives 09:50, but the ... min trip there cannot arrive
before ..."`. Costs are recomputed with the optimizer's own rules. Any costs sent with the plan
are ignored.

## Errors

Every error has the same shape. 422 = bad input. 500 = unexpected server error: the message
is generic, and the stack trace goes only to the server log, never to the client.

```json
{"detail": [{"field": "trip", "message": "day_end must be after day_start"}]}
{"detail": [{"field": "day_orders[0][1]", "message": "unknown destination 'D99' (not in destinations)"}]}
{"detail": [{"field": "trip.total_budget_lkr",
             "message": "5,000 LKR is below the 11,000 LKR that food, accommodation and other daily costs alone need for 2 days (APPROX values in src/config.py)"}]}
```

| Case | Example `field` |
|------|-----------------|
| unknown destination id (reoptimize, validate) | `day_orders[0][1]`, `days[0].entries[2].destination_id`, `remove[0]`, `add[0].destination_id` |
| duplicate id, reserved `START` id | `destinations[2].id` |
| bad times: closing before opening, `day_end <= day_start`, `"25:00"`, departure before arrival | `destinations[0]`, `trip`, `trip.day_end`, `days[0].entries[1].departure_time` |
| impossible budget: `<= 0`, or below the unavoidable living costs | `trip.total_budget_lkr` |
| place outside Sri Lanka, score not in 0..1, missing field | `destinations[0]`, `destinations[0].score`, `destinations[0].name` |
| unknown option value, time limit out of range | `options.method`, `options.time_limit_s` |
| wrong number of days in a plan | `day_orders`, `days` |

"Below the living costs" applies under the realistic profile only: food + other per day, plus
accommodation per night (`num_days - 1` nights), all APPROX. A budget above that but too small
for the chosen places is **not** an error. The plan is returned with real overrun flags and warnings.

## Component 4 contract (stored itinerary)

Component 4 should store the **whole** /itinerary (or /reoptimize) response as one JSON
document, together with the request that produced it:

```json
{
  "itinerary_id": "<Component 4's own id>",
  "created_at": "<ISO 8601>",
  "request": { "trip": {}, "destinations": [], "options": {} },
  "response": { "travel_times": "...", "summary": {}, "days": [], "budget": {}, "status": {},
                "objective": {}, "run": {}, "warnings": [] }
}
```

Why the request too: /reoptimize and /validate need `trip` and `destinations`, and `run`
(method, profile, weights, seed) is what reproduces an uncapped plan.

Use of the stored document:

- **Show it:** `response.summary`, `response.days`, `response.budget`, `response.status`,
  `response.warnings`.
- **Re-check it later** (e.g. after the user edits times): `POST /validate` with
  `request.trip`, `request.destinations` and `response.days`.
- **Edit and improve it:** `POST /reoptimize` with `day_orders` taken from the visit
  `destination_id`s of each day in `response.days`.

Stable keys: every field listed in this document. Times are `"HH:MM:SS"` strings, money is
LKR, distances are km, durations are minutes. New fields may be added later. Existing fields
will not be renamed.

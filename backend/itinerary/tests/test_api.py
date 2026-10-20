"""Tests for the HTTP API (app/main.py, app/service.py, app/schemas.py) with FastAPI's TestClient.

Inputs are the 15 MOCK places of data/destinations.json. Google is always switched off
here (no network in tests); travel times are the offline haversine estimate.
"""

import json
from datetime import time

import pytest
from fastapi.testclient import TestClient

from app import service
from app.main import app
from src import config

KANDY = {"start_lat": 7.2906, "start_lng": 80.6337}
COLOMBO = {"start_lat": 6.9344, "start_lng": 79.8428}
V5_FLAGS = ("USE_TRANSPORT_MODES", "USE_REGION_SPEEDS", "USE_LUNCH_BREAK", "USE_EVENING_DRIVE",
            "USE_DAILY_COSTS")
REAL_KEY_CHECK = service.google_key_available  # the client fixture replaces it with "no key"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """A client with Google off and a private matrix cache."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(service, "CACHE_DIR", tmp_path_factory.mktemp("cache"))
        mp.setattr(service, "google_key_available", lambda: False)
        yield TestClient(app)


@pytest.fixture(scope="module")
def places() -> list[dict]:
    """The MOCK places as Component 1 would send them (JSON records)."""
    return json.loads(config.DESTINATIONS_FILE.read_text(encoding="utf-8"))


def pick(places, *ids) -> list[dict]:
    return [p for p in places if p["id"] in ids]


def body(places, num_days=2, budget=80_000, start=KANDY, **options) -> dict:
    return {"trip": {"num_days": num_days, "total_budget_lkr": budget, **start},
            "destinations": places, "options": options}


HILLS = ("D02", "D04", "D05", "D06", "D13")  # hill country (scenarios.HILL_COUNTRY)


@pytest.fixture(scope="module")
def seq_basic(client, places):
    r = client.post("/itinerary", json=body(pick(places, *HILLS), method="sequential", profile="basic"))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def seq_realistic(client, places):
    r = client.post("/itinerary", json=body(pick(places, *HILLS), method="sequential"))
    assert r.status_code == 200, r.text
    return r.json()


def visits(response) -> list[dict]:
    return [e for d in response["days"] for e in d["entries"] if e["type"] == "visit"]


# ---------- 1. Endpoints ----------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "travel_times": "estimated", "default_profile": "realistic",
                        "profiles": ["basic", "realistic"]}


def test_itinerary_returns_one_card_per_day(seq_basic):
    assert [d["day"] for d in seq_basic["days"]] == [1, 2]
    assert seq_basic["summary"]["stops"] == len(visits(seq_basic)) > 0


# ---------- 2. Response shape ----------

def test_summary_adds_up_the_day_cards(seq_realistic):
    s, days = seq_realistic["summary"], seq_realistic["days"]
    assert s["days"] == 2 and s["places_requested"] == len(HILLS)
    assert s["stops"] + s["places_unscheduled"] == len(HILLS)
    assert s["total_km"] == pytest.approx(sum(d["travel_km"] for d in days), abs=0.01)
    assert s["total_cost_lkr"] == pytest.approx(sum(d["cost_lkr"] for d in days), abs=0.01)
    assert s["total_travel_time_min"] == pytest.approx(sum(d["travel_time_min"] for d in days))


def test_day_card_cost_is_the_sum_of_its_categories(seq_realistic):
    for day in seq_realistic["days"]:
        assert set(day["cost_breakdown"]) == {"accommodation", "transport", "food", "activities", "other"}
        assert sum(day["cost_breakdown"].values()) == pytest.approx(day["cost_lkr"], abs=0.01)
        stops = [e for e in day["entries"] if e["type"] == "visit"]
        assert day["cost_breakdown"]["transport"] == pytest.approx(sum(e["travel_cost_lkr"] for e in stops))
        assert day["cost_breakdown"]["activities"] == pytest.approx(sum(e["entry_cost_lkr"] for e in stops))


def test_entries_are_in_time_order(seq_realistic):
    for day in seq_realistic["days"]:
        times = []
        for e in day["entries"]:
            times += [e["arrival_time"], e["departure_time"]] if e["type"] == "visit" else [e["start_time"],
                                                                                              e["end_time"]]
        assert times == sorted(times)


def test_visit_fields(seq_realistic, places):
    categories = {p["id"]: p["category"] for p in places}
    for v in visits(seq_realistic):
        assert v["category"] == categories[v["destination_id"]]
        assert v["cost_lkr"] == pytest.approx(v["travel_cost_lkr"] + v["entry_cost_lkr"])
        assert v["transport_mode"] in {"car", "bus", "walk"} or "+" in v["transport_mode"]
        assert v["travel_km"] >= 0


def test_budget_breakdown_has_the_five_categories(seq_realistic):
    b = seq_realistic["budget"]
    assert list(b["breakdown"]) == ["accommodation", "transport", "food", "activities", "other"]
    assert sum(b["breakdown"].values()) == pytest.approx(b["planned_total_lkr"], abs=0.01)


def test_status_reflects_the_budget_report(client, places):
    """A budget that only just covers the living costs: the plan really overruns, and says so."""
    r = client.post("/itinerary", json=body(pick(places, *HILLS), budget=20_000, method="sequential"))
    j = r.json()
    assert r.status_code == 200
    assert j["status"]["over_budget"] == (j["budget"]["planned_total_lkr"] > 20_000)
    assert j["status"]["days_over_budget"] == [d["day"] for d in j["days"] if d["over_budget"]]
    assert j["status"]["days_over_budget"]  # 20,000 LKR is too little for any real day here
    assert any("over its allocation" in w for w in j["warnings"])


def test_unscheduled_places_come_with_reasons(client, places):
    r = client.post("/itinerary", json=body(places, num_days=1, method="sequential"))  # 15 places, 1 day
    j = r.json()
    assert j["status"]["unscheduled"] and all(u["reason"] for u in j["status"]["unscheduled"])
    assert j["summary"]["places_unscheduled"] == len(j["status"]["unscheduled"])


# ---------- 3. Profiles ----------

def test_realistic_profile_is_the_default(seq_realistic):
    assert seq_realistic["run"]["profile"] == "realistic"


def test_realistic_profile_turns_on_the_v5_rules(seq_basic, seq_realistic):
    def lunches(r):
        return [e for d in r["days"] for e in d["entries"] if e["type"] == "lunch"]

    assert not lunches(seq_basic) and lunches(seq_realistic)
    basic, real = seq_basic["budget"]["breakdown"], seq_realistic["budget"]["breakdown"]
    assert basic["food"] == basic["accommodation"] == basic["other"] == 0
    assert real["accommodation"] == config.ACCOMMODATION_PER_NIGHT_LKR  # 2 days = 1 night
    assert real["other"] == 2 * config.OTHER_PER_DAY_LKR


def test_requests_never_change_the_config_defaults(client, places):
    before = {flag: getattr(config, flag) for flag in V5_FLAGS}
    client.post("/itinerary", json=body(pick(places, *HILLS), method="sequential"))
    client.post("/itinerary", json=body(pick(places, *HILLS), budget=1))  # rejected inside the profile
    assert {flag: getattr(config, flag) for flag in V5_FLAGS} == before
    assert not any(before.values())


def test_per_day_start_times_are_used(client, places):
    trip = {"num_days": 2, "total_budget_lkr": 80_000, **KANDY, "day_starts": ["08:00", "06:00"]}
    r = client.post("/itinerary", json={"trip": trip, "destinations": pick(places, *HILLS),
                                        "options": {"method": "sequential"}})
    assert [d["start_time"] for d in r.json()["days"]] == ["08:00:00", "06:00:00"]


def test_service_profile_flags_restore_after_an_error():
    with pytest.raises(RuntimeError):
        with service.profile_flags("realistic"):
            assert config.USE_LUNCH_BREAK
            raise RuntimeError
    assert not config.USE_LUNCH_BREAK


# ---------- 4. Daily allocation + reserve = trip total ----------

@pytest.mark.parametrize("budget, num_days, profile", [
    (80_000, 2, "realistic"), (77_777.77, 3, "realistic"), (100_001, 5, "basic"), (33_333.33, 1, "basic"),
    (20_000, 2, "realistic"),  # over budget: the allocation still adds up
])
def test_allocations_plus_reserve_equal_the_total(client, places, budget, num_days, profile):
    r = client.post("/itinerary", json=body(pick(places, *HILLS), num_days=num_days, budget=budget,
                                            method="sequential", profile=profile))
    b = r.json()["budget"]
    allocated = sum(d["allocated_lkr"] for d in b["daily_allocation"])
    assert [d["day"] for d in b["daily_allocation"]] == list(range(1, num_days + 1))
    assert b["reserve_lkr"] == pytest.approx(budget * config.BUDGET_RESERVE_PCT, abs=0.005)
    assert round(allocated + b["reserve_lkr"], 2) == round(budget, 2) == b["allocated_plus_reserve_lkr"]
    assert b["total_budget_lkr"] == budget


def test_day_cards_carry_the_same_allocation(seq_realistic):
    by_day = {d["day"]: d for d in seq_realistic["budget"]["daily_allocation"]}
    for card in seq_realistic["days"]:
        assert card["allocated_lkr"] == by_day[card["day"]]["allocated_lkr"]
        assert card["cost_lkr"] == by_day[card["day"]]["planned_lkr"]


# ---------- 5. Method, weights, seed, time limit ----------

def test_joint_is_the_default_method(client, places):
    j = client.post("/itinerary", json=body(pick(places, *HILLS))).json()
    assert j["run"]["method"] == "joint" and j["run"]["seed"] == config.JOINT_SEED
    assert j["run"]["time_limit_s"] == config.API_JOINT_TIME_LIMIT_S
    assert j["objective"]["total"] >= j["objective"]["start_total"]  # never below sequential


def test_same_seed_same_plan(client, places):
    def plan(seed):
        j = client.post("/itinerary", json=body(pick(places, *HILLS), seed=seed)).json()
        assert not j["status"]["search_time_capped"]  # a capped run need not repeat
        return [[e.get("destination_id") for e in d["entries"]] for d in j["days"]], j["objective"]["total"]

    assert plan(7) == plan(7)


@pytest.mark.parametrize("preset", ["default", "budget", "time"])
def test_weight_presets_score_with_their_own_weights(client, places, preset):
    j = client.post("/itinerary", json=body(pick(places, *HILLS), method="sequential", weights=preset)).json()
    weights = config.EVALUATION_WEIGHT_SETTINGS[preset]
    assert j["run"]["weights"] == preset
    assert j["objective"]["terms"]["spend"] == pytest.approx(
        -weights["spend"] * j["budget"]["planned_total_lkr"] / config.OBJECTIVE_MONEY_SCALE_LKR, abs=1e-3)


def test_time_cap_flags_and_returns_a_plan(client, places):
    j = client.post("/itinerary", json=body(places, num_days=4, budget=200_000, time_limit_s=0.001)).json()
    assert j["status"]["search_time_capped"] is True
    assert any("time limit" in w for w in j["warnings"])
    assert j["summary"]["stops"] > 0 and not j["status"]["opening_hour_conflicts"]


def test_uncapped_run_is_not_flagged(client, places):
    j = client.post("/itinerary", json=body(pick(places, *HILLS))).json()
    assert j["status"]["search_time_capped"] is False
    assert not any("time limit" in w for w in j["warnings"])


def test_sequential_has_no_seed_or_time_limit(seq_basic):
    assert seq_basic["run"]["seed"] is None and seq_basic["run"]["time_limit_s"] is None
    assert seq_basic["objective"]["start_total"] is None and seq_basic["status"]["search_time_capped"] is False


@pytest.mark.parametrize("options, field", [
    ({"method": "exact"}, "options.method"), ({"weights": "cheap"}, "options.weights"),
    ({"profile": "fancy"}, "options.profile"), ({"time_limit_s": 0}, "options.time_limit_s"),
    ({"time_limit_s": config.API_MAX_TIME_LIMIT_S + 1}, "options.time_limit_s"),
])
def test_bad_options_are_422(client, places, options, field):
    r = client.post("/itinerary", json=body(pick(places, *HILLS), **options))
    assert r.status_code == 422 and r.json()["detail"][0]["field"] == field


# ---------- 6. Input errors: clear 422 messages, never a stack trace ----------

def error(r) -> tuple[str, str]:
    """(field, message) of the first error; checks the error shape on the way."""
    assert set(r.json()) == {"detail"}
    first = r.json()["detail"][0]
    assert set(first) == {"field", "message"}
    return first["field"], first["message"]


def with_place(places, **change) -> list[dict]:
    return [{**places[0], **change}, *places[1:3]]


@pytest.mark.parametrize("trip_change, field, words", [
    ({"day_start": "18:00", "day_end": "08:00"}, "trip", "day_end must be after day_start"),
    ({"day_end": "25:00"}, "trip.day_end", "time"),
    ({"day_starts": ["08:00"]}, "trip", "day_starts needs one time per day"),
    ({"num_days": 0}, "trip.num_days", "greater than or equal to 1"),
    ({"start_lat": 51.5, "start_lng": -0.12}, "trip", "inside Sri Lanka"),
])
def test_bad_trip_is_422(client, places, trip_change, field, words):
    b = body(pick(places, *HILLS))
    b["trip"].update(trip_change)
    r = client.post("/itinerary", json=b)
    assert r.status_code == 422
    got_field, message = error(r)
    assert got_field == field and words in message


@pytest.mark.parametrize("change, field, words", [
    ({"opening_time": "18:00", "closing_time": "07:00"}, "destinations[0]", "closing_time must be after opening_time"),
    ({"opening_time": "7am"}, "destinations[0].opening_time", "time"),
    ({"lat": 13.08, "lng": 80.27}, "destinations[0]", "outside Sri Lanka"),
    ({"cost_lkr": -5}, "destinations[0]", "cost_lkr must be >= 0"),
    ({"score": 1.5}, "destinations[0].score", "less than or equal to 1"),
    ({"id": "START"}, "destinations[0].id", "reserved"),
])
def test_bad_destination_is_422(client, places, change, field, words):
    r = client.post("/itinerary", json=body(with_place(places, **change)))
    assert r.status_code == 422
    got_field, message = error(r)
    assert got_field == field and words in message


def test_duplicate_destination_is_422(client, places):
    r = client.post("/itinerary", json=body([places[0], places[1], places[0]]))
    assert r.status_code == 422 and error(r) == ("destinations[2].id", "duplicate destination id 'D01'")


def test_missing_field_and_empty_list_are_422(client, places):
    record = {k: v for k, v in places[0].items() if k != "name"}
    assert error(client.post("/itinerary", json=body([record])))[0] == "destinations[0].name"
    assert error(client.post("/itinerary", json=body([])))[0] == "destinations"


@pytest.mark.parametrize("budget, profile, words", [
    (0, "basic", "must be greater than 0"),
    (-100, "basic", "greater than or equal to 0"),
    (5_000, "realistic", "food, accommodation and other daily costs alone"),  # 2 days need 11,000 LKR
])
def test_impossible_budget_is_422(client, places, budget, profile, words):
    r = client.post("/itinerary", json=body(pick(places, *HILLS), budget=budget, profile=profile))
    assert r.status_code == 422
    field, message = error(r)
    assert field.startswith("trip") and words in message


def test_budget_just_above_the_living_costs_is_planned(client, places):
    floor = service.minimum_trip_cost  # needs the realistic flags on
    with service.profile_flags("realistic"):
        minimum = floor(2)
    assert minimum == 2 * (config.FOOD_PER_DAY_LKR + config.OTHER_PER_DAY_LKR) + config.ACCOMMODATION_PER_NIGHT_LKR
    r = client.post("/itinerary", json=body(pick(places, *HILLS), budget=minimum, method="sequential"))
    assert r.status_code == 200


def test_malformed_json_is_422(client):
    r = client.post("/itinerary", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and error(r) == (None, "request body is not valid JSON")


def test_unexpected_error_is_500_without_a_trace(places, monkeypatch):
    def boom(_req):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(service, "plan_itinerary", boom)
    r = TestClient(app, raise_server_exceptions=False).post("/itinerary", json=body(pick(places, *HILLS)))
    assert r.status_code == 500
    assert r.json() == {"detail": [{"field": None, "message": "internal error: the request could not be planned"}]}
    assert "Traceback" not in r.text and "secret" not in r.text


# ---------- 7. Google key: only from the server's .env, offline estimate otherwise ----------

def test_key_is_read_from_dotenv_only(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setenv(config.GOOGLE_API_KEY_ENV, "from-the-environment")
    assert REAL_KEY_CHECK() is False  # no .env file: the environment does not count
    (tmp_path / ".env").write_text(f"{config.GOOGLE_API_KEY_ENV}=\n", encoding="utf-8")
    assert REAL_KEY_CHECK() is False  # empty key
    (tmp_path / ".env").write_text(f"{config.GOOGLE_API_KEY_ENV}=test-key\n", encoding="utf-8")
    assert REAL_KEY_CHECK() is True


def test_no_key_means_estimated_travel_times(seq_basic):
    assert seq_basic["travel_times"] == "estimated"
    assert any("offline estimates" in w for w in seq_basic["warnings"])


def test_google_failure_falls_back_to_the_estimate(monkeypatch):
    from src.distance import GoogleMatrixError

    monkeypatch.setattr(service, "google_key_available", lambda: True)
    calls = []

    def run(use_google):
        calls.append(use_google)
        if use_google:
            raise GoogleMatrixError("REQUEST_DENIED: key=abc123")
        return "offline plan"

    result, warnings = service.with_travel_source(run)
    assert result == "offline plan" and calls == [True, False]
    assert "GoogleMatrixError" in warnings[0] and "abc123" not in warnings[0]


def test_travel_source_labels():
    import networkx as nx

    def graph(*sources):
        g = nx.DiGraph()
        for i, s in enumerate(sources):
            g.add_edge(i, i + 1, source=s)
        return g

    assert service.travel_source(graph("haversine", "haversine")) == "estimated"
    assert service.travel_source(graph("google", "google")) == "google"
    assert service.travel_source(graph("google", "haversine")) == "mixed"  # Google had no route for a leg


# ---------- 8a. The response numbers are the optimizer's own output ----------

def same_numbers(response, itinerary, score):
    """Every number the response takes from the optimizer, against the optimizer's own result."""
    assert response["objective"]["total"] == score.total
    assert response["summary"]["total_cost_lkr"] == itinerary.total_cost_lkr
    assert response["budget"]["breakdown"] == itinerary.cost_breakdown
    assert response["status"]["over_budget"] == itinerary.over_budget
    assert [(u["destination_id"], u["reason"]) for u in response["status"]["unscheduled"]] == \
           [(u.destination_id, u.reason) for u in itinerary.unscheduled]
    for card, day in zip(response["days"], itinerary.days, strict=True):
        assert card["cost_lkr"] == day.daily_cost_lkr and card["allocated_lkr"] == day.daily_budget_lkr
        assert card["over_budget"] == day.over_budget
        got = [e for e in card["entries"] if e["type"] == "visit"]
        assert [(v["destination_id"], v["arrival_time"], v["departure_time"], v["wait_min"], v["travel_time_min"],
                 v["travel_cost_lkr"], v["entry_cost_lkr"], v["evening_drive"]) for v in got] == \
               [(s.destination_id, s.arrival_time.isoformat(), s.departure_time.isoformat(), s.wait_min,
                 s.travel_time_min, s.travel_cost_lkr, s.entry_cost_lkr, s.evening_drive) for s in day.stops]
        lunch = [e for e in card["entries"] if e["type"] == "lunch"]
        assert [(e["start_time"], e["cost_lkr"]) for e in lunch] == \
               ([(day.lunch.start_time.isoformat(), day.lunch.food_cost_lkr)] if day.lunch else [])


@pytest.mark.parametrize("profile, weights", [("realistic", "default"), ("basic", "budget"), ("realistic", "time")])
def test_joint_response_equals_optimize_joint(client, places, tmp_path, profile, weights):
    from src.joint import optimize_joint
    from src.models import Destination, TripRequest

    b = body(places, num_days=4, budget=150_000, start=COLOMBO, profile=profile, weights=weights, seed=3,
             time_limit_s=config.API_MAX_TIME_LIMIT_S)
    j = client.post("/itinerary", json=b).json()
    assert not j["status"]["search_time_capped"]
    with service.profile_flags(profile):
        own = optimize_joint([Destination(**p) for p in places], TripRequest(**b["trip"]),
                             weights=config.EVALUATION_WEIGHT_SETTINGS[weights], seed=3, cache_dir=tmp_path)
    same_numbers(j, own.itinerary, own.score)


def test_sequential_response_equals_run_sequential(client, places, tmp_path):
    from src.models import Destination, TripRequest
    from src.objective import score_plan
    from src.pipeline import run_sequential

    b = body(places, num_days=3, budget=90_000, start=COLOMBO, method="sequential")
    j = client.post("/itinerary", json=b).json()
    with service.profile_flags("realistic"):
        own = run_sequential([Destination(**p) for p in places], TripRequest(**b["trip"]), cache_dir=tmp_path,
                             mode_weights=config.OBJECTIVE_WEIGHTS)
        score = score_plan(own.itinerary.days, own.itinerary.unscheduled, own.budget_report, graph=own.graph)
    same_numbers(j, own.itinerary, score)


def test_leg_km_follows_the_scheduled_path(client, places):
    """km comes from re-walking each leg; that walk must give the scheduler's own travel time."""
    import math
    from src.models import Destination, TripRequest
    from src.pipeline import run_sequential
    from src.routing import dijkstra

    b = body(places, num_days=4, budget=150_000, start=COLOMBO, method="sequential")
    j = client.post("/itinerary", json=b).json()
    with service.profile_flags("realistic"):
        graph = run_sequential([Destination(**p) for p in places], TripRequest(**b["trip"]),
                               cache_dir=service.CACHE_DIR, mode_weights=config.OBJECTIVE_WEIGHTS).graph
    location = config.START_NODE_ID
    for v in visits(j):
        path = dijkstra(graph, location, v["destination_id"], config.EDGE_WEIGHTS).path
        legs = list(zip(path, path[1:]))
        assert math.ceil(sum(graph.edges[e]["duration_min"] for e in legs)) == v["travel_time_min"]
        assert v["travel_km"] == pytest.approx(sum(graph.edges[e]["distance_km"] for e in legs), abs=1e-3)
        location = v["destination_id"]


# ---------- 8b. POST /reoptimize ----------

@pytest.fixture(scope="module")
def joint_plan(client, places):
    """A joint plan of all 15 places to edit."""
    b = body(places, num_days=4, budget=150_000, start=COLOMBO)
    j = client.post("/itinerary", json=b).json()
    assert not j["status"]["search_time_capped"]
    return b, j


def orders_of(response) -> list[list[str]]:
    return [[e["destination_id"] for e in d["entries"] if e["type"] == "visit"] for d in response["days"]]


def reopt(b, orders, **extra) -> dict:
    return {"trip": b["trip"], "destinations": b["destinations"], "day_orders": orders, **extra}


def test_reoptimize_starts_from_the_users_plan(client, joint_plan):
    b, j = joint_plan
    r = client.post("/reoptimize", json=reopt(b, orders_of(j)))
    assert r.status_code == 200
    got = r.json()
    assert got["objective"]["start_total"] == j["objective"]["total"]  # the start is exactly that plan
    assert got["objective"]["total"] >= got["objective"]["start_total"]
    assert got["run"]["method"] == "joint (from your plan)"


def test_reoptimize_never_puts_a_removed_stop_back(client, joint_plan):
    b, j = joint_plan
    removed = orders_of(j)[0][0]
    got = client.post("/reoptimize", json=reopt(b, orders_of(j), remove=[removed])).json()
    assert removed not in [v["destination_id"] for v in visits(got)]
    assert removed not in [u["destination_id"] for u in got["status"]["unscheduled"]]
    assert got["summary"]["places_requested"] == len(b["destinations"]) - 1


def test_reoptimize_with_an_added_stop(client, joint_plan):
    b, j = joint_plan
    left_out = [u["destination_id"] for u in j["status"]["unscheduled"]]
    orders = orders_of(j)
    if not left_out:  # make room: take one stop out of the plan, then add it back
        left_out = [orders[-1].pop()]
    add = {"destination_id": left_out[0], "day": 1, "position": 1}
    got = client.post("/reoptimize", json=reopt(b, orders, add=[add])).json()
    in_plan = left_out[0] in [v["destination_id"] for v in visits(got)]
    assert in_plan or any(left_out[0] in w and "which you added" in w for w in got["warnings"])


def test_reoptimize_repairs_an_infeasible_order(client, places):
    """Horton Plains (4 h visit, closes 16:00) put last on a long day: does not fit as given."""
    b = body(pick(places, *HILLS), num_days=2, budget=100_000)
    orders = [["D02", "D05", "D13", "D04", "D06"], []]
    got = client.post("/reoptimize", json=reopt(b, orders))
    assert got.status_code == 200
    j = got.json()
    assert "closest feasible plan" in j["warnings"][0]
    assert not j["status"]["opening_hour_conflicts"]


@pytest.mark.parametrize("change, field", [
    ({"day_orders": [["D02", "XX"], []]}, "day_orders[0][1]"),
    ({"day_orders": [["D02"], ["D02"]]}, "day_orders[1][0]"),
    ({"day_orders": [["D02"]]}, "day_orders"),
    ({"remove": ["XX"]}, "remove[0]"),
    ({"add": [{"destination_id": "XX", "day": 1}]}, "add[0].destination_id"),
    ({"add": [{"destination_id": "D02", "day": 1}]}, "add[0].destination_id"),  # already in the plan
    ({"add": [{"destination_id": "D04", "day": 3}]}, "add[0].day"),
    ({"add": [{"destination_id": "D04", "day": 1, "position": 9}]}, "add[0].position"),
])
def test_reoptimize_bad_edits_are_422(client, places, change, field):
    b = body(pick(places, *HILLS), num_days=2)
    r = client.post("/reoptimize", json={**reopt(b, [["D02"], ["D05"]]), **change})
    assert r.status_code == 422 and error(r)[0] == field


# ---------- 8c. POST /validate ----------

def as_validate(b, response) -> dict:
    """The days of an /itinerary response, posted back as they are (extra fields are ignored)."""
    return {"trip": b["trip"], "destinations": b["destinations"], "days": response["days"],
            "options": {k: v for k, v in b["options"].items() if k in ("profile", "weights")}}


def test_validate_accepts_the_optimizers_own_plan(client, joint_plan):
    b, j = joint_plan
    got = client.post("/validate", json=as_validate(b, j)).json()
    assert got["opening_hour_conflicts"] == [] and got["timing_conflicts"] == []
    assert got["valid"] == (not j["status"]["over_budget"])
    assert got["budget"]["planned_total_lkr"] == j["budget"]["planned_total_lkr"]
    assert got["budget"]["daily_allocation"] == j["budget"]["daily_allocation"]


def test_validate_finds_an_opening_hour_conflict(client, joint_plan):
    b, j = joint_plan
    days = json.loads(json.dumps(j["days"]))
    stop = next(e for d in days for e in d["entries"] if e["type"] == "visit")
    stop["departure_time"] = "23:30:00"  # after every closing time in the mock data
    got = client.post("/validate", json={**as_validate(b, j), "days": days}).json()
    assert got["valid"] is False
    assert any(stop["destination_id"] in c and "after closing" in c for c in got["opening_hour_conflicts"])
    assert any("after the day ends" in c for c in got["timing_conflicts"])


def test_validate_finds_an_impossible_arrival(client, places):
    b = body(pick(places, "D02", "D04"), num_days=1)  # Kandy temple, then Ella: hours apart
    days = [{"day": 1, "entries": [
        {"type": "visit", "destination_id": "D02", "arrival_time": "08:10", "departure_time": "09:40"},
        {"type": "visit", "destination_id": "D04", "arrival_time": "09:50", "departure_time": "10:50"}]}]
    got = client.post("/validate", json={**b, "days": days}).json()
    assert not got["valid"] and any("D04" in c and "cannot arrive before" in c for c in got["timing_conflicts"])
    assert got["opening_hour_conflicts"] == []


def test_validate_reports_a_budget_overrun(client, joint_plan):
    b, j = joint_plan
    tight = {**as_validate(b, j), "trip": {**b["trip"], "total_budget_lkr": 30_000}}
    got = client.post("/validate", json=tight).json()
    assert got["over_budget"] and not got["valid"] and got["days_over_budget"]
    a = got["budget"]
    assert round(sum(d["allocated_lkr"] for d in a["daily_allocation"]) + a["reserve_lkr"], 2) == 30_000


@pytest.mark.parametrize("days, field", [
    ([{"day": 1, "entries": [{"type": "visit", "destination_id": "XX", "arrival_time": "09:00",
                              "departure_time": "10:00"}]}], "days[0].entries[0].destination_id"),
    ([{"day": 1, "entries": [{"type": "visit", "destination_id": "D02", "arrival_time": "10:00",
                              "departure_time": "09:00"}]}], "days[0].entries[0].departure_time"),
    ([{"day": 1, "entries": [{"type": "lunch", "start_time": "13:00", "end_time": "12:00"}]}],
     "days[0].entries[0].end_time"),
    ([{"day": 1, "entries": [{"type": "nap", "start_time": "13:00"}]}], "days[0].entries[0]"),
    ([{"day": 2, "entries": []}], "days"),
])
def test_validate_bad_plans_are_422(client, places, days, field):
    r = client.post("/validate", json={**body(pick(places, *HILLS), num_days=1), "days": days})
    assert r.status_code == 422 and error(r)[0] == field

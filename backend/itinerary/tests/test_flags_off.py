"""With every version 5 flag OFF, all four methods rebuild exactly the pre-version-5 plans.

The reference plans in tests/data/golden_plans.json were written before any version 5
code existed (see tests/golden_plans.py), so this compares new code with OLD output.
"""

import json

import pytest

from tests.golden_plans import GOLDEN_FILE, build_snapshot
from src import config

V5_FLAGS = ("USE_TRANSPORT_MODES", "USE_REGION_SPEEDS", "USE_LUNCH_BREAK", "USE_EVENING_DRIVE",
            "USE_DAILY_COSTS")


def test_every_new_flag_is_off_by_default():
    for flag in V5_FLAGS:
        assert getattr(config, flag, False) is False, flag


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    return build_snapshot(tmp_path_factory.mktemp("cache"))


def test_flags_off_reproduces_the_old_plans_exactly(rebuilt):
    golden = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    assert set(rebuilt) == set(golden)
    for key, old in golden.items():
        assert rebuilt[key] == old, key

"""Load destinations from JSON and validate every record."""

import json
from pathlib import Path

from pydantic import ValidationError

from src.models import Destination, in_sri_lanka


class DestinationValidationError(ValueError):
    """Raised when a destination record is invalid. The message names the record."""


def _label(index: int, record: dict) -> str:
    """Human-readable name for a record, used in error messages."""
    return f"record #{index} (id={record.get('id')!r}, name={record.get('name')!r})"


def _check_rules(dest: Destination) -> list[str]:
    """Return a list of business-rule problems (empty if the destination is valid)."""
    problems = []
    if not in_sri_lanka(dest.lat, dest.lng):
        problems.append(f"coordinates ({dest.lat}, {dest.lng}) are outside Sri Lanka")
    if dest.visit_duration_min <= 0:
        problems.append("visit_duration_min must be > 0")
    if dest.closing_time <= dest.opening_time:
        problems.append("closing_time must be after opening_time")
    if dest.cost_lkr < 0:
        problems.append("cost_lkr must be >= 0")
    return problems


def load_destinations(path: str | Path) -> list[Destination]:
    """Read destinations from a JSON list and validate them. Raises on the first bad record."""
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise DestinationValidationError("destinations file must contain a JSON list")

    destinations: list[Destination] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise DestinationValidationError(f"record #{index}: must be a JSON object")
        label = _label(index, record)

        # 1. Types and required fields (Pydantic)
        try:
            dest = Destination.model_validate(record)
        except ValidationError as e:
            raise DestinationValidationError(f"{label}: {e}") from e

        # 2. Business rules
        problems = _check_rules(dest)
        if problems:
            raise DestinationValidationError(f"{label}: " + "; ".join(problems))

        # 3. Unique ids
        if dest.id in seen_ids:
            raise DestinationValidationError(f"{label}: duplicate id {dest.id!r}")
        seen_ids.add(dest.id)

        destinations.append(dest)
    return destinations

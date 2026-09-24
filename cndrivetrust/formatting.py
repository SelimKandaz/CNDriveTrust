"""Stable human-readable formatting without discarding raw values."""

from __future__ import annotations

from typing import Any

NVME_DATA_UNIT_BYTES = 512_000


def raw_value(values: dict[str, Any], name: str) -> Any:
    item = values.get(name)
    return item.get("value") if isinstance(item, dict) else None


def field_status(values: dict[str, Any], name: str) -> str:
    item = values.get(name)
    return str(item.get("status") or "UNAVAILABLE") if isinstance(item, dict) else "UNAVAILABLE"


def number(values: dict[str, Any], name: str) -> int | float | None:
    value = raw_value(values, name)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def bytes_human(value: int | float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    amount = float(value)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while abs(amount) >= 1000 and index < len(units) - 1:
        amount /= 1000
        index += 1
    precision = 0 if index == 0 else (2 if abs(amount) < 10 else 1)
    return f"{amount:.{precision}f} {units[index]}"


def nvme_units_human(value: int | float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    return bytes_human(value * NVME_DATA_UNIT_BYTES)


def duration_hours(value: int | float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    hours = float(value)
    if hours < 24:
        return f"{hours:g} hour" + ("" if hours == 1 else "s")
    return f"{hours:g} hours ({hours / 24:.1f} days)"


def duration_minutes(value: int | float | None) -> str:
    if value is None:
        return "UNAVAILABLE"
    minutes = float(value)
    if minutes < 60:
        return f"{minutes:g} minute" + ("" if minutes == 1 else "s")
    return f"{minutes:g} minutes ({minutes / 60:.1f} hours)"


def rate_human(value: int | float | None) -> str:
    return "UNAVAILABLE" if value is None else f"{bytes_human(value)}/s"


def shown(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "UNAVAILABLE"
    return f"{value}{suffix}"

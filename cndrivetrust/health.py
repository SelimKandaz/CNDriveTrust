"""Conservative, explainable drive health and usage interpretation."""

from __future__ import annotations

from typing import Any

from .formatting import (
    bytes_human,
    duration_hours,
    duration_minutes,
    field_status,
    number,
    nvme_units_human,
    rate_human,
    raw_value,
)

SCHEMA_VERSION = "2.1"


def _dimension(state: str, explanation: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"state": state, "explanation": explanation, "evidence": evidence}


def _history_trust(values: dict[str, Any]) -> dict[str, Any]:
    wear = number(values, "percentage_used")
    vendor_wear = number(values, "vendor_media_wear_percent")
    average_erase = number(values, "nand_erase_cycles_average")
    maximum_erase = number(values, "nand_erase_cycles_maximum")
    written_units = number(values, "data_units_written")
    write_commands = number(values, "host_write_commands")
    hours = number(values, "power_on_hours")
    vendor_minutes = number(values, "vendor_workload_timer_minutes")
    observed = {
        "percentage_used": wear,
        "vendor_media_wear_percent": vendor_wear,
        "average_erase_cycles": average_erase,
        "maximum_erase_cycles": maximum_erase,
        "data_units_written": written_units,
        "host_write_commands": write_commands,
        "power_on_hours": hours,
        "vendor_workload_timer_minutes": vendor_minutes,
    }

    physical_wear = max([item for item in (wear, vendor_wear) if item is not None] or [0]) > 0
    substantial_erase = average_erase is not None and average_erase >= 10
    host_history_near_zero = (written_units is not None and written_units <= 16) and (
        write_commands is None or write_commands <= 128
    )
    recent_runtime = hours is not None and hours <= 1
    if (physical_wear or substantial_erase) and host_history_near_zero and recent_runtime:
        return _dimension(
            "REVIEW_REQUIRED",
            "Host-visible lifetime history is not continuous with reported physical NAND wear.",
            observed,
        ) | {
            "code": "HISTORY_CONTINUITY_BROKEN",
            "observed": "Non-zero wear/erase history with effectively blank host-write and runtime history.",
            "possible_explanations": [
                "Controller replacement or service/refurbishment activity",
                "Controller reinitialization or a vendor service process",
                "Vendor-specific counter semantics or incomplete lifetime telemetry",
            ],
            "not_established": ["Fraud", "SMART tampering", "Seller manipulation"],
        }

    minimal_wear = (wear in (None, 0)) and (vendor_wear in (None, 0)) and (
        average_erase is None or average_erase <= 1
    ) and (maximum_erase is None or maximum_erase <= 1)
    minimal_usage = (written_units is None or written_units == 0) and (
        hours is None or hours == 0
    ) and (vendor_minutes is None or vendor_minutes <= 15)
    if minimal_wear and minimal_usage:
        return _dimension(
            "CONSISTENT",
            "The available counters form a near-new / minimal-use profile.",
            observed,
        ) | {
            "code": "CONSISTENT_MINIMAL_USE_PROFILE",
            "not_established": ["Factory sealed", "Never used", "Supply-chain provenance"],
        }

    vendor_statuses = {
        field_status(values, "vendor_media_wear_percent"),
        field_status(values, "nand_erase_cycles_average"),
    }
    if "QUERY_FAILED" in vendor_statuses:
        return _dimension(
            "PARTIAL",
            "The vendor wear query failed, so physical-wear continuity could not be fully evaluated.",
            observed,
        ) | {"code": "VENDOR_WEAR_QUERY_FAILED"}
    if average_erase is None and vendor_wear is None:
        return _dimension(
            "PARTIAL",
            "Generic lifetime counters are available, but no supported vendor wear log was available for an independent continuity check.",
            observed,
        ) | {"code": "VENDOR_WEAR_UNAVAILABLE"}

    return _dimension(
        "CONSISTENT",
        "No contradiction was detected between host-visible usage and the available wear evidence.",
        observed,
    ) | {"code": "NO_HISTORY_CONTRADICTION_DETECTED"}


def _media_health(values: dict[str, Any]) -> dict[str, Any]:
    smart = raw_value(values, "smart_health")
    critical = number(values, "critical_warning")
    media_errors = number(values, "media_errors")
    program_failures = number(values, "program_fail_count")
    erase_failures = number(values, "erase_fail_count")
    error_values = [item for item in (media_errors, program_failures, erase_failures) if item is not None]
    evidence = {
        "smart_health": smart,
        "critical_warning": critical,
        "media_errors": media_errors,
        "program_failures": program_failures,
        "erase_failures": erase_failures,
    }
    if smart == "FAILED" or (critical is not None and critical != 0):
        return _dimension("REVIEW_REQUIRED", "The drive reports a failed SMART state or non-zero NVMe critical warning.", evidence)
    if any(item > 0 for item in error_values):
        return _dimension("REVIEW_REQUIRED", "One or more media/program/erase failure counters are non-zero.", evidence)
    if smart == "PASSED" and critical in (None, 0):
        return _dimension("GOOD", "Current SMART health passes and no NVMe critical warning was observed.", evidence)
    if "QUERY_FAILED" in {field_status(values, "smart_health"), field_status(values, "critical_warning")}:
        return _dimension("QUERY_FAILED", "A current media-health query failed; missing data was not converted to zero.", evidence)
    return _dimension("PARTIAL", "Current media-health evidence is incomplete.", evidence)


def _endurance(values: dict[str, Any]) -> dict[str, Any]:
    used = number(values, "percentage_used")
    vendor_used = number(values, "vendor_media_wear_percent")
    effective = max([item for item in (used, vendor_used) if item is not None] or [-1])
    remaining = None if effective < 0 else max(0, 100 - effective)
    evidence = {"percentage_used": used, "vendor_media_wear_percent": vendor_used, "remaining_percent": remaining}
    if effective < 0:
        return _dimension("UNAVAILABLE", "No supported endurance percentage was returned.", evidence)
    if effective >= 100:
        return _dimension("CRITICAL", "Reported endurance consumption is at or above 100%.", evidence)
    if effective >= 80:
        return _dimension("WORN", "Reported endurance consumption is high; review replacement policy.", evidence)
    if effective >= 20:
        return _dimension("USED", "Meaningful endurance has been consumed, but the drive is below the high-wear threshold.", evidence)
    if effective == 0:
        return _dimension("EXCELLENT", "Reported endurance consumption rounds to 0%.", evidence)
    return _dimension("GOOD", "Reported endurance consumption is low.", evidence)


def _error_state(values: dict[str, Any]) -> dict[str, Any]:
    names = (
        "media_errors", "num_err_log_entries", "program_fail_count", "erase_fail_count",
        "end_to_end_error_count", "crc_error_count",
    )
    evidence = {name: number(values, name) for name in names}
    present = {key: value for key, value in evidence.items() if value is not None}
    if any(value > 0 for value in present.values()):
        return _dimension("REVIEW_REQUIRED", "At least one available error counter is non-zero.", evidence)
    if any(field_status(values, name) == "QUERY_FAILED" for name in names):
        return _dimension("QUERY_FAILED", "At least one error-counter query failed; missing data was not converted to zero.", evidence)
    if present:
        state = "GOOD" if len(present) >= 2 else "PARTIAL"
        return _dimension(state, "All available error counters are zero; unavailable counters remain explicitly unknown.", evidence)
    return _dimension("UNAVAILABLE", "No supported error counters were available.", evidence)


def _usage(values: dict[str, Any]) -> dict[str, Any]:
    hours = number(values, "power_on_hours")
    writes = number(values, "data_units_written")
    reads = number(values, "data_units_read")
    write_bytes = None if writes is None else writes * 512_000
    if (hours in (None, 0)) and (write_bytes in (None, 0)):
        state = "MINIMAL"
    elif (hours or 0) <= 100 and (write_bytes or 0) <= 5_000_000_000_000:
        state = "LIGHT"
    else:
        state = "USED"
    return _dimension(
        state,
        "Usage is descriptive and is not itself a health failure.",
        {"power_on_hours": hours, "host_writes_bytes": write_bytes, "host_reads_bytes": None if reads is None else reads * 512_000},
    )


def _performance(last_result: dict[str, Any] | None) -> dict[str, Any]:
    verification = (last_result or {}).get("read_verification", {})
    status = verification.get("status", "NOT_RUN")
    scan = verification.get("scan", {}) if isinstance(verification.get("scan"), dict) else {}
    speed = scan.get("throughput_bytes_per_second") or verification.get("throughput_bytes_per_second")
    verified_bytes = scan.get("bytes_read") or verification.get("bytes_read")
    if status == "VERIFIED":
        state = "VERIFIED"
        explanation = "A preserved full-capacity read completed successfully."
    elif status in ("FAILED", "QUERY_FAILED"):
        state = "FAILED"
        explanation = "The last preserved full-capacity read did not verify successfully."
    else:
        state = "NOT_RUN"
        explanation = "No verified full-capacity read result was found for this summary."
    return _dimension(state, explanation, {
        "last_full_read_status": status,
        "throughput_bytes_per_second": speed,
        "verified_bytes": verified_bytes,
        "source_run_id": (last_result or {}).get("run_id"),
    })


def build_summary(
    current: dict[str, Any],
    *,
    last_result: dict[str, Any] | None = None,
    run_id: str,
    observed_utc: str,
) -> dict[str, Any]:
    values = current.get("values", {})
    target = current.get("target") or current.get("identity") or {}
    dimensions = {
        "media_health": _media_health(values),
        "endurance": _endurance(values),
        "error_state": _error_state(values),
        "usage": _usage(values),
        "performance": _performance(last_result),
        "history_trust": _history_trust(values),
    }
    history = dimensions["history_trust"]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "CNDRIVETRUST_HEALTH_USAGE_SUMMARY",
        "run_id": run_id,
        "observed_utc": observed_utc,
        "target": {
            "device_path": target.get("device_path"),
            "manufacturer": raw_value(values, "manufacturer") or target.get("manufacturer"),
            "model": raw_value(values, "model") or target.get("model"),
            "serial": raw_value(values, "serial") or target.get("serial"),
            "firmware": raw_value(values, "firmware") or target.get("firmware"),
            "capacity_bytes": number(values, "capacity_bytes") or target.get("capacity_bytes"),
            "transport": raw_value(values, "transport") or target.get("transport"),
        },
        "dimensions": dimensions,
        "current_values": values,
        "usage_display": {
            "power_on_hours": duration_hours(number(values, "power_on_hours")),
            "vendor_runtime": duration_minutes(number(values, "vendor_workload_timer_minutes")),
            "host_reads": nvme_units_human(number(values, "data_units_read")),
            "host_writes": nvme_units_human(number(values, "data_units_written")),
            "controller_busy_time_minutes": number(values, "controller_busy_time"),
        },
        "performance_display": {
            "last_verified_read_speed": rate_human(dimensions["performance"]["evidence"].get("throughput_bytes_per_second")),
            "verified_capacity": bytes_human(dimensions["performance"]["evidence"].get("verified_bytes")),
        },
        "overall": "REVIEW_REQUIRED" if any(
            item["state"] in ("REVIEW_REQUIRED", "CRITICAL", "FAILED") for item in dimensions.values()
        ) else (
            "PARTIAL" if any(item["state"] in ("PARTIAL", "UNAVAILABLE", "QUERY_FAILED") for item in dimensions.values())
            else "SUPPORTED"
        ),
        "assessment_limits": [
            "This summary does not prove that a drive is factory-new, untampered, or reliable in the future.",
            "Zero errors and zero power-on hours are observations, not proof of supply-chain history.",
            "Vendor-specific fields are interpreted only by the matching vendor module.",
        ],
    }
    return summary

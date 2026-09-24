"""Samsung enterprise NVMe vendor telemetry decoders.

Field meanings in this module apply only after Samsung PCI vendor identity has
been established. The raw log page remains the authoritative evidence.
"""

from __future__ import annotations

from typing import Any

SAMSUNG_VENDOR_ID = 0x144D
EXTENDED_SMART_LOG_ID = 0xCA
EXTENDED_SMART_LOG_BYTES = 512


def parse_extended_smart(record: dict[str, Any]) -> dict[str, Any]:
    status = record.get("status", "NOT_EVALUATED")
    payload = record.get("stdout_bytes")
    if status != "OK":
        return {"status": status, "values": {}, "reason": record.get("stderr", "")}
    if not isinstance(payload, bytes) or len(payload) < 112:
        return {
            "status": "QUERY_FAILED",
            "values": {},
            "reason": "Samsung log page 0xCA was shorter than 112 bytes.",
        }

    names = {
        0xAB: "program_fail_count",
        0xAC: "erase_fail_count",
        0xB8: "end_to_end_error_count",
        0xC7: "crc_error_count",
        0xE2: "vendor_media_wear_percent",
        0xE3: "host_read_percentage",
        0xE4: "vendor_workload_timer_minutes",
        0xEA: "thermal_throttling_raw",
        0xF4: "physical_nand_writes_raw",
        0xF5: "lifetime_data_units_written_raw",
    }
    values: dict[str, Any] = {}
    attributes: dict[str, Any] = {}
    for offset in range(0, min(len(payload), 192), 12):
        entry = payload[offset:offset + 12]
        if len(entry) < 12:
            break
        attribute_id = entry[0]
        if attribute_id in (0x00, 0xFF):
            continue
        normalized = entry[3]
        raw = int.from_bytes(entry[5:12], "little")
        attributes[f"0x{attribute_id:02X}"] = {
            "normalized": normalized,
            "raw": raw,
            "offset": offset,
        }
        if attribute_id == 0xAD:
            values.update({
                "wear_level_normalized": normalized,
                "nand_erase_cycles_minimum": int.from_bytes(entry[5:7], "little"),
                "nand_erase_cycles_maximum": int.from_bytes(entry[7:9], "little"),
                "nand_erase_cycles_average": int.from_bytes(entry[9:11], "little"),
            })
        elif attribute_id in names:
            values[names[attribute_id]] = raw
    if "nand_erase_cycles_average" not in values:
        return {
            "status": "QUERY_FAILED",
            "values": values,
            "attributes": attributes,
            "reason": "Samsung wear-level attribute 0xAD was not present.",
        }
    return {"status": "VALUE", "values": values, "attributes": attributes}


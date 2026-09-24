"""SCSI/SAS REPORT SUPPORTED OPERATION CODES interpretation."""

from __future__ import annotations

from typing import Any


def summarize(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def state(name: str) -> str:
        record = records.get(name)
        if not isinstance(record, dict):
            return "NOT_EVALUATED"
        status = str(record.get("status") or "QUERY_FAILED")
        if status != "OK":
            return status
        text = (str(record.get("stdout") or "") + str(record.get("stderr") or "")).lower()
        if "not supported" in text or "unsupported" in text:
            return "NOT_SUPPORTED"
        return "SUPPORTED"

    return {
        "protocol": "SCSI",
        "sanitize_command": state("scsi-sanitize-opcode"),
        "block_erase_service_action": state("scsi-sanitize-block-erase"),
        "crypto_erase_service_action": state("scsi-sanitize-crypto-erase"),
        "overwrite_service_action": state("scsi-sanitize-overwrite"),
        "execution": "DISABLED",
    }


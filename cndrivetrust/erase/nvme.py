"""NVMe capability decoding from Identify Controller data."""

from __future__ import annotations

from typing import Any


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def decode(id_ctrl: dict[str, Any], sanitize_log_status: str) -> dict[str, Any]:
    """Decode only standardized basic capability bits.

    Raw Identify Controller data is retained by the caller. Unknown or absent
    fields remain UNKNOWN rather than being interpreted as unsupported.
    """
    sanicap = _integer(id_ctrl.get("sanicap"))
    oacs = _integer(id_ctrl.get("oacs"))
    fna = _integer(id_ctrl.get("fna"))

    def bit(value: int | None, position: int) -> str:
        return "UNKNOWN" if value is None else ("SUPPORTED" if value & (1 << position) else "NOT_SUPPORTED")

    return {
        "protocol": "NVME",
        "sanitize": {
            "crypto_erase": bit(sanicap, 0),
            "block_erase": bit(sanicap, 1),
            "overwrite": bit(sanicap, 2),
            "status_log": "AVAILABLE" if sanitize_log_status == "OK" else sanitize_log_status,
        },
        "format": {
            "command": bit(oacs, 1),
            "crypto_erase_modifier": bit(fna, 2),
        },
        "raw_capability_fields": {"sanicap": sanicap, "oacs": oacs, "fna": fna},
        "execution": "DISABLED",
    }


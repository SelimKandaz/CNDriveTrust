"""Read-only protocol-aware erase/sanitize capability discovery."""

from __future__ import annotations

import json
from typing import Any, Callable

from . import EXECUTION_STATUS
from . import ata, nvme, scsi

RunCommand = Callable[..., dict[str, Any]]

def _is_prohibited(argv: list[str]) -> bool:
    lowered = [str(item).lower() for item in argv]
    executable = lowered[0].rsplit("/", 1)[-1] if lowered else ""
    if executable == "nvme" and len(lowered) > 1 and lowered[1] in ("sanitize", "format"):
        return True
    if executable in ("sg_sanitize", "blkdiscard", "dd"):
        return True
    return executable == "hdparm" and any("security-erase" in item for item in lowered[1:])


def classify_protocol(label: dict[str, Any]) -> str:
    path = str(label.get("device_path") or "")
    transport = str(label.get("transport") or label.get("lsblk_transport") or "").upper()
    if path.startswith("/dev/nvme") or transport == "NATIVE_NVME":
        return "NVME"
    if transport in ("SAS", "SCSI", "HBA_OR_RAID"):
        return "SCSI"
    if transport in ("SATA", "ATA"):
        return "ATA"
    return "GENERIC_BLOCK"


def media_type(label: dict[str, Any]) -> str:
    rotational = label.get("rotational")
    if rotational is True or rotational == 1:
        return "ROTATIONAL_HDD"
    if rotational is False or rotational == 0:
        return "SOLID_STATE"
    return "UNKNOWN"


def _run(run_command: RunCommand, argv: list[str], **kwargs: Any) -> dict[str, Any]:
    if _is_prohibited(argv):
        raise RuntimeError("Destructive command attempted inside read-only discovery")
    return run_command(argv, **kwargs)


def collect(label: dict[str, Any], run_command: RunCommand, parse_json: Callable[[dict[str, Any]], dict[str, Any]], nvme_controller: Callable[[str], str | None]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    protocol = classify_protocol(label)
    path = str(label["device_path"])
    records: dict[str, dict[str, Any]] = {}
    capabilities: dict[str, Any]

    if protocol == "NVME":
        controller = nvme_controller(path)
        if not controller:
            capabilities = {"protocol": "NVME", "query_status": "QUERY_FAILED", "execution": EXECUTION_STATUS}
        else:
            records["nvme-id-ctrl"] = _run(run_command, ["nvme", "id-ctrl", controller, "--output-format=json"], timeout=60)
            records["nvme-sanitize-log"] = _run(run_command, ["nvme", "sanitize-log", controller, "--human-readable"], timeout=60)
            capabilities = nvme.decode(parse_json(records["nvme-id-ctrl"]), str(records["nvme-sanitize-log"].get("status")))
    elif protocol == "ATA":
        records["ata-identify"] = _run(run_command, ["hdparm", "-I", path], timeout=60)
        capabilities = ata.parse_identify(str(records["ata-identify"].get("stdout") or ""), str(records["ata-identify"].get("status")))
    elif protocol == "SCSI":
        # REPORT SUPPORTED OPERATION CODES is read-only. No SANITIZE command is sent.
        records["scsi-inquiry"] = _run(run_command, ["sg_inq", path], timeout=60)
        records["scsi-sanitize-opcode"] = _run(run_command, ["sg_opcodes", "--opcode=0x48", path], timeout=60)
        records["scsi-sanitize-overwrite"] = _run(run_command, ["sg_opcodes", "--opcode=0x48,0x01", path], timeout=60)
        records["scsi-sanitize-block-erase"] = _run(run_command, ["sg_opcodes", "--opcode=0x48,0x02", path], timeout=60)
        records["scsi-sanitize-crypto-erase"] = _run(run_command, ["sg_opcodes", "--opcode=0x48,0x03", path], timeout=60)
        capabilities = scsi.summarize(records)
    else:
        capabilities = {
            "protocol": "GENERIC_BLOCK",
            "native_sanitize": "NOT_EVALUATED",
            "future_overwrite_methods": ["ZERO_FILL", "RANDOM_OVERWRITE", "READBACK_VERIFICATION"],
            "warning": "Overwrite is not assumed equivalent to protocol-native secure erase or sanitize.",
            "execution": EXECUTION_STATUS,
        }

    result = {
        "schema_version": "2.2",
        "artifact_type": "CNDRIVETRUST_ERASE_CAPABILITY_DISCOVERY",
        "target": label,
        "protocol": protocol,
        "media_type": media_type(label),
        "transport": label.get("transport"),
        "capabilities": capabilities,
        "execution": {
            "status": EXECUTION_STATUS,
            "implemented": False,
            "reason": "This release performs capability discovery only and contains no destructive execution backend.",
        },
    }
    return result, records


def contains_prohibited_command(records: dict[str, dict[str, Any]]) -> bool:
    for record in records.values():
        argv = record.get("argv", []) if isinstance(record, dict) else []
        if _is_prohibited([str(item) for item in argv]):
            return True
    return False

#!/usr/bin/env python3
"""Read-only SSD/NVMe evidence collection for the Dell CNGPUStress runner."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from cndrivetrust.vendors import samsung as samsung_vendor

PROJECT_NAME = "CNDriveTrust"
PROJECT_TAGLINE = "Evidence-Driven SSD/NVMe Readiness & Provenance"
VERSION = "2.3.0"
DEFAULT_RESULT_ROOT = Path("/var/lib/harddrive-test-results")
DEFAULT_CONFIG = Path("/etc/harddrive-test/config.json")
CRITICAL_MOUNTS = ("/", "/boot", "/boot/efi")
MAX_PEL_BYTES = 64 * 1024 * 1024
NVME_VENDOR_NAMES = {0x144D: "Samsung"}
NVME_DATA_UNIT_BYTES = 512_000
SAMSUNG_VENDOR_ID = samsung_vendor.SAMSUNG_VENDOR_ID
SAMSUNG_EXTENDED_SMART_LOG_ID = samsung_vendor.EXTENDED_SMART_LOG_ID
SAMSUNG_EXTENDED_SMART_LOG_BYTES = samsung_vendor.EXTENDED_SMART_LOG_BYTES
NVME_COUNTERS = (
    "percentage_used",
    "power_on_hours",
    "data_units_written",
    "data_units_read",
    "host_read_commands",
    "host_write_commands",
    "power_cycles",
    "unsafe_shutdowns",
    "media_errors",
    "num_err_log_entries",
    "vendor_media_wear_percent",
    "nand_erase_cycles_average",
    "vendor_workload_timer_minutes",
)
COUNTER_LABELS = {
    "percentage_used": "Percentage Used",
    "power_on_hours": "Power On Hours",
    "data_units_written": "Data Units Written",
    "power_cycles": "Power Cycles",
    "unsafe_shutdowns": "Unsafe Shutdowns",
    "media_errors": "Media/Data Integrity Errors",
    "num_err_log_entries": "Error Log Entries",
    "vendor_media_wear_percent": "Samsung Media Wear",
    "nand_erase_cycles_average": "Average NAND Erase Cycles",
    "vendor_workload_timer_minutes": "Samsung Workload Timer",
}
EXPLANATION = [
    "Controller replacement or refurbishment/service activity.",
    "Controller reinitialization or a vendor service process.",
    "Lifetime telemetry may be incomplete or have vendor-specific semantics.",
]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_component(value: Any, fallback: str = "UNKNOWN") -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    return text[:120] or fallback


def command_status(returncode: int | None, output: str, executable_present: bool) -> str:
    if not executable_present:
        return "UNSUPPORTED"
    if returncode == 0:
        return "OK"
    lowered = output.lower()
    if any(term in lowered for term in (
        "not supported", "unsupported", "invalid opcode", "unknown log page", "invalid log page",
    )):
        return "UNSUPPORTED"
    if output.strip():
        return "QUERY_FAILED"
    return "QUERY_FAILED"


def run_command(argv: list[str], timeout: int = 90, binary_stdout: bool = False) -> dict[str, Any]:
    started = utc_now()
    executable = argv[0]
    if not shutil.which(executable):
        return {
            "argv": argv,
            "started_utc": started,
            "ended_utc": utc_now(),
            "returncode": None,
            "status": "UNSUPPORTED",
            "stdout": "",
            "stderr": f"Required command not installed: {executable}",
        }
    try:
        proc = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=not binary_stdout,
            encoding=None if binary_stdout else "utf-8",
            errors=None if binary_stdout else "replace",
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
        stdout = proc.stdout or (b"" if binary_stdout else "")
        stderr = proc.stderr or (b"" if binary_stdout else "")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        combined = stderr if binary_stdout else stdout + stderr
        result = {
            "argv": argv,
            "started_utc": started,
            "ended_utc": utc_now(),
            "returncode": proc.returncode,
            "status": command_status(proc.returncode, combined, True),
            "stdout": "" if binary_stdout else stdout,
            "stderr": stderr,
        }
        if binary_stdout:
            result["stdout_bytes"] = stdout
            result["stdout_binary"] = True
        return result
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or (b"" if binary_stdout else "")
        err = exc.stderr or (b"" if binary_stdout else "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        result = {
            "argv": argv,
            "started_utc": started,
            "ended_utc": utc_now(),
            "returncode": None,
            "status": "QUERY_FAILED",
            "stdout": "" if binary_stdout else out,
            "stderr": f"Timed out after {timeout}s\n{err}",
        }
        if binary_stdout:
            result["stdout_bytes"] = out
            result["stdout_binary"] = True
        return result
    except OSError as exc:
        return {
            "argv": argv,
            "started_utc": started,
            "ended_utc": utc_now(),
            "returncode": None,
            "status": "QUERY_FAILED",
            "stdout": "",
            "stderr": str(exc),
        }


def save_raw_record(root: Path, scope: str, name: str, record: dict[str, Any]) -> None:
    prefix = root / "raw" / safe_component(scope) / safe_component(name)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    stdout_bytes = record.get("stdout_bytes")
    if isinstance(stdout_bytes, bytes):
        (prefix.with_suffix(".stdout.bin")).write_bytes(stdout_bytes)
    else:
        (prefix.with_suffix(".stdout.txt")).write_text(record.get("stdout", ""), encoding="utf-8", errors="replace")
    (prefix.with_suffix(".stderr.txt")).write_text(record.get("stderr", ""), encoding="utf-8", errors="replace")
    metadata = {key: value for key, value in record.items() if key not in ("stdout", "stderr", "stdout_bytes")}
    if isinstance(stdout_bytes, bytes):
        metadata["stdout_bytes_count"] = len(stdout_bytes)
    (prefix.with_suffix(".meta.json")).write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def parse_json_output(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") in ("UNSUPPORTED", "BLOCKED", "NOT_EVALUATED"):
        return {}
    text = str(record.get("stdout", "")).strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {"_items": value}
    except (ValueError, TypeError):
        return {}


def parse_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def parse_samsung_extended_smart(record: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper for the isolated Samsung vendor decoder."""
    return samsung_vendor.parse_extended_smart(record)


def parse_sanitize_log(record: dict[str, Any]) -> dict[str, Any]:
    text = str(record.get("stdout", ""))
    status = record.get("status", "NOT_EVALUATED")
    if status != "OK":
        return {"status": status, "value": None, "reason": record.get("stderr", "")}
    match = re.search(r"Sanitize Status\s+\(SSTAT\)\s*:\s*(0x[0-9a-f]+|\d+)", text, re.I)
    if not match:
        return {"status": "QUERY_FAILED", "value": None, "reason": "SSTAT was not found in sanitize-log output."}
    sstat = int(match.group(1), 0)
    return {
        "status": "VALUE",
        "value": {
            "sstat": sstat,
            "operation_status_code": sstat & 0x7,
            "never_sanitized": (sstat & 0x7) == 0,
            "global_data_erased": bool(sstat & 0x100),
            "completed_overwrite_passes": (sstat >> 3) & 0x1F,
        },
    }


def decode_nvme_version(value: Any) -> str | None:
    parsed = parse_integer(value)
    if parsed is None:
        text = str(value).strip() if value is not None else ""
        return text or None
    major = (parsed >> 16) & 0xFFFF
    minor = (parsed >> 8) & 0xFF
    tertiary = parsed & 0xFF
    return f"{major}.{minor}" if tertiary == 0 else f"{major}.{minor}.{tertiary}"


def classify_smartctl_optional_selftest(records: dict[str, dict[str, Any]]) -> None:
    text_record = records.get("smartctl-text", {})
    json_record = records.get("smartctl-json", {})
    smart_json = parse_json_output(json_record)
    health_passed = get_nested(smart_json, "smart_status", "passed") is True
    health_log = get_nested(smart_json, "nvme_smart_health_information_log")
    text = str(text_record.get("stdout", ""))
    unsupported_selftest_log = bool(
        re.search(r"Read Self-test Log failed:.*Invalid Field in Command", text, flags=re.IGNORECASE)
    )
    if not (health_passed and isinstance(health_log, dict) and unsupported_selftest_log):
        return
    explanation = (
        "SMART/NVMe health data was returned and health passed; the optional NVMe self-test-log query "
        "returned Invalid Field in Command, so smartctl's aggregate exit status is partial, not a health failure."
    )
    for name in ("smartctl-text", "smartctl-json"):
        record = records.get(name)
        if record and record.get("returncode") == 4:
            record["status"] = "PARTIAL"
            record["status_reason"] = explanation


def empty_record(argv: list[str], status: str, reason: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "argv": argv,
        "started_utc": now,
        "ended_utc": now,
        "returncode": None,
        "status": status,
        "stdout": "",
        "stderr": reason,
    }


def collect_persistent_event_log(controller: str, id_ctrl_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Read a supported NVMe PEL without writing persistent device data.

    The only stateful step is the NVMe-defined temporary reporting context;
    the function releases it in a finally block after the read attempt.
    """
    id_ctrl = parse_json_output(id_ctrl_record)
    lpa = parse_integer(id_ctrl.get("lpa"))
    pels = parse_integer(id_ctrl.get("pels"))
    base_argv = ["nvme", "persistent-event-log", controller]
    if lpa is None and pels is None:
        status = id_ctrl_record.get("status")
        state = "NOT_EVALUATED" if status in ("UNSUPPORTED", "QUERY_FAILED") else "UNAVAILABLE"
        return {"nvme-persistent-event-log": empty_record(
            base_argv, state, "Identify Controller did not expose readable PEL capability fields; no PEL request was sent."
        )}

    pel_flag = bool(lpa is not None and lpa & 0x10)
    size_flag = bool(pels is not None and pels > 0)
    if not pel_flag and not size_flag:
        return {"nvme-persistent-event-log": empty_record(
            base_argv, "UNSUPPORTED",
            f"Identify Controller reports Persistent Event Log unsupported (LPA={lpa!r}, PELS={pels!r}); no PEL request was sent.",
        )}

    records: dict[str, dict[str, Any]] = {}
    establish_argv = [*base_argv, "--action=1", "--log_len=0"]
    establish = run_command(establish_argv, timeout=45)
    records["nvme-pel-context-establish"] = establish
    if establish.get("status") != "OK":
        records["nvme-persistent-event-log"] = {
            **establish,
            "argv": establish_argv,
            "pel_supported_by_identify": True,
            "pel_phase": "establish_context",
        }
        return records

    release_argv = [*base_argv, "--action=2", "--log_len=0"]
    final_record: dict[str, Any] | None = None
    try:
        header_argv = [*base_argv, "--action=0", "--log_len=512", "--raw-binary"]
        header = run_command(header_argv, timeout=45, binary_stdout=True)
        records["nvme-pel-header"] = header
        data = header.get("stdout_bytes")
        if header.get("status") != "OK" or not isinstance(data, bytes):
            final_record = {**header, "pel_phase": "read_header"}
            records["nvme-persistent-event-log"] = final_record
            return records
        if len(data) < 512 or data[0] != 0x0D:
            final_record = {
                **header,
                "status": "QUERY_FAILED",
                "stderr": (header.get("stderr", "") + "\nInvalid PEL header: expected a 512-byte header with log identifier 0x0D.").strip(),
                "pel_phase": "validate_header",
            }
            records["nvme-persistent-event-log"] = final_record
            return records

        total_events = int.from_bytes(data[4:8], "little")
        total_length = int.from_bytes(data[8:16], "little")
        if total_length < 512:
            final_record = {
                **header,
                "status": "QUERY_FAILED",
                "stderr": (header.get("stderr", "") + f"\nInvalid PEL total length: {total_length} bytes.").strip(),
                "pel_phase": "validate_header",
            }
            records["nvme-persistent-event-log"] = final_record
            return records
        if total_length > MAX_PEL_BYTES:
            final_record = {
                **header,
                "status": "BLOCKED",
                "stderr": (header.get("stderr", "") + f"\nPEL size {total_length} exceeds the read-only collection cap of {MAX_PEL_BYTES} bytes.").strip(),
                "pel_phase": "size_cap",
                "pel_total_length": total_length,
                "pel_total_events": total_events,
            }
            return records | {"nvme-persistent-event-log": final_record}

        read_argv = [*base_argv, "--action=0", f"--log_len={total_length}", "--raw-binary"]
        pel = run_command(read_argv, timeout=180, binary_stdout=True)
        pel["pel_supported_by_identify"] = True
        pel["pel_total_length"] = total_length
        pel["pel_total_events"] = total_events
        pel["pel_log_id"] = data[0]
        pel["pel_revision"] = data[16]
        if pel.get("status") == "OK":
            pel_data = pel.get("stdout_bytes")
            if not isinstance(pel_data, bytes) or len(pel_data) != total_length:
                pel["status"] = "QUERY_FAILED"
                pel["stderr"] = (pel.get("stderr", "") + f"\nPEL length mismatch: expected {total_length}, received {len(pel_data) if isinstance(pel_data, bytes) else 'no binary data'}.").strip()
            elif pel_data[:512] != data[:512]:
                pel["status"] = "QUERY_FAILED"
                pel["stderr"] = (pel.get("stderr", "") + "\nPEL header changed between the initial read and complete read.").strip()
        final_record = pel
        records["nvme-persistent-event-log"] = pel
        return records
    finally:
        release = run_command(release_argv, timeout=45)
        records["nvme-pel-context-release"] = release
        if final_record is not None:
            final_record["pel_context_release_status"] = release.get("status")


def normalize_error_log(record: dict[str, Any]) -> dict[str, Any]:
    status = record.get("status", "NOT_EVALUATED")
    payload = parse_json_output(record)
    if not isinstance(payload, dict) or "errors" not in payload:
        return {"value": None, "source": "nvme error-log", "time": record.get("ended_utc", utc_now()), "status": "QUERY_FAILED"}
    entries = payload.get("errors")
    if status != "OK":
        return {"value": None, "source": "nvme error-log", "time": record.get("ended_utc", utc_now()), "status": status}
    if not isinstance(entries, list):
        return {"value": None, "source": "nvme error-log", "time": record.get("ended_utc", utc_now()), "status": "QUERY_FAILED"}
    active = [entry for entry in entries if isinstance(entry, dict) and (parse_integer(entry.get("error_count")) or 0) > 0]
    return {
        "value": active,
        "source": "nvme error-log",
        "time": record.get("ended_utc", utc_now()),
        "status": "VALUE" if active else "EMPTY",
        "reported_slots": len(entries),
    }


def get_nested(data: Any, *path: str) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def find_value(data: Any, keys: tuple[str, ...]) -> Any:
    if isinstance(data, dict):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        for value in data.values():
            found = find_value(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_value(value, keys)
            if found is not None:
                return found
    return None


def value_record(value: Any, source: str, observed_at: str | None = None, unit: str | None = None) -> dict[str, Any]:
    if value is None or value == "":
        state = "UNAVAILABLE"
    elif isinstance(value, (dict, list)) and not value:
        state = "EMPTY"
    elif isinstance(value, (int, float)) and value == 0:
        state = "0"
    else:
        state = "VALUE"
    result: dict[str, Any] = {
        "value": value,
        "source": source,
        "time": observed_at or utc_now(),
        "status": state,
    }
    if unit:
        result["unit"] = unit
    return result


def disks_from_lsblk(data: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("type", "")).lower() == "disk":
                found.append(node)
            visit(node.get("children"))

    visit(data.get("blockdevices"))
    unique: dict[str, dict[str, Any]] = {}
    for disk in found:
        key = str(disk.get("path") or disk.get("name") or "")
        if key:
            unique[key] = disk
    return sorted(unique.values(), key=lambda item: str(item.get("path") or item.get("name") or ""))


def disk_ancestors_from_lsblk_json(payload: str) -> set[str]:
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return set()
    result: set[str] = set()

    def visit(nodes: Any) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("type", "")).lower() == "disk":
                name = str(node.get("name") or node.get("path") or "")
                if name:
                    result.add(name)
            visit(node.get("children"))

    visit(data.get("blockdevices"))
    return result


def canonical_device_source(source: str) -> str:
    source = source.strip()
    if "[" in source:
        source = source.split("[", 1)[0]
    if source.startswith(("UUID=", "PARTUUID=", "LABEL=", "PARTLABEL=")):
        resolved = run_command(["findfs", source], timeout=10)
        if resolved.get("returncode") == 0 and resolved.get("stdout", "").strip():
            return resolved["stdout"].strip()
    return source


def resolve_protected_disks(
    mount_sources: dict[str, str],
    inverse_payloads: dict[str, str],
) -> tuple[set[str], list[str]]:
    protected: set[str] = set()
    errors: list[str] = []
    for mountpoint in ("/", "/boot", "/boot/efi"):
        source = mount_sources.get(mountpoint, "")
        if mountpoint == "/" and not source:
            errors.append("Root mount source could not be determined.")
            continue
        if not source:
            continue
        resolved_source = canonical_device_source(source)
        if not resolved_source.startswith("/dev/"):
            errors.append(f"{mountpoint} source is not a resolvable block device: {source}")
            continue
        payload = inverse_payloads.get(resolved_source)
        disks = disk_ancestors_from_lsblk_json(payload or "")
        if not disks:
            errors.append(f"No physical disk ancestor was resolved for {mountpoint} source {resolved_source}.")
            continue
        protected.update(disks)
    if not protected:
        errors.append("No physical boot disk could be proven.")
    return protected, errors


def source_for_mount(mountpoint: str) -> dict[str, Any]:
    return run_command(["findmnt", "--noheadings", "--raw", "--output", "SOURCE", "--target", mountpoint], timeout=10)


def detect_protection() -> tuple[set[str], dict[str, str], dict[str, dict[str, Any]], list[str]]:
    mount_sources: dict[str, str] = {}
    mount_records: dict[str, dict[str, Any]] = {}
    inverse_records: dict[str, dict[str, Any]] = {}
    inverse_payloads: dict[str, str] = {}
    errors: list[str] = []
    for mountpoint in CRITICAL_MOUNTS:
        record = source_for_mount(mountpoint)
        mount_records[mountpoint] = record
        source = record.get("stdout", "").strip().splitlines()
        if record.get("returncode") == 0 and source and source[0]:
            resolved = canonical_device_source(source[0])
            mount_sources[mountpoint] = resolved
            if resolved.startswith("/dev/") and resolved not in inverse_payloads:
                inv = run_command(
                    ["lsblk", "--inverse", "--json", "--paths", "--output", "NAME,TYPE", resolved],
                    timeout=15,
                )
                inverse_records[resolved] = inv
                inverse_payloads[resolved] = inv.get("stdout", "")
        elif mountpoint == "/":
            errors.append("findmnt failed to identify the root source.")
    protected, map_errors = resolve_protected_disks(mount_sources, inverse_payloads)
    errors.extend(map_errors)
    return protected, mount_sources, mount_records | {f"lsblk-inverse:{key}": val for key, val in inverse_records.items()}, errors


def classify_transport(disk: dict[str, Any]) -> tuple[str, str]:
    tran = str(disk.get("tran") or "").strip().lower()
    path = str(disk.get("path") or disk.get("name") or "")
    if tran == "nvme" or re.match(r"^/dev/nvme\d+n\d+", path):
        return "NATIVE_NVME", "lsblk transport/path"
    if tran == "usb":
        return "USB_BRIDGE", "lsblk transport"
    if tran in ("sata", "ata"):
        return "SATA", "lsblk transport"
    if tran in ("sas", "scsi"):
        return "HBA_OR_RAID", "lsblk transport; controller mode requires corroboration"
    if tran in ("pcie", "pci"):
        return "PCIE", "lsblk transport"
    return "OTHER_OR_UNKNOWN", "transport not identified by lsblk"


def device_label(disk: dict[str, Any]) -> dict[str, Any]:
    path = str(disk.get("path") or ("/dev/" + str(disk.get("name", ""))))
    transport, transport_source = classify_transport(disk)
    size = disk.get("size")
    return {
        "device_path": path,
        "kernel_name": str(disk.get("kname") or disk.get("name") or Path(path).name),
        "model": str(disk.get("model") or "").strip() or None,
        "serial": str(disk.get("serial") or "").strip() or None,
        "capacity_bytes": int(size) if str(size or "").isdigit() else None,
        "transport": transport,
        "transport_source": transport_source,
        "lsblk_transport": disk.get("tran"),
        "wwn": disk.get("wwn"),
        "removable": disk.get("rm"),
        "hotplug": disk.get("hotplug"),
        "read_only": disk.get("ro"),
        "rotational": disk.get("rota"),
        "mountpoints": disk.get("mountpoints") or [],
    }


def find_pci_ids(device_path: str) -> dict[str, Any]:
    name = Path(device_path).name
    start = Path("/sys/class/block") / name / "device"
    try:
        resolved = start.resolve(strict=True)
    except OSError:
        return {"value": None, "source": "sysfs", "status": "UNAVAILABLE"}
    for parent in (resolved, *resolved.parents):
        vendor = parent / "vendor"
        device = parent / "device"
        if vendor.is_file() and device.is_file():
            try:
                return {
                    "value": {
                        "vendor_id": vendor.read_text().strip(),
                        "device_id": device.read_text().strip(),
                        "sysfs_path": str(parent),
                    },
                    "source": "SYSFS_PCI_ANCESTOR",
                    "status": "VALUE",
                }
            except OSError:
                break
    return {"value": None, "source": "sysfs", "status": "UNAVAILABLE"}


def nvme_controller_path(device_path: str) -> str | None:
    match = re.match(r"^(/dev/nvme\d+)n\d+(?:p\d+)?$", device_path)
    if match:
        return match.group(1)
    if re.match(r"^/dev/nvme\d+$", device_path):
        return device_path
    return None


def capture_global_evidence() -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    records: dict[str, dict[str, Any]] = {}
    records["lsblk"] = run_command(
        [
            "lsblk", "--json", "--bytes", "--paths", "--output",
            "NAME,KNAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RM,HOTPLUG,RO,PKNAME,WWN,FSTYPE,MOUNTPOINTS",
        ],
        timeout=30,
    )
    lsblk_json = parse_json_output(records["lsblk"])
    disks = disks_from_lsblk(lsblk_json)
    records["nvme-list"] = run_command(["nvme", "list", "--output-format=json"], timeout=45)
    records["smartctl-scan"] = run_command(["smartctl", "--scan-open"], timeout=45)
    records["lspci"] = run_command(["lspci", "-Dnn"], timeout=30)
    records["kernel-log"] = run_command(["dmesg", "--ctime"], timeout=45)
    protection, mount_sources, mount_records, protection_errors = detect_protection()
    protection_data = {
        "protected_disks": sorted(protection),
        "mount_sources": mount_sources,
        "mount_records": {
            key: {
                "argv": value.get("argv"),
                "started_utc": value.get("started_utc"),
                "ended_utc": value.get("ended_utc"),
                "returncode": value.get("returncode"),
                "status": value.get("status"),
                "stdout": value.get("stdout"),
                "stderr": value.get("stderr"),
            }
            for key, value in mount_records.items()
        },
        "fail_closed": bool(protection_errors),
        "errors": protection_errors,
    }
    for key, record in mount_records.items():
        records["mount-" + safe_component(key)] = record
    return records, {"blockdevices": disks}, [protection_data]


def key_for_disk_value(name: str) -> tuple[str, ...]:
    return {
        "model": ("model_name", "mn", "model"),
        "serial": ("serial_number", "sn", "serial"),
        "firmware": ("firmware_version", "fr", "firmware"),
        "manufacturer": ("vendor", "manufacturer", "model_family"),
        "nvme_version": ("ver", "nvme_version"),
        "critical_warning": ("critical_warning",),
        "available_spare": ("available_spare",),
        "available_spare_threshold": ("available_spare_threshold",),
        "percentage_used": ("percentage_used",),
        "data_units_read": ("data_units_read",),
        "data_units_written": ("data_units_written",),
        "host_read_commands": ("host_reads", "host_read_commands"),
        "host_write_commands": ("host_writes", "host_write_commands"),
        "controller_busy_time": ("controller_busy_time",),
        "power_cycles": ("power_cycles",),
        "power_on_hours": ("power_on_hours",),
        "unsafe_shutdowns": ("unsafe_shutdowns",),
        "media_errors": ("media_errors",),
        "num_err_log_entries": ("num_err_log_entries", "error_log_entries"),
        "temperature": ("temperature", "current"),
        "temperature_sensor_1": ("temperature_sensor_1",),
        "temperature_sensor_2": ("temperature_sensor_2",),
        "temperature_sensor_3": ("temperature_sensor_3",),
    }.get(name, (name,))


def extract_ata_attribute(smart_data: dict[str, Any], wanted: tuple[str, ...]) -> Any:
    table = get_nested(smart_data, "ata_smart_attributes", "table")
    if not isinstance(table, list):
        return None
    low = {item.lower() for item in wanted}
    for item in table:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").lower()
        if name in low:
            return get_nested(item, "raw", "value")
    return None


def normalize_device(
    disk: dict[str, Any],
    records: dict[str, dict[str, Any]],
    device_id: str,
    started_utc: str,
) -> dict[str, Any]:
    nvme_ctrl = nvme_controller_path(str(disk.get("device_path", "")))
    nvme_ctrl_json = parse_json_output(records.get("nvme-id-ctrl", {}))
    nvme_ns_json = parse_json_output(records.get("nvme-id-ns", {}))
    nvme_smart_json = parse_json_output(records.get("nvme-smart-log", {}))
    smart_json = parse_json_output(records.get("smartctl-json", {}))
    smart_text = str(records.get("smartctl-text", {}).get("stdout", ""))
    nvme_human = str(records.get("nvme-smart-log-human", {}).get("stdout", ""))
    smart_obj = get_nested(smart_json, "nvme_smart_health_information_log") or {}
    smart_device = get_nested(smart_json, "device") or {}
    smart_status = get_nested(smart_json, "smart_status", "passed")
    values: dict[str, dict[str, Any]] = {}

    for field in (
        "manufacturer", "model", "serial", "firmware", "nvme_version",
        "critical_warning", "available_spare", "available_spare_threshold",
        "percentage_used", "data_units_read", "data_units_written",
        "host_read_commands", "host_write_commands", "controller_busy_time",
        "power_cycles", "power_on_hours", "unsafe_shutdowns", "media_errors",
        "num_err_log_entries", "temperature", "temperature_sensor_1",
        "temperature_sensor_2", "temperature_sensor_3",
    ):
        wanted = key_for_disk_value(field)
        source = "UNAVAILABLE"
        value = find_value(nvme_smart_json, wanted)
        if value is not None:
            source = "nvme smart-log"
        if value is None:
            value = find_value(smart_obj, wanted)
            if value is not None:
                source = "smartctl -x -j"
        if value is None and field in ("model", "serial", "firmware", "manufacturer", "nvme_version"):
            value = find_value(nvme_ctrl_json, wanted)
            if value is not None:
                source = "nvme id-ctrl"
        if value is None and field == "manufacturer":
            vendor_id = parse_integer(nvme_ctrl_json.get("vid"))
            value = NVME_VENDOR_NAMES.get(vendor_id)
            if value is not None:
                source = "nvme id-ctrl PCI vendor ID"
        if value is None and field == "model":
            value = disk.get("model")
            source = "lsblk" if value else "UNAVAILABLE"
        if value is None and field == "serial":
            value = disk.get("serial")
            source = "lsblk" if value else "UNAVAILABLE"
        if value is None and field == "firmware":
            value = find_value(smart_json, wanted)
            source = "smartctl -x -j" if value is not None else "UNAVAILABLE"
        if value is None and field in (
            "power_on_hours", "temperature", "data_units_written",
            "power_cycles", "unsafe_shutdowns",
        ):
            value = extract_ata_attribute(smart_json, wanted)
            if value is not None:
                source = "smartctl ATA attributes"
        if value is None and field == "temperature":
            value = get_nested(smart_json, "temperature", "current")
            if value is not None:
                source = "smartctl -x -j"
        if value is None and field == "power_on_hours":
            value = get_nested(smart_json, "power_on_time", "hours")
            if value is not None:
                source = "smartctl -x -j power_on_time"
        if field == "nvme_version" and value is not None:
            value = decode_nvme_version(value)
        if field in ("manufacturer", "model", "serial", "firmware") and isinstance(value, str):
            value = value.strip() or None
        record = value_record(value, source, started_utc)
        if field == "temperature" and value is not None:
            record["unit"] = "tool-reported native value; consult raw output"
        if field.startswith("temperature_sensor_") and value is not None:
            if source == "nvme smart-log":
                record["unit"] = "K"
            elif source.startswith("smartctl"):
                record["unit"] = "°C"
            else:
                record["unit"] = "tool-reported native value; consult raw output"
        values[field] = record

    # Prefer a temperature explicitly reported in Celsius. Preserve any
    # NVMe-native value separately as the raw command output.
    temp_c = get_nested(smart_json, "temperature", "current")
    temp_source = "smartctl -x -j temperature.current"
    if temp_c is None:
        for text, source in ((smart_text, "smartctl -x text"), (nvme_human, "nvme smart-log --human-readable")):
            match = re.search(r"Temperature(?:\s+Sensor\s+\d+)?\s*:\s*(\d+)\s*(?:C|Celsius)\b", text, re.I)
            if match:
                temp_c = int(match.group(1))
                temp_source = source
                break
    if temp_c is not None:
        values["temperature"] = value_record(temp_c, temp_source, started_utc, "°C")

    for number in range(1, 9):
        field = f"temperature_sensor_{number}"
        if int_value(values, field) is not None and "unit" not in values[field]:
            values[field]["unit"] = "tool-reported native value; consult raw output"
        if field not in values:
            values[field] = value_record(None, "UNAVAILABLE", started_utc)

    # ATA attributes are retained under their own names; they are not
    # relabeled as NVMe media/data-integrity counters.
    ata_vendor_fields = {
        "reallocated_sectors": ("Reallocated_Sector_Ct",),
        "uncorrectable_errors": ("Uncorrectable_Error_Cnt", "Reported_Uncorrect"),
        "crc_errors": ("CRC_Error_Count", "UDMA_CRC_Error_Count"),
        "wear_leveling_count": ("Wear_Leveling_Count",),
        "total_lbas_written": ("Total_LBAs_Written",),
    }
    ata_fields: dict[str, Any] = {}
    for name, patterns in ata_vendor_fields.items():
        value = extract_ata_attribute(smart_json, patterns)
        ata_fields[name] = value_record(value, "smartctl ATA attributes", started_utc)

    for field, value in (
        ("capacity_bytes", disk.get("capacity_bytes")),
        ("device_path", disk.get("device_path")),
        ("namespace_id", find_value(nvme_ns_json, ("nsid",))),
        ("namespace_nguid", find_value(nvme_ns_json, ("nguid",))),
        ("namespace_eui64", find_value(nvme_ns_json, ("eui64",))),
        ("pci_ids", find_pci_ids(str(disk.get("device_path", ""))).get("value")),
    ):
        values[field] = value_record(value, "lsblk/sysfs/nvme id-ns", started_utc)

    if smart_status is not None:
        values["smart_health"] = value_record("PASSED" if smart_status else "FAILED", "smartctl -x -j", started_utc)
    else:
        values["smart_health"] = value_record(None, "smartctl -x -j", started_utc)

    values["firmware_slot_information"] = value_record(
        parse_json_output(records.get("nvme-fw-log", {})) or None,
        "nvme fw-log",
        started_utc,
    )
    values["error_log"] = normalize_error_log(records.get("nvme-error-log", {}))
    pel_record = records.get("nvme-persistent-event-log", {})
    pel_events = pel_record.get("pel_total_events")
    pel_status = pel_record.get("status", "NOT_EVALUATED")
    if pel_status == "OK":
        semantic_status = "EMPTY" if pel_events == 0 else "VALUE"
        pel_value: Any = {
            "total_events": pel_events,
            "total_length_bytes": pel_record.get("pel_total_length"),
            "log_id": pel_record.get("pel_log_id"),
            "revision": pel_record.get("pel_revision"),
        }
    else:
        semantic_status = pel_status
        pel_value = None
    values["persistent_event_log"] = {
        "value": pel_value,
        "source": "nvme persistent-event-log",
        "time": pel_record.get("ended_utc", started_utc),
        "status": semantic_status,
        "explanation": pel_record.get("stderr", ""),
    }
    samsung = parse_samsung_extended_smart(records.get("samsung-extended-smart-0xca", {}))
    samsung_values = samsung.get("values", {}) if isinstance(samsung, dict) else {}
    samsung_units = {
        "vendor_media_wear_percent": "% used",
        "vendor_workload_timer_minutes": "minutes",
        "nand_erase_cycles_minimum": "cycles",
        "nand_erase_cycles_maximum": "cycles",
        "nand_erase_cycles_average": "cycles",
    }
    for name in (
        "program_fail_count", "erase_fail_count", "wear_level_normalized",
        "nand_erase_cycles_minimum", "nand_erase_cycles_maximum", "nand_erase_cycles_average",
        "end_to_end_error_count", "crc_error_count", "vendor_media_wear_percent",
        "host_read_percentage", "vendor_workload_timer_minutes", "thermal_throttling_raw",
        "physical_nand_writes_raw", "lifetime_data_units_written_raw",
    ):
        value = samsung_values.get(name)
        item = value_record(value, "Samsung Extended SMART log page 0xCA", started_utc, samsung_units.get(name))
        if samsung.get("status") not in ("VALUE", "OK") and value is None:
            item["status"] = samsung.get("status", "NOT_EVALUATED")
            item["explanation"] = samsung.get("reason", "")
        values[name] = item

    sanitize = parse_sanitize_log(records.get("nvme-sanitize-log", {}))
    values["sanitize_state"] = {
        "value": sanitize.get("value"),
        "source": "nvme sanitize-log --human-readable",
        "time": records.get("nvme-sanitize-log", {}).get("ended_utc", started_utc),
        "status": sanitize.get("status", "NOT_EVALUATED"),
        "explanation": sanitize.get("reason", ""),
    }
    if isinstance(sanitize.get("value"), dict):
        values["global_data_erased"] = value_record(
            sanitize["value"].get("global_data_erased"), "NVMe Sanitize Status SSTAT bit 8", started_utc,
        )
    else:
        values["global_data_erased"] = value_record(None, "NVMe Sanitize Status SSTAT bit 8", started_utc)

    values["transport"] = value_record(disk.get("transport"), disk.get("transport_source", "lsblk"), started_utc)
    values["controller_path"] = value_record(nvme_ctrl, "derived from namespace path", started_utc)
    return {
        "device_id": device_id,
        "identity": disk,
        "controller_path": nvme_ctrl,
        "values": values,
        "command_status": {
            key: {
                "status": value.get("status"),
                "returncode": value.get("returncode"),
                "started_utc": value.get("started_utc"),
                "ended_utc": value.get("ended_utc"),
            }
            for key, value in records.items()
        },
        "vendor_specific": {
            "samsung_extended_smart": samsung,
            "sanitize_log": sanitize,
            "smartctl_device": smart_device or None,
            "ata_attributes": ata_fields,
            "nvme_controller_unmapped_fields": {
                key: value for key, value in nvme_ctrl_json.items()
                if key not in {"mn", "sn", "fr", "vid", "ssvid", "ver"}
            } or None,
        },
    }


def collect_one_device(disk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path = str(disk["device_path"])
    records: dict[str, dict[str, Any]] = {}
    records["udevadm"] = run_command(["udevadm", "info", "--query=all", "--name", path], timeout=30)
    records["smartctl-text"] = run_command(["smartctl", "-x", path], timeout=100)
    records["smartctl-json"] = run_command(["smartctl", "-x", "-j", path], timeout=100)
    controller = nvme_controller_path(path)
    if controller:
        records["nvme-id-ctrl"] = run_command(["nvme", "id-ctrl", controller, "--output-format=json"], timeout=60)
        records["nvme-id-ns"] = run_command(["nvme", "id-ns", path, "--output-format=json"], timeout=60)
        records["nvme-smart-log"] = run_command(["nvme", "smart-log", path, "--output-format=json"], timeout=60)
        records["nvme-smart-log-human"] = run_command(["nvme", "smart-log", path, "--human-readable"], timeout=60)
        records["nvme-error-log"] = run_command(
            ["nvme", "error-log", controller, "--log-entries=64", "--output-format=json"],
            timeout=60,
        )
        records["nvme-fw-log"] = run_command(["nvme", "fw-log", controller, "--output-format=json"], timeout=60)
        records["nvme-sanitize-log"] = run_command(["nvme", "sanitize-log", controller, "--human-readable"], timeout=60)
        id_ctrl = parse_json_output(records["nvme-id-ctrl"])
        if parse_integer(id_ctrl.get("vid")) == SAMSUNG_VENDOR_ID:
            records["samsung-extended-smart-0xca"] = run_command(
                [
                    "nvme", "get-log", controller,
                    f"--log-id={SAMSUNG_EXTENDED_SMART_LOG_ID}",
                    f"--log-len={SAMSUNG_EXTENDED_SMART_LOG_BYTES}",
                    "--raw-binary",
                ],
                timeout=60,
                binary_stdout=True,
            )
        else:
            records["samsung-extended-smart-0xca"] = empty_record(
                ["nvme", "get-log", controller, "--log-id=0xca"],
                "NOT_EVALUATED",
                "Samsung vendor log page was not queried because PCI vendor ID 0x144D was not established.",
            )
        records.update(collect_persistent_event_log(controller, records["nvme-id-ctrl"]))
    classify_smartctl_optional_selftest(records)
    return records


def collect_post_read_evidence(disk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    path = str(disk["device_path"])
    controller = nvme_controller_path(path)
    records: dict[str, dict[str, Any]] = {
        "post-smartctl-json": run_command(["smartctl", "-x", "-j", path], timeout=100),
    }
    if not controller:
        return records
    records["post-nvme-smart-log"] = run_command(["nvme", "smart-log", path, "--output-format=json"], timeout=60)
    records["post-nvme-error-log"] = run_command(
        ["nvme", "error-log", controller, "--log-entries=64", "--output-format=json"], timeout=60,
    )
    records["post-nvme-sanitize-log"] = run_command(["nvme", "sanitize-log", controller, "--human-readable"], timeout=60)
    identity = run_command(["nvme", "id-ctrl", controller, "--output-format=json"], timeout=60)
    records["post-nvme-id-ctrl"] = identity
    if parse_integer(parse_json_output(identity).get("vid")) == SAMSUNG_VENDOR_ID:
        records["post-samsung-extended-smart-0xca"] = run_command(
            [
                "nvme", "get-log", controller,
                f"--log-id={SAMSUNG_EXTENDED_SMART_LOG_ID}",
                f"--log-len={SAMSUNG_EXTENDED_SMART_LOG_BYTES}",
                "--raw-binary",
            ],
            timeout=60,
            binary_stdout=True,
        )
    return records


def parse_dd_bytes(stderr: str) -> int | None:
    matches = re.findall(r"(?:^|\r|\n)(\d+)\s+bytes\s+.*?copied", stderr, flags=re.I)
    return int(matches[-1]) if matches else None


def run_full_read_scan(disk: dict[str, Any], protected: set[str], protection_failed: bool) -> dict[str, Any]:
    """Read every advertised byte once and discard it; never write to the target."""
    path = str(disk.get("device_path") or "")
    started = utc_now()
    record: dict[str, Any] = {
        "argv": ["dd", f"if={path}", "of=/dev/null", "bs=16M", "iflag=direct", "status=none"],
        "started_utc": started,
        "read_only": True,
        "device_path": path,
        "expected_serial": disk.get("serial"),
        "expected_bytes": disk.get("capacity_bytes"),
    }
    if protection_failed or not path or path in protected:
        return {
            **record,
            "ended_utc": utc_now(),
            "returncode": None,
            "status": "BLOCKED",
            "stdout": "",
            "stderr": "Boot-device protection was unresolved or the selected path is protected.",
            "complete": False,
        }

    current = run_command(
        ["lsblk", "--json", "--bytes", "--paths", "--output", "PATH,TYPE,SIZE,SERIAL", path],
        timeout=30,
    )
    payload = parse_json_output(current)
    current_disks = disks_from_lsblk(payload)
    expected_serial = str(disk.get("serial") or "").strip()
    current_serial = str(current_disks[0].get("serial") or "").strip() if len(current_disks) == 1 else ""
    current_size = parse_integer(current_disks[0].get("size")) if len(current_disks) == 1 else None
    expected_size = parse_integer(disk.get("capacity_bytes"))
    if len(current_disks) != 1 or (expected_serial and current_serial != expected_serial) or current_size != expected_size:
        return {
            **record,
            "ended_utc": utc_now(),
            "returncode": None,
            "status": "BLOCKED",
            "stdout": "",
            "stderr": "Target identity changed or could not be re-established immediately before the read scan.",
            "complete": False,
            "observed_serial": current_serial or None,
            "observed_bytes": current_size,
        }

    timeout_seconds = max(7200, int((expected_size or 0) / (50 * 1024 * 1024)) + 600)
    begin = time.monotonic()
    try:
        proc = subprocess.Popen(
            record["argv"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", env={**os.environ, "LC_ALL": "C"},
        )
        while proc.poll() is None:
            elapsed = int(time.monotonic() - begin)
            print(f"\r  Full read {path}: {elapsed}s elapsed", end="", flush=True)
            if elapsed > timeout_seconds:
                proc.kill()
                stdout, stderr = proc.communicate()
                print()
                return {
                    **record, "ended_utc": utc_now(), "returncode": None,
                    "status": "QUERY_FAILED", "stdout": stdout or "", "stderr": (stderr or "") + "\nFull read timed out.",
                    "elapsed_seconds": time.monotonic() - begin, "complete": False,
                }
            time.sleep(5)
        stdout, stderr = proc.communicate()
        print()
    except OSError as exc:
        return {
            **record, "ended_utc": utc_now(), "returncode": None, "status": "QUERY_FAILED",
            "stdout": "", "stderr": str(exc), "elapsed_seconds": time.monotonic() - begin, "complete": False,
        }

    elapsed = time.monotonic() - begin
    bytes_read = expected_size if proc.returncode == 0 else parse_dd_bytes(stderr or "")
    complete = proc.returncode == 0 and expected_size is not None and bytes_read == expected_size
    return {
        **record,
        "ended_utc": utc_now(),
        "returncode": proc.returncode,
        "status": "OK" if complete else "QUERY_FAILED",
        "stdout": stdout or "",
        "stderr": stderr or "",
        "elapsed_seconds": round(elapsed, 3),
        "bytes_read": bytes_read,
        "complete": complete,
        "throughput_bytes_per_second": round(bytes_read / elapsed, 3) if bytes_read and elapsed else None,
    }


def int_value(values: dict[str, Any], name: str) -> int | float | None:
    item = values.get(name)
    if not isinstance(item, dict) or item.get("status") not in ("0", "VALUE"):
        return None
    value = item.get("value")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", ""))
    except (ValueError, TypeError):
        return None


def smart_counter(payload: dict[str, Any], name: str) -> int | None:
    value = find_value(payload, key_for_disk_value(name))
    parsed = parse_integer(value)
    return parsed


def analyze_read_verification(records: dict[str, dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    scan = records.get("full-capacity-read", {})
    if not scan:
        return {
            "status": "NOT_EVALUATED",
            "complete": False,
            "findings": [{
                "code": "FULL_READ_NOT_EVALUATED", "severity": "INFO", "observed": {},
                "explanation": ["Full-capacity read verification was not selected."],
                "not_established": ["Complete addressability", "Whole-media readability"],
            }],
        }

    expected_bytes = parse_integer(scan.get("expected_bytes"))
    bytes_read = parse_integer(scan.get("bytes_read"))
    pre = {name: int_value(values, name) for name in (
        "data_units_read", "data_units_written", "host_read_commands", "host_write_commands",
        "critical_warning", "media_errors", "num_err_log_entries",
        "nand_erase_cycles_minimum", "nand_erase_cycles_average", "nand_erase_cycles_maximum",
        "vendor_workload_timer_minutes",
    )}
    post_smart = parse_json_output(records.get("post-nvme-smart-log", {}))
    post = {name: smart_counter(post_smart, name) for name in (
        "data_units_read", "data_units_written", "host_read_commands", "host_write_commands",
        "critical_warning", "media_errors", "num_err_log_entries",
    )}
    post_vendor = parse_samsung_extended_smart(records.get("post-samsung-extended-smart-0xca", {}))
    post_vendor_values = post_vendor.get("values", {}) if isinstance(post_vendor, dict) else {}
    for name in (
        "nand_erase_cycles_minimum", "nand_erase_cycles_average", "nand_erase_cycles_maximum",
        "vendor_workload_timer_minutes",
    ):
        post[name] = parse_integer(post_vendor_values.get(name))

    findings: list[dict[str, Any]] = []
    complete = bool(scan.get("complete")) and expected_bytes is not None and bytes_read == expected_bytes
    if not complete:
        findings.append({
            "code": "FULL_READ_INCOMPLETE", "severity": "REVIEW",
            "observed": {"expected_bytes": expected_bytes, "bytes_read": bytes_read, "status": scan.get("status")},
            "explanation": ["The read-only scan did not read the complete advertised namespace."],
            "not_established": ["Whether the cause is media, transport, hot-plug, timeout, or host state"],
        })

    unchanged_fields = (
        "data_units_written", "host_write_commands", "critical_warning", "media_errors",
        "nand_erase_cycles_minimum", "nand_erase_cycles_average", "nand_erase_cycles_maximum",
    )
    changes = {
        name: {"before": pre.get(name), "after": post.get(name)}
        for name in unchanged_fields
        if pre.get(name) is not None and post.get(name) is not None and pre[name] != post[name]
    }
    if changes:
        findings.append({
            "code": "UNEXPECTED_COUNTER_CHANGE_DURING_READ_ONLY_SCAN", "severity": "REVIEW",
            "observed": changes,
            "explanation": ["A counter expected to remain stable changed during a read-only full-capacity scan."],
            "not_established": ["Whether another host/controller activity contributed"],
        })

    read_delta = None
    expected_units = None
    read_counter_coherent = None
    if pre.get("data_units_read") is not None and post.get("data_units_read") is not None:
        read_delta = post["data_units_read"] - pre["data_units_read"]
    if expected_bytes is not None:
        expected_units = (expected_bytes + NVME_DATA_UNIT_BYTES - 1) // NVME_DATA_UNIT_BYTES
    if read_delta is not None and expected_units is not None:
        read_counter_coherent = abs(read_delta - expected_units) <= 8
        if not read_counter_coherent:
            findings.append({
                "code": "READ_COUNTER_DELTA_MISMATCH", "severity": "REVIEW",
                "observed": {"data_units_read_delta": read_delta, "expected_approximate_units": expected_units},
                "explanation": ["The lifetime read-counter delta did not closely match the complete namespace read."],
                "not_established": ["Counter unit/rounding behavior or concurrent reads"],
            })

    status = "VERIFIED" if complete and not any(item["severity"] == "REVIEW" for item in findings) else "REVIEW_REQUIRED"
    return {
        "status": status,
        "complete": complete,
        "expected_bytes": expected_bytes,
        "bytes_read": bytes_read,
        "elapsed_seconds": scan.get("elapsed_seconds"),
        "throughput_bytes_per_second": scan.get("throughput_bytes_per_second"),
        "pre": pre,
        "post": post,
        "data_units_read_delta": read_delta,
        "expected_data_units_read_delta": expected_units,
        "read_counter_coherent": read_counter_coherent,
        "findings": findings,
    }
def analyze_telemetry(
    values: dict[str, Any],
    previous_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    wear = int_value(values, "percentage_used")
    poh = int_value(values, "power_on_hours")
    written = int_value(values, "data_units_written")
    host_writes = int_value(values, "host_write_commands")
    cycles = int_value(values, "power_cycles")
    unsafe = int_value(values, "unsafe_shutdowns")
    vendor_wear = int_value(values, "vendor_media_wear_percent")
    erase_min = int_value(values, "nand_erase_cycles_minimum")
    erase_avg = int_value(values, "nand_erase_cycles_average")
    erase_max = int_value(values, "nand_erase_cycles_maximum")
    workload_minutes = int_value(values, "vendor_workload_timer_minutes")
    global_data_erased = value_value(values, "global_data_erased")

    physical_wear_present = bool(
        (vendor_wear is not None and vendor_wear > 0)
        or (erase_avg is not None and erase_avg >= 10)
        or (wear is not None and wear > 0)
    )
    zero_retained_writes = written == 0 and (host_writes in (0, None))

    if physical_wear_present and zero_retained_writes:
        findings.append({
            "code": "LIFETIME_HISTORY_DISCONTINUITY",
            "severity": "REVIEW",
            "observed": {
                "percentage_used": wear,
                "power_on_hours": poh,
                "data_units_written": written,
                "host_write_commands": host_writes,
                "vendor_media_wear_percent": vendor_wear,
                "nand_erase_cycles_minimum": erase_min,
                "nand_erase_cycles_average": erase_avg,
                "nand_erase_cycles_maximum": erase_max,
                "vendor_workload_timer_minutes": workload_minutes,
            },
            "explanation": EXPLANATION,
            "not_established": ["Fraud", "Counter manipulation", "SMART tampering"],
        })

    if (
        poh == 0 and written == 0 and (host_writes in (0, None))
        and vendor_wear == 0 and erase_avg == 0 and erase_max is not None and erase_max <= 1
        and workload_minutes is not None and workload_minutes < 60 and global_data_erased is True
    ):
        findings.append({
            "code": "COHERENT_NEAR_NEW_TELEMETRY",
            "severity": "OBSERVATION",
            "observed": {
                "power_cycles": cycles, "unsafe_shutdowns": unsafe, "power_on_hours": poh,
                "vendor_workload_timer_minutes": workload_minutes, "data_units_written": written,
                "nand_erase_cycles_minimum": erase_min, "nand_erase_cycles_average": erase_avg,
                "nand_erase_cycles_maximum": erase_max, "global_data_erased": global_data_erased,
            },
            "explanation": ["Independent standard and vendor counters agree with minutes of runtime and minimal factory/provisioning activity."],
            "not_established": ["Commercial chain of custody", "Cryptographic proof of factory-new status"],
        })

    if cycles is not None and cycles > 0 and poh == 0 and workload_minutes is not None and workload_minutes < 60:
        findings.append({
            "code": "POWER_CYCLES_WITH_SUB_HOUR_RUNTIME",
            "severity": "OBSERVATION",
            "observed": {
                "power_cycles": cycles,
                "power_on_hours": poh,
                "vendor_workload_timer_minutes": workload_minutes,
            },
            "explanation": ["Zero whole power-on hours is explained by the higher-resolution vendor timer being below 60 minutes."],
            "not_established": ["Purpose of each power cycle"],
        })

    if unsafe is not None and unsafe > 0 and zero_retained_writes and physical_wear_present:
        findings.append({
            "code": "UNSAFE_SHUTDOWNS_WITH_DISCONTINUOUS_HISTORY", "severity": "REVIEW",
            "observed": {"unsafe_shutdowns": unsafe, "power_on_hours": poh, "data_units_written": written, "nand_erase_cycles_average": erase_avg},
            "explanation": EXPLANATION, "not_established": ["Counter reset cause"],
        })

    if wear == 0 and not physical_wear_present and (
        (poh is not None and poh > 0) or (written is not None and written > 0) or (erase_avg is not None and erase_avg > 0)
    ):
        findings.append({
            "code": "USED_BELOW_ONE_PERCENT_WEAR", "severity": "OBSERVATION",
            "observed": {"percentage_used": wear, "power_on_hours": poh, "data_units_written": written, "nand_erase_cycles_average": erase_avg},
            "explanation": ["NVMe Percentage Used is a whole-percent endurance estimate; zero does not mean unused."],
            "not_established": ["Factory-new status"],
        })

    if wear is not None and vendor_wear is not None and abs(wear - vendor_wear) > 1:
        findings.append({
            "code": "STANDARD_VENDOR_WEAR_MISMATCH", "severity": "REVIEW",
            "observed": {"percentage_used": wear, "vendor_media_wear_percent": vendor_wear},
            "explanation": ["Standard NVMe and Samsung vendor wear estimates disagree beyond a one-percent rounding allowance."],
            "not_established": ["Which estimate is authoritative"],
        })

    if poh is not None and workload_minutes is not None and abs(poh - (workload_minutes // 60)) > 1:
        findings.append({
            "code": "POWER_ON_TIME_DOMAIN_MISMATCH", "severity": "REVIEW",
            "observed": {"power_on_hours": poh, "vendor_workload_timer_minutes": workload_minutes},
            "explanation": ["Whole-hour and vendor-minute runtime counters do not describe compatible elapsed time domains."],
            "not_established": ["Whether power-state accounting or a reset caused the difference"],
        })

    if global_data_erased is True and physical_wear_present:
        findings.append({
            "code": "BLANK_STATE_VS_MEDIA_WEAR_CONFLICT", "severity": "REVIEW",
            "observed": {"global_data_erased": True, "percentage_used": wear, "vendor_media_wear_percent": vendor_wear, "nand_erase_cycles_average": erase_avg},
            "explanation": ["The namespace blank-state assertion and preserved physical NAND wear do not share an ordinary continuous new-device history."],
            "not_established": ["Service/refurbishment mechanism", "Actor", "Date"],
        })

    old = previous_runs or []
    current_fw = value_value(values, "firmware")
    current_counters = {key: int_value(values, key) for key in NVME_COUNTERS}
    for prior in old:
        prior_values = prior.get("values") if isinstance(prior, dict) else None
        if not isinstance(prior_values, dict):
            continue
        prior_fw = value_value(prior_values, "firmware")
        if current_fw and prior_fw and current_fw != prior_fw:
            findings.append({
                "code": "FIRMWARE_CHANGED",
                "severity": "OBSERVATION",
                "observed": {"previous": prior_fw, "current": current_fw},
                "explanation": ["Firmware changed between preserved runs; this alone does not establish a defect."],
                "not_established": ["Whether the change was expected or authorized"],
            })
        prior_serial = value_value(prior_values, "serial")
        current_serial = value_value(values, "serial")
        prior_model = value_value(prior_values, "model")
        current_model = value_value(values, "model")
        if prior_serial and current_serial and prior_serial == current_serial and prior_model and current_model and prior_model != current_model:
            findings.append({
                "code": "SERIAL_HISTORY_CONFLICT",
                "severity": "REVIEW",
                "observed": {"serial": current_serial, "previous_model": prior_model, "current_model": current_model},
                "explanation": ["The same serial is associated with different model strings in preserved runs."],
                "not_established": ["Which model string is authoritative"],
            })
        prior_vals = {key: int_value(prior_values, key) for key in NVME_COUNTERS}
        regressions = {
            key: {"previous": before, "current": current_counters.get(key)}
            for key, before in prior_vals.items()
            if before is not None
            and current_counters.get(key) is not None
            and current_counters[key] < before
        }
        if regressions:
            findings.append({
                "code": "COUNTER_REGRESSION",
                "severity": "REVIEW",
                "observed": regressions,
                "explanation": EXPLANATION,
                "not_established": ["Counter manipulation"],
            })
        old_wear = prior_vals.get("percentage_used")
        old_written = prior_vals.get("data_units_written")
        old_poh = prior_vals.get("power_on_hours")
        if (
            old_wear is not None and wear is not None and wear > old_wear
            and old_written is not None and written == old_written
            and old_poh is not None and poh == old_poh
        ):
            findings.append({
                "code": "WEAR_WITHOUT_COUNTER_CONTINUITY",
                "severity": "REVIEW",
                "observed": {
                    "previous_percentage_used": old_wear,
                    "current_percentage_used": wear,
                    "previous_data_units_written": old_written,
                    "current_data_units_written": written,
                    "previous_power_on_hours": old_poh,
                    "current_power_on_hours": poh,
                },
                "explanation": EXPLANATION,
                "not_established": ["Why the counters diverged"],
            })

    unique: dict[str, dict[str, Any]] = {}
    for finding in findings:
        key = finding["code"] + json.dumps(finding.get("observed", {}), sort_keys=True, default=str)
        unique[key] = finding
    return {
        "disposition": "REVIEW_REQUIRED" if any(item["severity"] == "REVIEW" for item in unique.values()) else "CONSISTENT",
        "findings": list(unique.values()),
        "interpretation": "Observed counter combinations are evidence for review, not proof of fraud or tampering.",
    }


def value_value(values: dict[str, Any], name: str) -> Any:
    item = values.get(name)
    return item.get("value") if isinstance(item, dict) else None


def previous_results(serial_component: str, serial: str | None, current_run_id: str) -> list[dict[str, Any]]:
    if not serial:
        return []
    root = Path(os.environ.get("HDT_RESULT_ROOT", str(DEFAULT_RESULT_ROOT)))
    pattern = f"*/{serial_component}/RUN-*/normalized/result.json"
    matches = sorted(root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    output: list[dict[str, Any]] = []
    for path in matches:
        if path.parent.parent.name == current_run_id:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("target", {}).get("serial") == serial:
            output.append(record)
        if len(output) >= 10:
            break
    return output


def cross_drive_findings(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[str]] = {}
    for item in devices:
        values = item.get("values", {})
        signature = {
            key: int_value(values, key)
            for key in (
                "percentage_used", "vendor_media_wear_percent", "nand_erase_cycles_average",
                "power_cycles", "unsafe_shutdowns", "power_on_hours", "data_units_written",
            )
        }
        if all(value is not None for value in signature.values()):
            groups.setdefault(json.dumps(signature, sort_keys=True), []).append(str(item.get("target", {}).get("device_path")))
    findings = []
    for signature, paths in groups.items():
        if len(paths) >= 3:
            findings.append({
                "code": "COMMON_TELEMETRY_STATE",
                "severity": "REVIEW",
                "observed": {"device_paths": paths, "shared_counters": json.loads(signature)},
                "explanation": ["Multiple drives report an identical lifetime-counter pattern; this is an observation requiring context."],
                "not_established": ["Common manufacture date", "Refurbishment batch", "Counter manipulation"],
            })
    return findings


def health_assessment(result: dict[str, Any]) -> dict[str, Any]:
    values = result["values"]
    findings = list(result["analysis"]["findings"])
    smart = value_value(values, "smart_health")
    critical_warning = int_value(values, "critical_warning")
    if smart == "FAILED":
        findings.append({
            "code": "SMART_HEALTH_FAILURE_REPORTED",
            "severity": "REVIEW",
            "observed": {"smart_health": smart},
            "explanation": ["The device's own SMART status reported failure."],
            "not_established": ["Physical root cause"],
        })
    if critical_warning is not None and critical_warning != 0:
        findings.append({
            "code": "NVME_CRITICAL_WARNING",
            "severity": "REVIEW",
            "observed": {"critical_warning": critical_warning},
            "explanation": ["NVMe Critical Warning is non-zero; decode the individual warning bits in raw output."],
            "not_established": ["Specific component failure without decoding the bits"],
        })

    has_identity = bool(value_value(values, "model") and value_value(values, "serial"))
    has_health = smart is not None or critical_warning is not None
    nvme = result["target"].get("transport") == "NATIVE_NVME"
    if nvme:
        required_counters = ("percentage_used", "power_on_hours", "data_units_written", "power_cycles")
        enough_counters = all(int_value(values, name) is not None for name in required_counters)
    else:
        enough_counters = int_value(values, "power_on_hours") is not None or int_value(values, "media_errors") is not None
    read_status = result.get("read_verification", {}).get("status", "NOT_EVALUATED")
    if any(item.get("severity") == "REVIEW" for item in findings):
        disposition = "REVIEW_REQUIRED"
    elif has_identity and has_health and enough_counters and read_status == "VERIFIED":
        disposition = "CONSISTENT"
    else:
        disposition = "INSUFFICIENT_EVIDENCE"
    result["analysis"]["findings"] = findings
    result["analysis"]["disposition"] = disposition
    return result["analysis"]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def render_markdown(record: dict[str, Any]) -> str:
    target = record.get("target", {})
    values = record.get("values", {})
    analysis = record.get("analysis", {})
    read = record.get("read_verification", {})

    def shown(name: str) -> Any:
        value = value_value(values, name)
        return "UNAVAILABLE" if value is None else value

    lines = [
        f"# {PROJECT_NAME} SSD/NVMe Evidence Report",
        "",
        f"**Disposition:** `{analysis.get('disposition', 'INSUFFICIENT_EVIDENCE')}`  ",
        f"**Run:** `{record.get('run_id')}`  ",
        f"**PO / Batch:** `{record.get('po_batch')}`  ",
        f"**Collected:** `{record.get('completed_utc')}`",
        "",
        "## Identity",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Device | `{target.get('device_path')}` |",
        f"| Manufacturer | {shown('manufacturer')} |",
        f"| Model | `{shown('model')}` |",
        f"| Serial | `{shown('serial')}` |",
        f"| Firmware | `{shown('firmware')}` |",
        f"| Capacity | {shown('capacity_bytes')} bytes |",
        f"| Transport | {target.get('transport')} |",
        "",
        "## Lifetime and physical-media consistency",
        "",
        "| Evidence | Value |",
        "|---|---:|",
        f"| Standard Percentage Used | {shown('percentage_used')}% |",
        f"| Samsung Media Wear | {shown('vendor_media_wear_percent')}% |",
        f"| Power-on Hours | {shown('power_on_hours')} |",
        f"| Samsung Workload Timer | {shown('vendor_workload_timer_minutes')} min |",
        f"| Data Units Read | {shown('data_units_read')} |",
        f"| Data Units Written | {shown('data_units_written')} |",
        f"| Host Read Commands | {shown('host_read_commands')} |",
        f"| Host Write Commands | {shown('host_write_commands')} |",
        f"| Power Cycles | {shown('power_cycles')} |",
        f"| Unsafe Shutdowns | {shown('unsafe_shutdowns')} |",
        f"| NAND Erase Cycles min/avg/max | {shown('nand_erase_cycles_minimum')} / {shown('nand_erase_cycles_average')} / {shown('nand_erase_cycles_maximum')} |",
        f"| Global Data Erased | {shown('global_data_erased')} |",
        f"| Media Errors | {shown('media_errors')} |",
        f"| NVMe Error Entries | {shown('num_err_log_entries')} |",
        "",
        "## Full-capacity read verification",
        "",
        "| Field | Result |",
        "|---|---|",
        f"| Status | `{read.get('status', 'NOT_EVALUATED')}` |",
        f"| Bytes expected | {read.get('expected_bytes', 'NOT_EVALUATED')} |",
        f"| Bytes read | {read.get('bytes_read', 'NOT_EVALUATED')} |",
        f"| Elapsed | {read.get('elapsed_seconds', 'NOT_EVALUATED')} seconds |",
        f"| Throughput | {read.get('throughput_bytes_per_second', 'NOT_EVALUATED')} B/s |",
        f"| Read-counter delta | {read.get('data_units_read_delta', 'NOT_EVALUATED')} |",
        f"| Expected approximate delta | {read.get('expected_data_units_read_delta', 'NOT_EVALUATED')} |",
        f"| Counter coherence | {read.get('read_counter_coherent', 'NOT_EVALUATED')} |",
        "",
        "## Findings",
        "",
    ]
    findings = analysis.get("findings", [])
    if not findings:
        lines.append("No consistency rule triggered. This does not prove future reliability.")
    for finding in findings:
        lines.extend([
            f"### {finding.get('code')} ({finding.get('severity')})",
            "",
            "**Observed fact**",
            "",
            "```json",
            json.dumps(finding.get("observed", {}), indent=2, ensure_ascii=False, default=str),
            "```",
            "",
            "**Possible explanations:** " + "; ".join(finding.get("explanation", [])),
            "",
            "**Not established:** " + "; ".join(finding.get("not_established", [])),
            "",
        ])
    lines.extend([
        "## Final assessment",
        "",
        f"`{analysis.get('disposition', 'INSUFFICIENT_EVIDENCE')}`",
        "",
        "This is a read-only evidence assessment. It does not by itself prove commercial chain of custody, factory-new status, absence of firmware tampering, or future reliability.",
        "",
    ])
    return "\n".join(str(item) for item in lines)


def render_html(record: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value if value is not None else "UNAVAILABLE"))

    target = record.get("target", {})
    values = record.get("values", {})
    protection = record.get("boot_protection", {})
    inventory = record.get("inventory", {})
    sections: list[str] = []
    categories = {
        "IDENTITY": ("manufacturer", "model", "serial", "firmware", "capacity_bytes", "nvme_version", "namespace_id", "namespace_nguid", "namespace_eui64", "pci_ids"),
        "TRANSPORT / OBSERVABILITY": ("device_path", "transport", "controller_path"),
        "HEALTH": ("smart_health", "critical_warning", "available_spare", "available_spare_threshold", "percentage_used"),
        "LIFETIME COUNTERS": ("data_units_read", "data_units_written", "host_read_commands", "host_write_commands", "controller_busy_time", "power_cycles", "power_on_hours", "unsafe_shutdowns"),
        "SAMSUNG PHYSICAL-MEDIA COUNTERS": ("vendor_media_wear_percent", "wear_level_normalized", "nand_erase_cycles_minimum", "nand_erase_cycles_average", "nand_erase_cycles_maximum", "vendor_workload_timer_minutes", "physical_nand_writes_raw", "lifetime_data_units_written_raw", "program_fail_count", "erase_fail_count", "end_to_end_error_count", "crc_error_count"),
        "BLANK / SANITIZE STATE": ("sanitize_state", "global_data_erased"),
        "ERROR HISTORY": ("media_errors", "num_err_log_entries", "error_log", "persistent_event_log"),
        "FIRMWARE": ("firmware", "firmware_slot_information"),
        "TEMPERATURE": ("temperature", "temperature_sensor_1", "temperature_sensor_2", "temperature_sensor_3"),
    }
    for title, names in categories.items():
        rows = []
        for name in names:
            if name not in values:
                continue
            item = values[name]
            value = item.get("value") if isinstance(item, dict) else item
            status = item.get("status", "UNAVAILABLE") if isinstance(item, dict) else "UNAVAILABLE"
            source = item.get("source", "") if isinstance(item, dict) else ""
            time_value = item.get("time", "") if isinstance(item, dict) else ""
            unit = item.get("unit", "") if isinstance(item, dict) else ""
            rows.append(
                f"<tr><th>{esc(name)}</th><td>{esc(value)}</td><td>{esc(status)}</td>"
                f"<td>{esc(source)}</td><td>{esc(unit)}</td><td>{esc(time_value)}</td></tr>"
            )
        sections.append(
            f"<section><h2>{esc(title)}</h2><table><thead><tr><th>Field</th><th>Value</th>"
            f"<th>Status</th><th>Source</th><th>Unit</th><th>Observed</th></tr></thead>"
            f"<tbody>{''.join(rows) or '<tr><td colspan=6>NOT_EVALUATED</td></tr>'}</tbody></table></section>"
        )
    findings = record.get("analysis", {}).get("findings", [])
    finding_rows = []
    for item in findings:
        finding_rows.append(
            f"<li><b>{esc(item.get('code'))}</b> ({esc(item.get('severity'))})"
            f"<pre>{esc(json.dumps(item.get('observed'), indent=2, ensure_ascii=False))}</pre>"
            f"<p>Possible explanations: {esc('; '.join(item.get('explanation', [])))}"
            f"<br>Not established: {esc('; '.join(item.get('not_established', [])))}</p></li>"
        )
    if not finding_rows:
        finding_rows.append("<li>No consistency rule triggered; this does not prove future reliability.</li>")
    warnings = record.get("warnings", [])
    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{PROJECT_NAME} Evidence {esc(record.get('run_id'))}</title>
<style>
body{{font:15px/1.5 system-ui,Segoe UI,sans-serif;margin:2rem;color:#17212b;background:#f5f7fa}}
main{{max-width:1200px;margin:auto;background:white;padding:2rem;border-radius:10px}}
h1,h2{{color:#11385b}}table{{border-collapse:collapse;width:100%;font-size:13px;margin:.7rem 0 1.5rem}}
th,td{{border:1px solid #d9e1ea;padding:.45rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}}
th{{background:#edf3f8}}.status{{font-weight:700;padding:.3rem .6rem;background:#fff2cc}}
pre{{white-space:pre-wrap;background:#f4f6f8;padding:.7rem}}.notice{{background:#fff7e6;padding:.7rem}}
</style></head><body><main>
<h1>{PROJECT_NAME} — SSD / NVMe Evidence Report</h1>
<p><b>{PROJECT_TAGLINE}</b> | Workflow v{VERSION}</p>
<p><b>Disposition:</b> <span class="status">{esc(record.get('analysis', {}).get('disposition'))}</span></p>
<p><b>Run:</b> {esc(record.get('run_id'))} | <b>Batch:</b> {esc(record.get('po_batch'))}</p>
<p><b>Device:</b> {esc(target.get('device_path', 'NO_TARGET'))} | {esc(target.get('model'))} | {esc(target.get('serial'))}</p>
<p><b>Condition:</b> {esc(record.get('expected_condition'))} | <b>Collected:</b> {esc(record.get('completed_utc'))}</p>
<p class="notice">Read-only collection. A consistent snapshot is not a reliability qualification. Raw command output is preserved in this run folder.</p>
{''.join(sections)}
<section><h2>FULL-CAPACITY READ VERIFICATION</h2>
<pre>{esc(json.dumps(record.get('read_verification', {'status': 'NOT_EVALUATED'}), indent=2, ensure_ascii=False))}</pre></section>
<section><h2>BOOT DISK PROTECTION</h2>
<p>State: {esc('FAIL_CLOSED' if protection.get('fail_closed') else 'RESOLVED')}</p>
<p>Protected physical disks: {esc(', '.join(protection.get('protected_disks', [])) or 'UNAVAILABLE')}</p>
<p>Mount sources: {esc(json.dumps(protection.get('mount_sources', {}), sort_keys=True))}</p>
<p>Inventory: {esc(json.dumps(inventory, sort_keys=True))}</p></section>
<section><h2>TELEMETRY CONSISTENCY</h2><p>{esc(record.get('analysis', {}).get('interpretation'))}</p><ul>{''.join(finding_rows)}</ul></section>
<section><h2>LIMITATIONS</h2><ul>{''.join(f'<li>{esc(item)}</li>' for item in warnings) or '<li>See raw command records for tool-specific limitations.</li>'}</ul></section>
<section><h2>FINAL DISPOSITION</h2><p>{esc(record.get('analysis', {}).get('disposition'))}</p>
<p>Export state: {esc(record.get('export', {}).get('status'))}</p></section>
</main></body></html>"""
    return html_doc


def write_report_files(run_dir: Path, record: dict[str, Any]) -> None:
    reports = run_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "report.html").write_text(render_html(record), encoding="utf-8")
    (reports / "report.md").write_text(render_markdown(record), encoding="utf-8")


def finalize_hashes(run_dir: Path, record: dict[str, Any]) -> None:
    files: list[dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected symlink in evidence bundle: {path}")
        if path.is_file() and path.name not in ("manifest.json", "checksums.sha256"):
            data = path.read_bytes()
            import hashlib

            files.append({
                "path": path.relative_to(run_dir).as_posix(),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
    manifest = {
        "artifact_type": "CNDRIVETRUST_SSD_NVME_EVIDENCE",
        "schema_version": "2.0",
        "project": PROJECT_NAME,
        "workflow_version": VERSION,
        "run_id": record.get("run_id"),
        "po_batch": record.get("po_batch"),
        "target_serial": record.get("target", {}).get("serial"),
        "built_utc": utc_now(),
        "immutable_after_finalization": True,
        "files": files,
    }
    write_json(run_dir / "manifest.json", manifest)
    import hashlib

    sums = []
    for item in files:
        sums.append(f"{item['sha256']}  {item['path']}")
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    sums.append(f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json")
    (run_dir / "checksums.sha256").write_text("\n".join(sums) + "\n", encoding="utf-8")


def write_bundle(run_dir: Path, record: dict[str, Any], global_records: dict[str, dict[str, Any]], device_records: dict[str, dict[str, Any]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=False)
    for key, value in global_records.items():
        save_raw_record(run_dir, "global", key, value)
    for key, value in device_records.items():
        save_raw_record(run_dir, "device", key, value)
    write_json(run_dir / "normalized" / "result.json", record)
    write_report_files(run_dir, record)
    finalize_hashes(run_dir, record)


def load_export_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        export = data.get("export", {})
        return export if isinstance(export, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def mounted_cifs(destination: Path) -> tuple[bool, str]:
    if not destination.is_absolute() or not destination.exists() or not destination.is_dir():
        return False, "Configured export destination is missing or is not a directory."
    fs = run_command(["findmnt", "--noheadings", "--raw", "--output", "FSTYPE", "--target", str(destination)], timeout=10)
    if fs.get("returncode") != 0 or fs.get("stdout", "").strip() != "cifs":
        return False, "Destination is not on a mounted CIFS filesystem."
    return True, ""


def export_bundle(run_dir: Path, record: dict[str, Any], config_path: Path = DEFAULT_CONFIG) -> None:
    export_cfg = load_export_config(config_path)
    destination_text = str(export_cfg.get("destination") or "").strip()
    if not destination_text:
        record["export"] = {"status": "PENDING_EXPORT", "reason": "Windows destination is not configured."}
        write_json(run_dir / "normalized" / "result.json", record)
        write_report_files(run_dir, record)
        finalize_hashes(run_dir, record)
        return

    destination = Path(destination_text)
    mounted, reason = mounted_cifs(destination)
    if not mounted:
        record["export"] = {"status": "PENDING_EXPORT", "reason": reason, "destination": destination_text}
        write_json(run_dir / "normalized" / "result.json", record)
        write_report_files(run_dir, record)
        finalize_hashes(run_dir, record)
        return

    po = safe_component(record.get("po_batch"), "UNKNOWN_BATCH")
    serial = safe_component(record.get("target", {}).get("serial"), "UNKNOWN_SERIAL")
    run_id = safe_component(record.get("run_id"), "UNKNOWN_RUN")
    final_dest = destination / po / serial / run_id
    if final_dest.exists():
        record["export"] = {
            "status": "PENDING_EXPORT",
            "reason": "Destination already contains this run ID; existing evidence was preserved.",
            "destination": str(final_dest),
        }
        write_json(run_dir / "normalized" / "result.json", record)
        write_report_files(run_dir, record)
        finalize_hashes(run_dir, record)
        return

    staging = final_dest.parent / f".{run_id}.staging-{uuid.uuid4().hex[:10]}"
    try:
        final_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, staging)
        record["export"] = {
            "status": "EXPORTED",
            "destination": str(final_dest),
            "exported_utc": utc_now(),
        }
        write_json(run_dir / "normalized" / "result.json", record)
        write_report_files(run_dir, record)
        finalize_hashes(run_dir, record)
        for relative in ("normalized/result.json", "reports/report.html", "reports/report.md", "manifest.json", "checksums.sha256"):
            shutil.copy2(run_dir / relative, staging / relative)
        if final_dest.exists():
            raise FileExistsError("Destination appeared during export; preserving existing data.")
        staging.rename(final_dest)
    except Exception as exc:
        if staging.exists() and staging.parent == final_dest.parent:
            shutil.rmtree(staging, ignore_errors=True)
        record["export"] = {
            "status": "PENDING_EXPORT",
            "reason": f"Export did not complete: {type(exc).__name__}",
            "destination": str(final_dest),
        }
        write_json(run_dir / "normalized" / "result.json", record)
        write_report_files(run_dir, record)
        finalize_hashes(run_dir, record)


def freeze_bundle(run_dir: Path) -> None:
    for path in run_dir.rglob("*"):
        if path.is_file():
            path.chmod(0o440)
    for path in sorted((item for item in run_dir.rglob("*") if item.is_dir()), reverse=True):
        path.chmod(0o550)
    run_dir.chmod(0o550)


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    return value or (default or "")


def display_disks(disks: list[dict[str, Any]], protected: set[str], fail_closed: bool) -> list[dict[str, Any]]:
    displayed: list[dict[str, Any]] = []
    print("\nDetected physical disks:")
    if not disks:
        print("  No physical disks were returned by lsblk.")
    for index, raw in enumerate(disks, 1):
        label = device_label(raw)
        path = label["device_path"]
        blocked = path in protected or fail_closed
        label["protected"] = blocked
        label["eligible"] = not blocked and bool(label.get("capacity_bytes"))
        label["selection_number"] = index
        state = "BOOT / PROTECTED" if path in protected else ("BLOCKED / PROTECTION UNRESOLVED" if fail_closed else ("ELIGIBLE" if label["eligible"] else "NO MEDIA / NOT ELIGIBLE"))
        print(
            f"  {index}. {label.get('model') or 'model unavailable'} | {label.get('serial') or 'serial unavailable'} | "
            f"{label.get('capacity_bytes') or 0} bytes | {label.get('transport')} | {path} | {state}"
        )
        displayed.append(label)
    return displayed


def choose_devices(displayed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [item for item in displayed if item.get("eligible")]
    if not eligible:
        print("\nNo eligible test drive is attached. The boot disk will not be tested.")
        return []
    print("\nChoose a drive number, comma-separated numbers, A for all eligible, or Q to cancel.")
    choice = prompt("Drive selection", "Q").strip().lower()
    if choice == "a":
        return eligible
    if choice == "q":
        return []
    wanted: set[int] = set()
    try:
        wanted = {int(token.strip()) for token in choice.split(",") if token.strip()}
    except ValueError:
        print("Invalid selection; no drive was tested.")
        return []
    by_number = {item["selection_number"]: item for item in eligible}
    if not wanted or any(number not in by_number for number in wanted):
        print("Selection included a protected, missing, or invalid disk; no drive was tested.")
        return []
    return [by_number[number] for number in sorted(wanted)]


def derive_manufacturer(model: Any, nvme_ctrl: dict[str, Any], smart_json: dict[str, Any]) -> Any:
    value = find_value(smart_json, ("vendor", "model_family"))
    if value:
        return value
    vendor_id = parse_integer(nvme_ctrl.get("vid"))
    return NVME_VENDOR_NAMES.get(vendor_id)


def selected_device_record(
    label: dict[str, Any],
    records: dict[str, dict[str, Any]],
    run_id: str,
    po_batch: str,
    condition: str,
    notes: str,
    collection_host: dict[str, Any],
    global_records: dict[str, dict[str, Any]],
    common_findings: list[dict[str, Any]],
    protection: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    record_id = safe_component(label.get("serial") or Path(label["device_path"]).name)
    normalized = normalize_device(label, records, record_id, utc_now())
    values = normalized["values"]
    nvme_json = parse_json_output(records.get("nvme-id-ctrl", {}))
    smart_json = parse_json_output(records.get("smartctl-json", {}))
    if value_value(values, "manufacturer") in (None, "", "UNAVAILABLE"):
        values["manufacturer"] = value_record(
            derive_manufacturer(value_value(values, "model"), nvme_json, smart_json),
            "smartctl/NVMe controller metadata",
        )
    analysis = analyze_telemetry(values, previous_results(record_id, label.get("serial"), run_id))
    analysis["findings"].extend(common_findings)
    read_verification = analyze_read_verification(records, values)
    analysis["findings"].extend(read_verification.get("findings", []))
    result = {
        "schema_version": "2.0",
        "workflow_version": VERSION,
        "project": PROJECT_NAME,
        "artifact_type": "CNDRIVETRUST_SSD_NVME_EVIDENCE",
        "run_id": run_id,
        "started_utc": collection_host["started_utc"],
        "completed_utc": utc_now(),
        "po_batch": po_batch,
        "expected_condition": condition,
        "notes": notes,
        "collection_host": collection_host,
        "boot_protection": protection,
        "inventory": inventory,
        "target": {
            **label,
            "manufacturer": value_value(values, "manufacturer"),
            "model": value_value(values, "model") or label.get("model"),
            "serial": value_value(values, "serial") or label.get("serial"),
            "firmware": value_value(values, "firmware"),
        },
        "values": values,
        "command_status": normalized["command_status"],
        "vendor_specific": normalized["vendor_specific"],
        "read_verification": read_verification,
        "analysis": analysis,
        "export": {"status": "PENDING_EXPORT", "reason": "Export is evaluated at finalization."},
        "warnings": [
            "Read-only collection only; no write, format, sanitize, firmware, or endurance operation is performed.",
            "A single snapshot cannot establish the age, provenance, or future reliability of a drive.",
            "Tool-reported lifetime counter semantics vary by controller and firmware.",
        ],
    }
    health_assessment(result)
    return result


def collect_host_identity() -> dict[str, Any]:
    result: dict[str, Any] = {"hostname": os.uname().nodename, "platform": "Linux"}
    for key, args in {
        "system_product": ["sudo", "-n", "dmidecode", "-s", "system-product-name"],
        "bios_version": ["sudo", "-n", "dmidecode", "-s", "bios-version"],
    }.items():
        item = run_command(args, timeout=20)
        value = item.get("stdout", "").strip()
        result[key] = {"value": value or None, "status": "VALUE" if item.get("returncode") == 0 and value else item.get("status")}
    return result


def create_empty_run(
    po_batch: str,
    condition: str,
    notes: str,
    run_id: str,
    global_records: dict[str, dict[str, Any]],
    inventory: dict[str, Any],
    protection: dict[str, Any],
    host: dict[str, Any],
    destination_root: Path,
) -> Path:
    run_dir = destination_root / safe_component(po_batch, "UNKNOWN_BATCH") / "NO_ELIGIBLE_DRIVES" / run_id
    record = {
        "schema_version": "2.0",
        "workflow_version": VERSION,
        "project": PROJECT_NAME,
        "artifact_type": "CNDRIVETRUST_SSD_NVME_EVIDENCE",
        "run_id": run_id,
        "started_utc": host["started_utc"],
        "completed_utc": utc_now(),
        "po_batch": po_batch,
        "expected_condition": condition,
        "notes": notes,
        "collection_host": host,
        "boot_protection": protection,
        "inventory": inventory,
        "targets": [],
        "analysis": {
            "disposition": "INSUFFICIENT_EVIDENCE",
            "findings": [{
                "code": "NO_ELIGIBLE_DRIVE",
                "severity": "INFO",
                "observed": {
                    "physical_disks": len(inventory.get("physical_disks", [])),
                    "protected_disks": protection.get("protected_disks", []),
                    "fail_closed": protection.get("fail_closed"),
                },
                "explanation": ["No non-boot physical SSD/NVMe was available for this run."],
                "not_established": ["Any health property of the runner disk or a future target drive"],
            }],
            "interpretation": "No drive was tested. The protected runner device was excluded.",
        },
        "export": {"status": "PENDING_EXPORT", "reason": "Windows destination is not configured or no target drive was selected."},
        "warnings": [
            "No eligible external test drive was attached.",
            "Read-only collection only; no test command was sent to the boot disk.",
        ],
    }
    run_dir.mkdir(parents=True, exist_ok=False)
    for key, value in global_records.items():
        save_raw_record(run_dir, "global", key, value)
    write_json(run_dir / "raw" / "global" / "boot-protection.json", protection)
    write_json(run_dir / "raw" / "global" / "inventory.json", inventory)
    write_json(run_dir / "normalized" / "result.json", record)
    write_report_files(run_dir, record)
    finalize_hashes(run_dir, record)
    export_bundle(run_dir, record)
    freeze_bundle(run_dir)
    return run_dir


def run_workflow() -> int:
    if not sys.stdin.isatty():
        print("ERROR: technician interaction requires a terminal; no test was started.")
        return 2

    print(f"\n{PROJECT_NAME} v{VERSION} - {PROJECT_TAGLINE}")
    print("READ-ONLY: no format, sanitize, firmware update, or target write is performed.")
    po_batch = prompt("PO / Batch ID")
    if not po_batch:
        print("A PO / Batch ID is required; no collection was started.")
        return 2
    condition = prompt("Expected condition: NEW / USED / UNKNOWN", "UNKNOWN").upper()
    if condition not in ("NEW", "USED", "UNKNOWN"):
        print("Invalid condition; use NEW, USED, or UNKNOWN.")
        return 2
    notes = prompt("Notes (optional)", "")
    full_read_choice = prompt("Run full-capacity read verification? YES / NO", "YES").upper()
    if full_read_choice not in ("YES", "NO"):
        print("Invalid full-read selection; use YES or NO.")
        return 2
    run_id = f"RUN-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12].upper()}"
    started = utc_now()
    collection_host = {"started_utc": started, **collect_host_identity()}
    global_records, block_data, protection_list = capture_global_evidence()
    protection = protection_list[0]
    raw_disks = block_data.get("blockdevices", [])
    protected = set(protection.get("protected_disks", []))
    fail_closed = bool(protection.get("fail_closed"))
    displayed = display_disks(raw_disks, protected, fail_closed)
    eligible = choose_devices(displayed)
    inventory = {
        "physical_disks": displayed,
        "eligible_device_paths": [item["device_path"] for item in displayed if item.get("eligible")],
    }
    destination_root = Path(os.environ.get("HDT_RESULT_ROOT", str(DEFAULT_RESULT_ROOT)))
    if not eligible:
        run_dir = create_empty_run(
            po_batch, condition, notes, run_id, global_records,
            inventory, protection, collection_host, destination_root,
        )
        print(f"\nNo target drive was tested. Evidence: {run_dir}")
        print("Disposition: INSUFFICIENT_EVIDENCE | Export: PENDING_EXPORT")
        return 0

    print("\nCollecting read-only evidence. Do not disconnect a selected drive.")
    collected: list[tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]] = []
    for label in eligible:
        per_device = collect_one_device(label)
        if full_read_choice == "YES":
            print(f"\nStarting full-capacity READ-ONLY verification for {label.get('serial') or label['device_path']}.")
            per_device["full-capacity-read"] = run_full_read_scan(label, protected, fail_closed)
            per_device.update(collect_post_read_evidence(label))
        normalized = normalize_device(label, per_device, safe_component(label.get("serial") or label["device_path"]), utc_now())
        record = {
            "target": label,
            "values": normalized["values"],
            "command_status": normalized["command_status"],
            "vendor_specific": normalized["vendor_specific"],
        }
        collected.append((label, per_device, record))

    common_findings = cross_drive_findings([item[2] for item in collected])
    run_dirs: list[Path] = []
    serial_counts: dict[str, int] = {}
    for label, _, _ in collected:
        serial_counts[safe_component(label.get("serial"), "UNKNOWN_SERIAL")] = (
            serial_counts.get(safe_component(label.get("serial"), "UNKNOWN_SERIAL"), 0) + 1
        )
    for index, (label, per_device, _) in enumerate(collected, 1):
        serial = label.get("serial")
        serial_component = safe_component(serial, "UNKNOWN_" + safe_component(Path(label["device_path"]).name))
        if serial_counts.get(serial_component, 0) > 1:
            serial_component += "__" + safe_component(Path(label["device_path"]).name)
        result = selected_device_record(
            label, per_device, run_id, po_batch, condition, notes,
            collection_host, global_records, common_findings, protection, inventory,
        )
        result_dir = destination_root / safe_component(po_batch, "UNKNOWN_BATCH") / serial_component / run_id
        result["device_run_index"] = index
        result["target"]["serial_directory"] = serial_component
        write_bundle(result_dir, result, global_records, per_device)
        export_bundle(result_dir, result)
        freeze_bundle(result_dir)
        try:
            from cndrivetrust.central.sync import enqueue_finalized
            sync = enqueue_finalized(
                result_dir,
                kind="Test-Disk",
                serial=serial_component,
                batch_id=safe_component(po_batch, "UNASSIGNED"),
            )
            print(f"Central: {sync.get('state', 'SYNC_PENDING')}")
        except Exception as exc:
            print(f"Central: SYNC_PENDING ({type(exc).__name__}); local evidence remains complete.")
        run_dirs.append(result_dir)
        print(f"{result['target'].get('device_path')}: {result['analysis']['disposition']} | {result_dir}")
    return 0


def preflight() -> int:
    global_records, block_data, protection_list = capture_global_evidence()
    protection = protection_list[0]
    displayed = display_disks(
        block_data.get("blockdevices", []),
        set(protection.get("protected_disks", [])),
        bool(protection.get("fail_closed")),
    )
    print(json.dumps({"version": VERSION, "protection": protection, "devices": displayed}, indent=2))
    if protection.get("fail_closed"):
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--preflight", action="store_true", help="Read-only inventory and boot-protection check; no report is written.")
    args = parser.parse_args(argv)
    if args.preflight:
        return preflight()
    return run_workflow()


if __name__ == "__main__":
    raise SystemExit(main())

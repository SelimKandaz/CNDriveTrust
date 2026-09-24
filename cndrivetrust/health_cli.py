"""Interactive, read-only CNDriveTrust Health & Usage Summary workflow."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import drive_evidence as evidence

from .health import build_summary
from .history import latest_result
from .reports import finalize_bundle, render_terminal, write_bundle
from .vendors import samsung

VERSION = "2.3.0"
DEFAULT_ROOT = Path("/var/lib/harddrive-test-results")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def collect_lightweight(label: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect current identity/health counters without full read, PEL context, or mutation."""
    path = str(label["device_path"])
    records: dict[str, dict[str, Any]] = {
        "udevadm": evidence.run_command(["udevadm", "info", "--query=all", "--name", path], timeout=30),
        "smartctl-text": evidence.run_command(["smartctl", "-x", path], timeout=100),
        "smartctl-json": evidence.run_command(["smartctl", "-x", "-j", path], timeout=100),
    }
    controller = evidence.nvme_controller_path(path)
    if controller:
        records["nvme-id-ctrl"] = evidence.run_command(["nvme", "id-ctrl", controller, "--output-format=json"], timeout=60)
        records["nvme-id-ns"] = evidence.run_command(["nvme", "id-ns", path, "--output-format=json"], timeout=60)
        records["nvme-smart-log"] = evidence.run_command(["nvme", "smart-log", path, "--output-format=json"], timeout=60)
        records["nvme-smart-log-human"] = evidence.run_command(["nvme", "smart-log", path, "--human-readable"], timeout=60)
        records["nvme-error-log"] = evidence.run_command(
            ["nvme", "error-log", controller, "--log-entries=64", "--output-format=json"], timeout=60,
        )
        identity = evidence.parse_json_output(records["nvme-id-ctrl"])
        if evidence.parse_integer(identity.get("vid")) == samsung.SAMSUNG_VENDOR_ID:
            records["samsung-extended-smart-0xca"] = evidence.run_command(
                [
                    "nvme", "get-log", controller,
                    f"--log-id={samsung.EXTENDED_SMART_LOG_ID}",
                    f"--log-len={samsung.EXTENDED_SMART_LOG_BYTES}",
                    "--raw-binary",
                ],
                timeout=60,
                binary_stdout=True,
            )
        else:
            records["samsung-extended-smart-0xca"] = evidence.empty_record(
                ["nvme", "get-log", controller, "--log-id=0xca"],
                "NOT_EVALUATED",
                "Samsung vendor log was not queried because Samsung PCI vendor identity was not established.",
            )
    evidence.classify_smartctl_optional_selftest(records)
    return records


def choose_one(disks: list[dict[str, Any]], protected: set[str], fail_closed: bool) -> dict[str, Any] | None:
    displayed = evidence.display_disks(disks, protected, fail_closed)
    eligible = [item for item in displayed if item.get("eligible")]
    if not eligible:
        print("\nNo safe non-boot drive is available. No device command was sent to the boot disk.")
        return None
    print("\nSelect one drive number, or Q to return.")
    selection = input("Drive selection [Q]: ").strip().lower() or "q"
    if selection == "q":
        return None
    try:
        wanted = int(selection)
    except ValueError:
        print("Invalid selection. No drive was queried.")
        return None
    matches = [item for item in eligible if item.get("selection_number") == wanted]
    if len(matches) != 1:
        print("Selection was protected, missing, or invalid. No drive was queried.")
        return None
    return matches[0]


def export_bundle(run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    config = evidence.load_export_config(evidence.DEFAULT_CONFIG)
    destination_text = str(config.get("destination") or "").strip()
    if not destination_text:
        return {"status": "PENDING_EXPORT", "reason": "Windows destination is not configured."}
    destination = Path(destination_text)
    mounted, reason = evidence.mounted_cifs(destination)
    if not mounted:
        return {"status": "PENDING_EXPORT", "reason": reason, "destination": destination_text}
    serial = evidence.safe_component(summary["target"].get("serial"), "UNKNOWN_SERIAL")
    final = destination / "CNDriveTrust-Health-Summary" / serial / summary["run_id"]
    if final.exists():
        return {"status": "PENDING_EXPORT", "reason": "Destination already exists; it was preserved.", "destination": str(final)}
    staging = final.parent / f".{summary['run_id']}.staging-{uuid.uuid4().hex[:8]}"
    try:
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(run_dir, staging)
        staging.rename(final)
        return {"status": "EXPORTED", "destination": str(final), "exported_utc": utc_now()}
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        return {"status": "PENDING_EXPORT", "reason": f"Export failed: {type(exc).__name__}", "destination": str(final)}


def run() -> int:
    if not sys.stdin.isatty():
        print("ERROR: technician interaction requires a terminal; no drive was queried.")
        return 2
    print(f"\nCNDriveTrust v{VERSION} - Health & Usage Summary")
    print("READ-ONLY: lightweight current telemetry plus preserved last-test evidence.")
    global_records, block_data, protection_items = evidence.capture_global_evidence()
    protection = protection_items[0]
    protected = set(protection.get("protected_disks", []))
    fail_closed = bool(protection.get("fail_closed"))
    target = choose_one(block_data.get("blockdevices", []), protected, fail_closed)
    if not target:
        return 0

    records = collect_lightweight(target)
    observed = utc_now()
    normalized = evidence.normalize_device(
        target, records, evidence.safe_component(target.get("serial") or target["device_path"]), observed,
    )
    serial = evidence.value_value(normalized["values"], "serial") or target.get("serial")
    root = Path(os.environ.get("HDT_RESULT_ROOT", str(DEFAULT_ROOT)))
    last, source_path = latest_result(root, str(serial) if serial else None)
    run_id = f"HEALTH-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10].upper()}"
    current = {"target": target, "values": normalized["values"], "vendor_specific": normalized["vendor_specific"]}
    summary = build_summary(current, last_result=last, run_id=run_id, observed_utc=observed)
    summary["workflow_version"] = VERSION
    summary["boot_protection"] = protection
    summary["data_freshness"] = {
        "current_health_values": "LIVE_VALUE",
        "performance_values": "LAST_TEST_VALUE" if last else "NOT_AVAILABLE",
        "last_test_result_path": str(source_path) if source_path else None,
    }
    serial_component = evidence.safe_component(serial, "UNKNOWN_SERIAL")
    run_dir = root / "HEALTH_SUMMARY" / serial_component / run_id
    raw = {
        **global_records,
        **records,
        "boot-protection": {"stdout": json.dumps(protection, indent=2), "stderr": "", "status": "OK"},
    }
    write_bundle(run_dir, summary, raw)
    export = export_bundle(run_dir, summary)
    summary["export"] = export
    finalize_bundle(run_dir, summary)
    if export.get("status") == "EXPORTED":
        shutil.copytree(run_dir, Path(export["destination"]), dirs_exist_ok=True)
    try:
        from .central.sync import enqueue_finalized
        sync = enqueue_finalized(run_dir, kind="Health-Summary", serial=serial_component)
    except Exception as exc:
        sync = {"state": "SYNC_PENDING", "error": type(exc).__name__}
    print("\n" + render_terminal(summary))
    print(f"JSON: {run_dir / 'normalized' / 'health-summary.json'}")
    print(f"HTML: {run_dir / 'reports' / 'health-summary.html'}")
    print(f"Export: {export['status']}")
    print(f"Central: {sync.get('state', 'SYNC_PENDING')}")
    return 0


def preflight() -> int:
    _, block_data, protection_items = evidence.capture_global_evidence()
    protection = protection_items[0]
    displayed = evidence.display_disks(
        block_data.get("blockdevices", []),
        set(protection.get("protected_disks", [])),
        bool(protection.get("fail_closed")),
    )
    print(json.dumps({"version": VERSION, "protection": protection, "devices": displayed}, indent=2))
    return 2 if protection.get("fail_closed") else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args(argv)
    return preflight() if args.preflight else run()


if __name__ == "__main__":
    raise SystemExit(main())

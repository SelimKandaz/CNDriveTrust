"""Interactive read-only Erase/Sanitize capability inspector."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

import drive_evidence as evidence

from . import EXECUTION_STATUS
from .discovery import collect, contains_prohibited_command
from .reports import render_terminal, write_bundle

VERSION = "2.2.0"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def execution_enabled() -> bool:
    return False


def choose_one(disks, protected, fail_closed):
    displayed = evidence.display_disks(disks, protected, fail_closed)
    eligible = [item for item in displayed if item.get("eligible")]
    if not eligible:
        print("\nNo safe non-boot drive is available. Boot media cannot be selected.")
        return None
    choice = input("\nSelect one drive number, or Q to return [Q]: ").strip().lower() or "q"
    if choice == "q":
        return None
    try:
        number = int(choice)
    except ValueError:
        print("Invalid selection. No device command was sent.")
        return None
    matches = [item for item in eligible if item.get("selection_number") == number]
    if len(matches) != 1:
        print("Protected, missing, or invalid selection. No device command was sent.")
        return None
    return matches[0]


def inspect_capabilities() -> int:
    global_records, block_data, protection_items = evidence.capture_global_evidence()
    protection = protection_items[0]
    target = choose_one(
        block_data.get("blockdevices", []),
        set(protection.get("protected_disks", [])),
        bool(protection.get("fail_closed")),
    )
    if target is None:
        return 0
    result, records = collect(target, evidence.run_command, evidence.parse_json_output, evidence.nvme_controller_path)
    if contains_prohibited_command(records):
        raise RuntimeError("Safety invariant violated: destructive command detected in discovery evidence")
    run_id = f"ERASECAP-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10].upper()}"
    result.update({
        "run_id": run_id,
        "workflow_version": VERSION,
        "observed_utc": utc_now(),
        "boot_protection": protection,
    })
    root = Path(os.environ.get("HDT_RESULT_ROOT", "/var/lib/harddrive-test-results"))
    serial = evidence.safe_component(target.get("serial"), "UNKNOWN_SERIAL")
    run_dir = root / "ERASE_CAPABILITY" / serial / run_id
    write_bundle(run_dir, result, {**global_records, **records})
    print("\n" + render_terminal(result))
    print(f"JSON: {run_dir / 'normalized' / 'erase-capabilities.json'}")
    print(f"HTML: {run_dir / 'reports' / 'erase-capabilities.html'}")
    return 0


def show_menu() -> int:
    if not sys.stdin.isatty():
        print("ERROR: technician interaction requires a terminal; no drive was queried.")
        return 2
    while True:
        print("\n" + "=" * 62)
        print("CNDriveTrust - ERASE / SANITIZE")
        print("=" * 62)
        print("1. Inspect Erase / Sanitize Capabilities  [READ-ONLY]")
        print("2. Execute Erase / Sanitize               [DISABLED]")
        print("B. Back")
        choice = input("\nSelection: ").strip().lower()
        if choice == "1":
            inspect_capabilities()
        elif choice == "2":
            print("\nEXECUTION DISABLED")
            print("This release contains no destructive erase/sanitize backend.")
            input("Press Enter to continue.")
        elif choice == "b":
            return 0
        else:
            print("Unknown selection. No action was performed.")


def preflight() -> int:
    _, block_data, protection_items = evidence.capture_global_evidence()
    protection = protection_items[0]
    displayed = evidence.display_disks(
        block_data.get("blockdevices", []), set(protection.get("protected_disks", [])), bool(protection.get("fail_closed")),
    )
    print(json.dumps({
        "version": VERSION,
        "execution": EXECUTION_STATUS,
        "protection": protection,
        "devices": displayed,
    }, indent=2))
    return 2 if protection.get("fail_closed") else 0


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(VERSION)
        return 0
    if arguments == ["--preflight"]:
        return preflight()
    if arguments:
        print("Unsupported argument. No action was performed.")
        return 2
    return show_menu()


if __name__ == "__main__":
    raise SystemExit(main())


"""Technician-facing terminal, JSON, and HTML Health Summary reports."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any

from .formatting import bytes_human, number, raw_value, shown


def _line(label: str, value: Any, width: int = 30) -> str:
    return f"{label:<{width}} {value}"


def render_terminal(summary: dict[str, Any]) -> str:
    target = summary["target"]
    values = summary["current_values"]
    dimensions = summary["dimensions"]
    history = dimensions["history_trust"]
    endurance = dimensions["endurance"]
    performance = dimensions["performance"]
    lines = [
        "=" * 68,
        "CNDriveTrust - Health & Usage Summary",
        "=" * 68,
        _line("Model", shown(target.get("model"))),
        _line("Serial", shown(target.get("serial"))),
        _line("Firmware", shown(target.get("firmware"))),
        _line("Capacity", bytes_human(target.get("capacity_bytes"))),
        _line("Transport", shown(target.get("transport"))),
        "",
        "CURRENT MEDIA HEALTH",
        "-" * 68,
        _line("Media Health", dimensions["media_health"]["state"]),
        _line("Remaining Endurance", shown(endurance["evidence"].get("remaining_percent"), "%")),
        _line("Available Spare", shown(number(values, "available_spare"), "%")),
        _line("Critical Warning", shown(number(values, "critical_warning"))),
        _line("Temperature", shown(number(values, "temperature"), " C")),
        "",
        "ERROR STATE",
        "-" * 68,
        _line("Error State", dimensions["error_state"]["state"]),
        _line("Media Errors", shown(number(values, "media_errors"))),
        _line("Error Log Entries", shown(number(values, "num_err_log_entries"))),
        _line("Program Failures", shown(number(values, "program_fail_count"))),
        _line("Erase Failures", shown(number(values, "erase_fail_count"))),
        _line("CRC Errors", shown(number(values, "crc_error_count"))),
        _line("End-to-End Errors", shown(number(values, "end_to_end_error_count"))),
        "",
        "USAGE HISTORY",
        "-" * 68,
        _line("Usage Profile", dimensions["usage"]["state"]),
        _line("Power-On Hours", summary["usage_display"]["power_on_hours"]),
        _line("Vendor Runtime", summary["usage_display"]["vendor_runtime"]),
        _line("Power Cycles", shown(number(values, "power_cycles"))),
        _line("Unsafe Shutdowns", shown(number(values, "unsafe_shutdowns"))),
        _line("Host Reads", summary["usage_display"]["host_reads"]),
        _line("Host Writes", summary["usage_display"]["host_writes"]),
        _line("Controller Busy Time", shown(number(values, "controller_busy_time"), " minutes")),
        "",
        "NAND / MEDIA WEAR",
        "-" * 68,
        _line("Endurance", endurance["state"]),
        _line("Percentage Used", shown(number(values, "percentage_used"), "%")),
        _line("Vendor Wear", shown(number(values, "vendor_media_wear_percent"), "% used")),
        _line("Minimum Erase Cycles", shown(number(values, "nand_erase_cycles_minimum"))),
        _line("Average Erase Cycles", shown(number(values, "nand_erase_cycles_average"))),
        _line("Maximum Erase Cycles", shown(number(values, "nand_erase_cycles_maximum"))),
        "",
        "PERFORMANCE (PRESERVED LAST FULL TEST)",
        "-" * 68,
        _line("Full Read Test", performance["state"]),
        _line("Last Verified Read Speed", summary["performance_display"]["last_verified_read_speed"]),
        _line("Verified Capacity", summary["performance_display"]["verified_capacity"]),
        _line("Source Run", shown(performance["evidence"].get("source_run_id"))),
        "",
        "HISTORY / PROVENANCE TRUST",
        "-" * 68,
        _line("History Trust", history["state"]),
        _line("Rule", history.get("code", "UNAVAILABLE")),
        f"Reason: {history['explanation']}",
    ]
    for statement in history.get("possible_explanations", []):
        lines.append(f"  Possible: {statement}")
    for statement in history.get("not_established", []):
        lines.append(f"  NOT established: {statement}")
    lines.extend([
        "",
        _line("Overall", summary["overall"]),
        _line("Observed UTC", summary["observed_utc"]),
        _line("Summary Run", summary["run_id"]),
        "=" * 68,
    ])
    return "\n".join(lines) + "\n"


def render_html(summary: dict[str, Any]) -> str:
    terminal = render_terminal(summary)
    dimensions = summary["dimensions"]
    cards = "".join(
        f"<section><h2>{html.escape(name.replace('_', ' ').title())}</h2>"
        f"<strong class='{html.escape(data['state'].lower())}'>{html.escape(data['state'])}</strong>"
        f"<p>{html.escape(data['explanation'])}</p></section>"
        for name, data in dimensions.items()
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>CNDriveTrust Health &amp; Usage Summary</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;background:#f3f6f8;color:#17212b;margin:0;padding:2rem}}
main{{max-width:1100px;margin:auto}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}}
section,pre{{background:white;border:1px solid #d5dee5;border-radius:8px;padding:1rem;box-shadow:0 2px 7px #0001}}
h1{{margin-bottom:.25rem}} h2{{font-size:1rem;margin-top:0}} strong{{display:inline-block;padding:.25rem .6rem;border-radius:999px;background:#e9eef2}}
.good,.excellent,.consistent,.supported,.verified{{background:#d7f3df;color:#145c2b}}
.review_required,.critical,.failed{{background:#ffe0dc;color:#8a1c13}}
.partial,.unavailable,.not_run{{background:#fff0c7;color:#765100}} pre{{overflow:auto;white-space:pre-wrap;line-height:1.35}}
</style></head><body><main><h1>CNDriveTrust Health &amp; Usage Summary</h1>
<p>Run {html.escape(str(summary['run_id']))} | {html.escape(str(summary['observed_utc']))}</p>
<div class="grid">{cards}</div><h2>Technician view</h2><pre>{html.escape(terminal)}</pre>
</main></body></html>"""


def finalize_bundle(root: Path, summary: dict[str, Any]) -> None:
    (root / "normalized" / "health-summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    (root / "reports" / "health-summary.txt").write_text(render_terminal(summary), encoding="utf-8")
    (root / "reports" / "health-summary.html").write_text(render_html(summary), encoding="utf-8")
    for generated in (root / "manifest.json", root / "checksums.sha256"):
        generated.unlink(missing_ok=True)
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": digest})
    manifest = {"artifact_type": summary["artifact_type"], "run_id": summary["run_id"], "files": entries}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksum_lines = [f"{item['sha256']}  {item['path']}" for item in entries]
    (root / "checksums.sha256").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def write_bundle(root: Path, summary: dict[str, Any], raw_records: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    (root / "reports").mkdir()
    (root / "normalized").mkdir()
    for name, record in raw_records.items():
        safe = "".join(char if char.isalnum() or char in "_.-" else "_" for char in name)
        output = record.get("stdout_bytes") if isinstance(record, dict) else None
        if isinstance(output, bytes):
            (root / "raw" / f"{safe}.stdout.bin").write_bytes(output)
        elif isinstance(record, dict):
            (root / "raw" / f"{safe}.stdout.txt").write_text(str(record.get("stdout", "")), encoding="utf-8")
        if isinstance(record, dict):
            (root / "raw" / f"{safe}.stderr.txt").write_text(str(record.get("stderr", "")), encoding="utf-8")
            metadata = {key: value for key, value in record.items() if key not in ("stdout", "stderr", "stdout_bytes")}
            if isinstance(output, bytes):
                metadata["stdout_bytes_count"] = len(output)
            (root / "raw" / f"{safe}.meta.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8")
    finalize_bundle(root, summary)

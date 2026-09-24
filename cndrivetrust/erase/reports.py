"""Evidence output for read-only erase/sanitize capability discovery."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any


def _flatten(prefix: str, value: Any, output: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), child, output)
    elif isinstance(value, list):
        output.append((prefix, ", ".join(str(item) for item in value) or "EMPTY"))
    else:
        output.append((prefix, "UNAVAILABLE" if value is None else str(value)))


def render_terminal(result: dict[str, Any]) -> str:
    target = result["target"]
    fields: list[tuple[str, str]] = []
    _flatten("", result["capabilities"], fields)
    lines = [
        "=" * 68,
        "CNDriveTrust - Erase / Sanitize Capability Discovery",
        "=" * 68,
        f"{'Model':<30} {target.get('model') or 'UNAVAILABLE'}",
        f"{'Serial':<30} {target.get('serial') or 'UNAVAILABLE'}",
        f"{'Device':<30} {target.get('device_path') or 'UNAVAILABLE'}",
        f"{'Transport':<30} {result.get('transport') or 'UNAVAILABLE'}",
        f"{'Protocol':<30} {result.get('protocol')}",
        f"{'Media type':<30} {result.get('media_type')}",
        "",
        "DISCOVERED CAPABILITIES",
        "-" * 68,
    ]
    lines.extend(f"{name:<38} {value}" for name, value in fields)
    lines.extend([
        "",
        "EXECUTION",
        "-" * 68,
        "Status                         DISABLED",
        "No erase, sanitize, format, namespace, security or overwrite command",
        "exists in this release.",
        "=" * 68,
    ])
    return "\n".join(lines) + "\n"


def render_html(result: dict[str, Any]) -> str:
    terminal = html.escape(render_terminal(result))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>CNDriveTrust Erase Capability Discovery</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f3f6f8;padding:2rem;color:#17212b}}
main{{max-width:1050px;margin:auto}}pre{{background:white;border:1px solid #d5dee5;border-radius:8px;padding:1rem;white-space:pre-wrap}}
.disabled{{display:inline-block;background:#fff0c7;color:#765100;padding:.3rem .7rem;border-radius:999px}}</style>
</head><body><main><h1>CNDriveTrust Erase / Sanitize Capability Discovery</h1>
<p class="disabled">EXECUTION DISABLED</p><pre>{terminal}</pre></main></body></html>"""


def write_bundle(root: Path, result: dict[str, Any], records: dict[str, dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "raw").mkdir()
    (root / "reports").mkdir()
    (root / "normalized").mkdir()
    for name, record in records.items():
        safe = "".join(char if char.isalnum() or char in "_.-" else "_" for char in name)
        (root / "raw" / f"{safe}.stdout.txt").write_text(str(record.get("stdout") or ""), encoding="utf-8")
        (root / "raw" / f"{safe}.stderr.txt").write_text(str(record.get("stderr") or ""), encoding="utf-8")
        metadata = {key: value for key, value in record.items() if key not in ("stdout", "stderr", "stdout_bytes")}
        (root / "raw" / f"{safe}.meta.json").write_text(json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8")
    (root / "normalized" / "erase-capabilities.json").write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    (root / "reports" / "erase-capabilities.txt").write_text(render_terminal(result), encoding="utf-8")
    (root / "reports" / "erase-capabilities.html").write_text(render_html(result), encoding="utf-8")
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (root / "manifest.json").write_text(json.dumps({"artifact_type": result["artifact_type"], "run_id": result["run_id"], "files": entries}, indent=2) + "\n", encoding="utf-8")
    (root / "checksums.sha256").write_text("\n".join(f"{item['sha256']}  {item['path']}" for item in entries) + "\n", encoding="utf-8")


"""Read-only lookup of preserved CNDriveTrust results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def latest_result(root: Path, serial: str | None) -> tuple[dict[str, Any] | None, Path | None]:
    if not serial or not root.exists():
        return None, None
    candidates: list[Path] = []
    for path in root.rglob("normalized/result.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        target = payload.get("target", {})
        if str(target.get("serial") or "").strip() == str(serial).strip():
            candidates.append(path)
    if not candidates:
        return None, None
    chosen = max(candidates, key=lambda item: item.stat().st_mtime_ns)
    try:
        return json.loads(chosen.read_text(encoding="utf-8")), chosen
    except (OSError, ValueError, TypeError):
        return None, None


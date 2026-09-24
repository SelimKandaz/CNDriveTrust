#!/usr/bin/env python3
"""Create a clearly labeled non-physical fixture and exercise live Central."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from cndrivetrust.central.sync import DEFAULT_CONFIG, enqueue_finalized


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cndrivetrust-central-smoke-") as temporary:
        root = Path(temporary)
        run_id = "RUN-CENTRAL-INTEGRATION-SMOKE-V6"
        run = root / run_id
        (run / "normalized").mkdir(parents=True)
        result = run / "normalized" / "result.json"
        result.write_text(json.dumps({"run_id": run_id, "serial": "NONPHYSICAL-FIXTURE", "physical": False}) + "\n")
        digest = hashlib.sha256(result.read_bytes()).hexdigest()
        manifest = run / "manifest.json"
        manifest.write_text(json.dumps({"run_id": run_id, "artifact_type": "INTEGRATION_TEST",
                                        "files": [{"path": "normalized/result.json", "sha256": digest}]}) + "\n")
        manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        (run / "checksums.sha256").write_text(
            f"{digest}  normalized/result.json\n{manifest_digest}  manifest.json\n")
        first = enqueue_finalized(run, kind="Integration-Test", serial="NONPHYSICAL-FIXTURE", batch_id="TEST")
        second = enqueue_finalized(run, kind="Integration-Test", serial="NONPHYSICAL-FIXTURE", batch_id="TEST")
        print(json.dumps({"first": first, "second": second}, indent=2, default=str))
        return 0 if first.get("drain", {}).get("synced") == 1 and second.get("state") == "SYNCED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

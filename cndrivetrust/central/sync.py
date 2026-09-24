"""High-level offline-first queue integration."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .bundle import create_bundle
from .client import CentralClient
from .queue import SyncQueue

DEFAULT_CONFIG = Path("/etc/cndrivetrust/central.json")


def load_config(path: Path = DEFAULT_CONFIG) -> dict:
    if not path.is_file():
        return {"enabled": False, "reason": "CONFIG_NOT_FOUND"}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"enabled": False, "reason": "CONFIG_INVALID"}


def queue_from_config(config: dict) -> SyncQueue:
    return SyncQueue(Path(config.get("queue_database", "/var/lib/cndrivetrust-central/queue.sqlite3")))


def client_from_config(config: dict) -> CentralClient:
    token_path = Path(config["token_file"])
    token = token_path.read_text(encoding="utf-8").strip()
    return CentralClient(config["endpoint"], token, ca_file=config.get("ca_file"), verify_tls=bool(config.get("verify_tls", True)))


def enqueue_finalized(run_dir: Path, *, kind: str, serial: str, batch_id: str = "UNASSIGNED",
                      config_path: Path = DEFAULT_CONFIG) -> dict:
    config = load_config(config_path)
    if not config.get("enabled"):
        return {"state": "LOCAL_COMPLETE", "central": config.get("reason", "DISABLED")}
    bundle, digest = create_bundle(run_dir, Path(config.get("spool_directory", "/var/lib/cndrivetrust-central/spool")))
    queue = queue_from_config(config)
    state = queue.enqueue(run_id=run_dir.name, kind=kind, serial=serial, batch_id=batch_id, run_dir=run_dir,
                          bundle_path=bundle, bundle_sha256=digest)
    result = {"state": state, "bundle_sha256": digest}
    try:
        result["drain"] = drain(config_path=config_path)
    except Exception as exc:
        result["state"] = "SYNC_PENDING"
        result["error"] = type(exc).__name__
    return result


def drain(*, config_path: Path = DEFAULT_CONFIG, limit: int = 20) -> dict:
    config = load_config(config_path)
    queue = queue_from_config(config)
    if not config.get("enabled"):
        return {"central": "DISABLED", **queue.status()}
    client = client_from_config(config)
    synced = failed = conflicts = 0
    for record in queue.pending(limit):
        queue.mark(record["sync_id"], "SYNC_IN_PROGRESS")
        try:
            acknowledgement = client.upload(record)
            queue.mark(record["sync_id"], "SYNCED", acknowledgement=acknowledgement)
            synced += 1
        except ValueError as exc:
            queue.mark(record["sync_id"], "SYNC_FAILED_PERMANENT", error=str(exc))
            conflicts += 1
        except Exception as exc:
            queue.mark(record["sync_id"], "SYNC_FAILED_RETRYABLE", error=f"{type(exc).__name__}: {exc}")
            failed += 1
    return {"synced": synced, "retryable_failed": failed, "permanent_failed": conflicts, **queue.status()}

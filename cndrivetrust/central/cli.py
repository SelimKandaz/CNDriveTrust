"""Technician Central status and retry interface."""

from __future__ import annotations

import argparse
import json

from .sync import DEFAULT_CONFIG, client_from_config, drain, load_config, queue_from_config


def status() -> dict:
    config = load_config()
    result = {"host_network": "ENABLED", "cndrivetrust_lan": "ENABLED", "configured": bool(config.get("enabled"))}
    result.update(queue_from_config(config).status())
    if config.get("enabled"):
        try:
            result["central"] = client_from_config(config).health().get("status", "ONLINE")
        except Exception as exc:
            result["central"] = "OFFLINE"; result["last_connection_error"] = type(exc).__name__
    else:
        result["central"] = "DISABLED"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("action", choices=("status", "retry"), nargs="?", default="status")
    args = parser.parse_args(argv); result = drain() if args.action == "retry" else status()
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())


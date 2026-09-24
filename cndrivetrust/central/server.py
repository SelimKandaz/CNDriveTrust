"""Standalone CNDriveTrust Central receiver for the Windows operations host."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import ssl
import tempfile
import tarfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import unquote
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from .bundle import safe_extract, sha256_file, validate_checksums

SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


class ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class Receiver:
    def __init__(self, root: Path, token: str, max_bytes: int = 2 * 1024**3):
        self.root, self.token, self.max_bytes = root.resolve(), token, max_bytes
        for name in ("incoming", "runs", "indexes", "logs"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.database = self.root / "indexes" / "serial-history.sqlite3"
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS runs_v2(
              run_id TEXT NOT NULL, kind TEXT NOT NULL, serial TEXT NOT NULL, batch_id TEXT NOT NULL,
              bundle_sha256 TEXT NOT NULL, final_path TEXT NOT NULL, received_utc TEXT NOT NULL)""")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS runs_v2_identity ON runs_v2(run_id,serial)")

    @staticmethod
    def response(start, status: str, payload: dict):
        body = json.dumps(payload, sort_keys=True).encode()
        start(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
        return [body]

    def __call__(self, env, start):
        if env.get("REQUEST_METHOD") == "GET" and env.get("PATH_INFO") == "/healthz":
            return self.response(start, "200 OK", {"status": "ONLINE", "product": "CNDriveTrust"})
        parts = str(env.get("PATH_INFO") or "").split("/")
        if env.get("REQUEST_METHOD") != "PUT" or len(parts) != 8 or parts[1:3] != ["v1", "runs"]:
            return self.response(start, "404 Not Found", {"error": "NOT_FOUND"})
        if not hmac.compare_digest(str(env.get("HTTP_AUTHORIZATION") or ""), f"Bearer {self.token}"):
            return self.response(start, "401 Unauthorized", {"error": "UNAUTHORIZED"})
        kind, serial, run_id, expected = map(unquote, parts[3:7])
        # split() leaves a trailing component only for a trailing slash; normal route has seven parts.
        return self.response(start, "400 Bad Request", {"error": "INVALID_ROUTE"})

    def receive(self, env, start, values: list[str]):
        kind, serial, run_id, expected = map(unquote, values)
        batch = str(env.get("HTTP_X_CNDRIVETRUST_BATCH") or "UNASSIGNED")
        if not all(SAFE.fullmatch(item) for item in (kind, serial, run_id, batch)) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            return self.response(start, "400 Bad Request", {"error": "INVALID_IDENTITY"})
        try:
            length = int(env.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > self.max_bytes:
            return self.response(start, "413 Payload Too Large", {"error": "SIZE_REJECTED"})
        with closing(sqlite3.connect(self.database)) as db:
            row = db.execute("SELECT bundle_sha256,final_path FROM runs_v2 WHERE run_id=? AND serial=?", (run_id, serial)).fetchone()
        if row:
            if row[0] == expected:
                return self.response(start, "200 OK", {"status": "ALREADY_SYNCED", "run_id": run_id, "serial": serial,
                                                        "manifest_hash_result": "MATCH", "path": row[1]})
            return self.response(start, "409 Conflict", {"error": "RUN_ID_CONFLICT"})
        fd, temporary_name = tempfile.mkstemp(prefix=f"{run_id}.", suffix=".upload", dir=self.root / "incoming")
        digest, remaining = hashlib.sha256(), length
        try:
            with os.fdopen(fd, "wb") as stream:
                while remaining:
                    block = env["wsgi.input"].read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError("short body")
                    stream.write(block); digest.update(block); remaining -= len(block)
                stream.flush(); os.fsync(stream.fileno())
            if digest.hexdigest() != expected:
                raise ValueError("bundle SHA mismatch")
            final = self.root / "runs" / kind / batch / serial / run_id
            staging = final.parent / f".{run_id}.incoming"
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            safe_extract(Path(temporary_name), staging)
            checked = validate_checksums(staging)
            if not (staging / "manifest.json").is_file():
                raise ValueError("manifest missing")
            final.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(final)
            received = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("INSERT INTO runs_v2 VALUES(?,?,?,?,?,?,?)", (run_id, kind, serial, batch, expected, str(final), received))
            return self.response(start, "201 Created", {"status": "ACKNOWLEDGED", "run_id": run_id, "serial": serial,
                "manifest_hash_result": "MATCH", "files_verified": checked, "timestamp": received, "path": str(final)})
        except (OSError, ValueError, tarfile.TarError) as exc:
            if 'staging' in locals() and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            return self.response(start, "400 Bad Request", {"error": type(exc).__name__})
        finally:
            Path(temporary_name).unlink(missing_ok=True)


class RoutedReceiver(Receiver):
    def __call__(self, env, start):
        if env.get("REQUEST_METHOD") == "GET" and env.get("PATH_INFO") == "/healthz":
            return self.response(start, "200 OK", {"status": "ONLINE", "product": "CNDriveTrust"})
        parts = str(env.get("PATH_INFO") or "").strip("/").split("/")
        if env.get("REQUEST_METHOD") != "PUT" or len(parts) != 6 or parts[:2] != ["v1", "runs"]:
            return self.response(start, "404 Not Found", {"error": "NOT_FOUND"})
        if not hmac.compare_digest(str(env.get("HTTP_AUTHORIZATION") or ""), f"Bearer {self.token}"):
            return self.response(start, "401 Unauthorized", {"error": "UNAUTHORIZED"})
        return self.receive(env, start, parts[2:])


def serve(root: Path, bind: str, port: int, certificate: Path, key: Path, token_file: Path) -> None:
    token = token_file.read_text(encoding="utf-8").strip()
    app = RoutedReceiver(root, token)
    httpd = make_server(bind, port, app, server_class=ThreadingServer, handler_class=WSGIRequestHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(certificate), str(key)); httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    print(json.dumps({"status": "LISTENING", "product": "CNDriveTrust", "port": port}), flush=True)
    httpd.serve_forever()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bind", default="0.0.0.0"); parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--cert", type=Path, required=True); parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True); args = parser.parse_args(argv)
    serve(args.root, args.bind, args.port, args.cert, args.key, args.token_file); return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Authenticated TLS bundle client."""

from __future__ import annotations

import http.client
import json
import ssl
from pathlib import Path
from urllib.parse import quote, urlparse


class CentralClient:
    def __init__(self, endpoint: str, token: str, *, ca_file: str | None = None, verify_tls: bool = True):
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Central endpoint must be credential-free HTTPS")
        self.parsed, self.token = parsed, token
        self.context = ssl.create_default_context(cafile=ca_file) if verify_tls else ssl._create_unverified_context()

    def health(self) -> dict:
        connection = http.client.HTTPSConnection(self.parsed.hostname, self.parsed.port or 443, timeout=10, context=self.context)
        try:
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            payload = json.loads(response.read())
            if response.status != 200:
                raise RuntimeError(f"Central HTTP {response.status}")
            return payload
        finally:
            connection.close()

    def upload(self, record: dict) -> dict:
        path = Path(record["bundle_path"])
        route = "/v1/runs/{}/{}/{}/{}".format(*[quote(str(record[key]), safe="") for key in
            ("kind", "serial", "run_id", "bundle_sha256")])
        connection = http.client.HTTPSConnection(self.parsed.hostname, self.parsed.port or 443, timeout=120, context=self.context)
        try:
            size = path.stat().st_size
            connection.putrequest("PUT", route)
            connection.putheader("Authorization", f"Bearer {self.token}")
            connection.putheader("Content-Type", "application/gzip")
            connection.putheader("Content-Length", str(size))
            connection.putheader("X-CNDriveTrust-Batch", str(record.get("batch_id") or "UNASSIGNED"))
            connection.endheaders()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    connection.send(block)
            response = connection.getresponse()
            payload = json.loads(response.read())
            if response.status not in (200, 201):
                error = payload.get("error", f"HTTP_{response.status}")
                raise ValueError(error) if response.status == 409 else RuntimeError(error)
            return payload
        finally:
            connection.close()


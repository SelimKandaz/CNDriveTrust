import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cndrivetrust.central.bundle import create_bundle, safe_extract, validate_checksums
from cndrivetrust.central.queue import SyncQueue
from cndrivetrust.central.server import RoutedReceiver


def finalized(root: Path, run_id="RUN-TEST-12345678") -> Path:
    run = root / run_id; (run / "normalized").mkdir(parents=True)
    evidence = run / "normalized" / "result.json"; evidence.write_text('{"serial":"SER1"}\n')
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    (run / "manifest.json").write_text(json.dumps({"run_id": run_id, "files": [{"path": "normalized/result.json", "sha256": digest}]}))
    manifest_digest = hashlib.sha256((run / "manifest.json").read_bytes()).hexdigest()
    (run / "checksums.sha256").write_text(f"{digest}  normalized/result.json\n{manifest_digest}  manifest.json\n")
    return run


class CentralSyncTests(unittest.TestCase):
    def test_bundle_roundtrip_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = finalized(root); bundle, digest = create_bundle(run, root / "spool")
            self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), digest)
            out = root / "out"; out.mkdir(); safe_extract(bundle, out)
            self.assertEqual(validate_checksums(out), 2)

    def test_queue_is_persistent_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = finalized(root); bundle, digest = create_bundle(run, root / "spool")
            queue = SyncQueue(root / "queue.sqlite3")
            state = queue.enqueue(run_id=run.name, kind="Test-Disk", serial="SER1", batch_id="PO1",
                                  run_dir=run, bundle_path=bundle, bundle_sha256=digest)
            self.assertEqual(state, "SYNC_PENDING")
            self.assertEqual(queue.status()["pending"], 1)
            self.assertEqual(queue.enqueue(run_id=run.name, kind="Test-Disk", serial="SER1", batch_id="PO1",
                                           run_dir=run, bundle_path=bundle, bundle_sha256=digest), "SYNC_PENDING")
            with self.assertRaisesRegex(ValueError, "RUN_ID_CONFLICT"):
                queue.enqueue(run_id=run.name, kind="Test-Disk", serial="SER1", batch_id="PO1",
                              run_dir=run, bundle_path=bundle, bundle_sha256="0" * 64)

    def test_same_run_id_allows_distinct_drive_serials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = finalized(root); bundle, digest = create_bundle(run, root / "spool")
            queue = SyncQueue(root / "queue.sqlite3")
            queue.enqueue(run_id=run.name, kind="Test-Disk", serial="SER1", batch_id="PO1",
                          run_dir=run, bundle_path=bundle, bundle_sha256=digest)
            queue.enqueue(run_id=run.name, kind="Test-Disk", serial="SER2", batch_id="PO1",
                          run_dir=run, bundle_path=bundle, bundle_sha256=digest)
            self.assertEqual(queue.status()["pending"], 2)

    def test_receiver_accepts_duplicate_and_rejects_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); run = finalized(root); bundle, digest = create_bundle(run, root / "spool")
            receiver = RoutedReceiver(root / "central", "secret")
            def request(sent_digest=digest, body=bundle.read_bytes()):
                captured = []
                env = {"REQUEST_METHOD": "PUT", "PATH_INFO": f"/v1/runs/Test-Disk/SER1/{run.name}/{sent_digest}",
                       "HTTP_AUTHORIZATION": "Bearer secret", "HTTP_X_CNDRIVETRUST_BATCH": "PO1",
                       "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
                payload = b"".join(receiver(env, lambda status, headers: captured.append(status)))
                return captured[0], json.loads(payload)
            status, payload = request(); self.assertEqual(status, "201 Created"); self.assertEqual(payload["manifest_hash_result"], "MATCH")
            status, payload = request(); self.assertEqual(status, "200 OK"); self.assertEqual(payload["status"], "ALREADY_SYNCED")
            status, payload = request("0" * 64); self.assertEqual(status, "409 Conflict"); self.assertEqual(payload["error"], "RUN_ID_CONFLICT")

    def test_corrupt_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); receiver = RoutedReceiver(root / "central", "secret"); body = b"not a tar"
            digest = hashlib.sha256(body).hexdigest(); captured = []
            env = {"REQUEST_METHOD": "PUT", "PATH_INFO": f"/v1/runs/Test-Disk/SER1/RUN-TEST-12345678/{digest}",
                   "HTTP_AUTHORIZATION": "Bearer secret", "HTTP_X_CNDRIVETRUST_BATCH": "PO1",
                   "CONTENT_LENGTH": str(len(body)), "wsgi.input": io.BytesIO(body)}
            payload = json.loads(b"".join(receiver(env, lambda status, headers: captured.append(status))))
            self.assertEqual(captured[0], "400 Bad Request"); self.assertIn("error", payload)


if __name__ == "__main__": unittest.main()

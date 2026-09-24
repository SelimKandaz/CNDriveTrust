import json
import tempfile
import unittest
from pathlib import Path

from cndrivetrust.erase import EXECUTION_STATUS
from cndrivetrust.erase import ata, nvme, scsi
from cndrivetrust.erase.cli import execution_enabled
from cndrivetrust.erase.discovery import (
    classify_protocol,
    collect,
    contains_prohibited_command,
    media_type,
)
from cndrivetrust.erase.reports import write_bundle


class EraseCapabilityTests(unittest.TestCase):
    def test_nvme_sanitize_and_format_bits(self):
        result = nvme.decode({"sanicap": 0b011, "oacs": 0b010, "fna": 0b100}, "OK")
        self.assertEqual(result["sanitize"]["crypto_erase"], "SUPPORTED")
        self.assertEqual(result["sanitize"]["block_erase"], "SUPPORTED")
        self.assertEqual(result["sanitize"]["overwrite"], "NOT_SUPPORTED")
        self.assertEqual(result["format"]["command"], "SUPPORTED")
        self.assertEqual(result["execution"], "DISABLED")

    def test_missing_nvme_fields_are_unknown_not_unsupported(self):
        result = nvme.decode({}, "UNSUPPORTED")
        self.assertEqual(result["sanitize"]["block_erase"], "UNKNOWN")
        self.assertEqual(result["format"]["command"], "UNKNOWN")

    def test_ata_security_and_frozen_state(self):
        text = """Security:\n        supported\n        not enabled\n        frozen\n        2min for SECURITY ERASE UNIT.\n        4min for ENHANCED SECURITY ERASE UNIT.\nSanitize feature set\n"""
        result = ata.parse_identify(text)
        self.assertEqual(result["security_feature"], "SUPPORTED")
        self.assertEqual(result["secure_erase"], "SUPPORTED")
        self.assertEqual(result["enhanced_secure_erase"], "SUPPORTED")
        self.assertEqual(result["frozen_state"], "FROZEN")
        self.assertEqual(result["sanitize_feature"], "SUPPORTED")

    def test_query_failure_is_not_reported_as_unsupported(self):
        result = ata.parse_identify("", "QUERY_FAILED")
        self.assertEqual(result["secure_erase"], "UNKNOWN")
        self.assertEqual(result["query_status"], "QUERY_FAILED")

    def test_scsi_capabilities_preserve_query_states(self):
        result = scsi.summarize({
            "scsi-sanitize-opcode": {"status": "OK", "stdout": "supported"},
            "scsi-sanitize-block-erase": {"status": "UNSUPPORTED", "stdout": ""},
        })
        self.assertEqual(result["sanitize_command"], "SUPPORTED")
        self.assertEqual(result["block_erase_service_action"], "UNSUPPORTED")
        self.assertEqual(result["crypto_erase_service_action"], "NOT_EVALUATED")

    def test_protocol_and_media_classification(self):
        self.assertEqual(classify_protocol({"device_path": "/dev/nvme0n1", "transport": "NATIVE_NVME"}), "NVME")
        self.assertEqual(classify_protocol({"device_path": "/dev/sdb", "transport": "HBA_OR_RAID"}), "SCSI")
        self.assertEqual(media_type({"rotational": 1}), "ROTATIONAL_HDD")
        self.assertEqual(media_type({"rotational": 0}), "SOLID_STATE")

    def test_nvme_discovery_calls_read_only_commands_only(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            if "id-ctrl" in argv:
                return {"argv": argv, "status": "OK", "stdout": '{"sanicap":3,"oacs":2,"fna":4}', "stderr": ""}
            return {"argv": argv, "status": "OK", "stdout": "status", "stderr": ""}

        result, records = collect(
            {"device_path": "/dev/nvme0n1", "transport": "NATIVE_NVME", "rotational": 0},
            run,
            lambda record: json.loads(record["stdout"]),
            lambda path: "/dev/nvme0",
        )
        self.assertEqual(result["execution"]["status"], "DISABLED")
        self.assertFalse(contains_prohibited_command(records))
        self.assertEqual([item[1] for item in calls], ["id-ctrl", "sanitize-log"])

    def test_execution_is_structurally_disabled(self):
        self.assertEqual(EXECUTION_STATUS, "DISABLED")
        self.assertFalse(execution_enabled())

    def test_capability_report_bundle_opens_and_hashes(self):
        result = {
            "artifact_type": "CNDRIVETRUST_ERASE_CAPABILITY_DISCOVERY",
            "run_id": "ERASECAP-TEST",
            "target": {"model": "Drive", "serial": "TEST", "device_path": "/dev/test"},
            "transport": "NATIVE_NVME",
            "protocol": "NVME",
            "media_type": "SOLID_STATE",
            "capabilities": {"sanitize": {"block_erase": "SUPPORTED"}, "execution": "DISABLED"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bundle"
            write_bundle(root, result, {"identify": {"argv": ["nvme", "id-ctrl"], "status": "OK", "stdout": "{}", "stderr": ""}})
            parsed = json.loads((root / "normalized" / "erase-capabilities.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["capabilities"]["execution"], "DISABLED")
            self.assertTrue((root / "reports" / "erase-capabilities.html").stat().st_size > 0)
            self.assertTrue((root / "checksums.sha256").stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()


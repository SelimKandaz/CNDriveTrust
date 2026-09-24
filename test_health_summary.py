import unittest
import json
import tempfile
from pathlib import Path

import drive_evidence as evidence
from cndrivetrust.health import build_summary
from cndrivetrust.reports import render_html, render_terminal, write_bundle


def values(**items):
    return {name: evidence.value_record(value, "fixture") for name, value in items.items()}


def current(profile):
    return {
        "target": {
            "device_path": "/dev/nvme9n1",
            "model": profile.pop("model", "Samsung PM9A3"),
            "serial": profile.pop("serial", "TEST-SERIAL"),
            "firmware": profile.pop("firmware", "GDC51C2Q"),
            "capacity_bytes": profile.pop("capacity_bytes", 960_197_124_096),
            "transport": "NATIVE_NVME",
        },
        "values": values(**profile),
    }


class HealthSummaryTests(unittest.TestCase):
    def make(self, profile, last=None):
        return build_summary(current(dict(profile)), last_result=last, run_id="HEALTH-TEST", observed_utc="2026-09-24T00:00:00Z")

    def test_history_inconsistent_samsung_profile_requires_review(self):
        summary = self.make({
            "smart_health": "PASSED", "critical_warning": 0, "available_spare": 100,
            "percentage_used": 6, "vendor_media_wear_percent": 6,
            "power_on_hours": 1, "vendor_workload_timer_minutes": 111,
            "data_units_written": 0, "host_write_commands": 0,
            "power_cycles": 5, "unsafe_shutdowns": 4,
            "nand_erase_cycles_minimum": 468, "nand_erase_cycles_average": 468,
            "nand_erase_cycles_maximum": 469, "media_errors": 0,
            "program_fail_count": 0, "erase_fail_count": 0,
        })
        self.assertEqual(summary["dimensions"]["media_health"]["state"], "GOOD")
        self.assertEqual(summary["dimensions"]["history_trust"]["state"], "REVIEW_REQUIRED")
        self.assertEqual(summary["dimensions"]["history_trust"]["code"], "HISTORY_CONTINUITY_BROKEN")
        self.assertNotIn("fraud", summary["dimensions"]["history_trust"]["explanation"].lower())

    def test_lightly_used_consistent_profile(self):
        # 1.46 TB / 512,000 bytes per NVMe data unit.
        summary = self.make({
            "smart_health": "PASSED", "critical_warning": 0, "percentage_used": 0,
            "vendor_media_wear_percent": 0, "power_on_hours": 52,
            "vendor_workload_timer_minutes": 3140, "data_units_written": 2_851_563,
            "host_write_commands": 62_213_808, "power_cycles": 72,
            "unsafe_shutdowns": 54, "nand_erase_cycles_minimum": 2,
            "nand_erase_cycles_average": 2, "nand_erase_cycles_maximum": 6,
            "media_errors": 0, "program_fail_count": 0, "erase_fail_count": 0,
        })
        self.assertEqual(summary["dimensions"]["media_health"]["state"], "GOOD")
        self.assertEqual(summary["dimensions"]["history_trust"]["state"], "CONSISTENT")
        self.assertEqual(summary["dimensions"]["usage"]["state"], "LIGHT")
        self.assertIn("TB", summary["usage_display"]["host_writes"])

    def test_near_new_minimal_use_profile(self):
        summary = self.make({
            "smart_health": "PASSED", "critical_warning": 0, "percentage_used": 0,
            "vendor_media_wear_percent": 0, "power_on_hours": 0,
            "vendor_workload_timer_minutes": 2, "data_units_written": 0,
            "host_write_commands": 0, "power_cycles": 3, "unsafe_shutdowns": 1,
            "nand_erase_cycles_minimum": 0, "nand_erase_cycles_average": 0,
            "nand_erase_cycles_maximum": 1, "media_errors": 0,
        })
        history = summary["dimensions"]["history_trust"]
        self.assertEqual(history["state"], "CONSISTENT")
        self.assertEqual(history["code"], "CONSISTENT_MINIMAL_USE_PROFILE")
        self.assertIn("Factory sealed", history["not_established"])

    def test_missing_vendor_log_is_partial_not_failure(self):
        summary = self.make({
            "smart_health": "PASSED", "critical_warning": 0, "percentage_used": 0,
            "power_on_hours": 12, "data_units_written": 2000, "media_errors": 0,
        })
        self.assertEqual(summary["dimensions"]["history_trust"]["state"], "PARTIAL")
        self.assertEqual(summary["dimensions"]["history_trust"]["code"], "VENDOR_WEAR_UNAVAILABLE")

    def test_unsupported_smart_field_remains_unavailable(self):
        summary = self.make({"smart_health": None, "critical_warning": None})
        self.assertEqual(summary["dimensions"]["media_health"]["state"], "PARTIAL")
        self.assertEqual(summary["dimensions"]["error_state"]["state"], "UNAVAILABLE")

    def test_query_failure_is_not_zero_or_good(self):
        profile = current({"smart_health": None, "critical_warning": None})
        profile["values"]["media_errors"] = {
            "value": None, "status": "QUERY_FAILED", "source": "fixture", "time": "now",
        }
        summary = build_summary(profile, run_id="HEALTH-TEST", observed_utc="now")
        self.assertEqual(summary["dimensions"]["error_state"]["state"], "QUERY_FAILED")

    def test_last_full_read_is_labeled_historical(self):
        summary = self.make({"smart_health": "PASSED", "critical_warning": 0}, last={
            "run_id": "RUN-OLD",
            "read_verification": {
                "status": "VERIFIED",
                "scan": {"throughput_bytes_per_second": 2_800_000_000, "bytes_read": 960_197_124_096},
            },
        })
        performance = summary["dimensions"]["performance"]
        self.assertEqual(performance["state"], "VERIFIED")
        self.assertEqual(performance["evidence"]["source_run_id"], "RUN-OLD")

    def test_terminal_and_html_escape_identity(self):
        summary = self.make({"model": "<script>", "smart_health": "PASSED", "critical_warning": 0})
        self.assertIn("CURRENT MEDIA HEALTH", render_terminal(summary))
        rendered = render_html(summary)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_report_bundle_json_html_manifest_and_hashes(self):
        summary = self.make({"smart_health": "PASSED", "critical_warning": 0, "media_errors": 0})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bundle"
            write_bundle(root, summary, {"smart": {"status": "OK", "stdout": "health", "stderr": ""}})
            parsed = json.loads((root / "normalized" / "health-summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(parsed["artifact_type"], "CNDRIVETRUST_HEALTH_USAGE_SUMMARY")
            self.assertIn("CNDriveTrust", (root / "reports" / "health-summary.html").read_text(encoding="utf-8"))
            self.assertTrue(any(item["path"] == "reports/health-summary.html" for item in manifest["files"]))
            self.assertTrue((root / "checksums.sha256").stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()

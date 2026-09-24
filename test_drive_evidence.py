import unittest
from unittest.mock import patch

import drive_evidence as app


class EvidenceRulesTests(unittest.TestCase):
    def test_parse_json_output_keeps_controller_capabilities(self):
        record = {"status": "OK", "stdout": '{"lpa":14,"pels":0}'}
        self.assertEqual(app.parse_json_output(record), {"lpa": 14, "pels": 0})

    def test_nvme_version_register_decodes_to_dotted_version(self):
        self.assertEqual(app.decode_nvme_version(66560), "1.4")
        self.assertEqual(app.decode_nvme_version("0x10401"), "1.4.1")

    def test_optional_nvme_selftest_query_is_partial_when_health_passes(self):
        records = {
            "smartctl-text": {
                "returncode": 4,
                "status": "QUERY_FAILED",
                "stdout": "SMART overall-health self-assessment test result: PASSED\\nRead Self-test Log failed: Invalid Field in Command (0x002)",
            },
            "smartctl-json": {
                "returncode": 4,
                "status": "QUERY_FAILED",
                "stdout": '{"smart_status":{"passed":true},"nvme_smart_health_information_log":{"critical_warning":0}}',
            },
        }
        app.classify_smartctl_optional_selftest(records)
        self.assertEqual(records["smartctl-text"]["status"], "PARTIAL")
        self.assertEqual(records["smartctl-json"]["status"], "PARTIAL")
        self.assertEqual(records["smartctl-json"]["returncode"], 4)
        self.assertIn("not a health failure", records["smartctl-json"]["status_reason"])

    def test_smartctl_health_failure_is_not_downgraded_to_partial(self):
        records = {
            "smartctl-text": {
                "returncode": 4,
                "status": "QUERY_FAILED",
                "stdout": "Read Self-test Log failed: Invalid Field in Command (0x002)",
            },
            "smartctl-json": {
                "returncode": 4,
                "status": "QUERY_FAILED",
                "stdout": '{"smart_status":{"passed":false},"nvme_smart_health_information_log":{"critical_warning":1}}',
            },
        }
        app.classify_smartctl_optional_selftest(records)
        self.assertEqual(records["smartctl-json"]["status"], "QUERY_FAILED")

    def test_invalid_log_page_is_unsupported_not_query_failed(self):
        self.assertEqual(app.command_status(1, "NVMe status: Invalid Log Page", True), "UNSUPPORTED")

    def test_zero_error_log_slots_are_semantically_empty(self):
        entries = [{"error_count": 0}, {"error_count": 0}]
        record = {"status": "OK", "stdout": __import__("json").dumps({"errors": entries})}
        normalized = app.normalize_error_log(record)
        self.assertEqual(normalized["status"], "EMPTY")
        self.assertEqual(normalized["value"], [])
        self.assertEqual(normalized["reported_slots"], 2)

    def test_missing_error_log_payload_is_query_failed_not_empty(self):
        normalized = app.normalize_error_log({"status": "OK", "stdout": '{"unexpected":[]}'} )
        self.assertEqual(normalized["status"], "QUERY_FAILED")

    def test_unsupported_pel_is_not_queried(self):
        record = {"status": "OK", "stdout": '{"lpa":14,"pels":0}'}
        with patch.object(app, "run_command") as run:
            result = app.collect_persistent_event_log("/dev/nvme0", record)
        self.assertEqual(result["nvme-persistent-event-log"]["status"], "UNSUPPORTED")
        run.assert_not_called()

    def test_supported_empty_pel_is_read_and_context_released(self):
        header = bytearray(512)
        header[0] = 0x0D
        header[8:16] = (512).to_bytes(8, "little")
        header[16] = 1

        def fake_command(argv, timeout=90, binary_stdout=False):
            record = {"argv": argv, "returncode": 0, "status": "OK", "stdout": "", "stderr": ""}
            if binary_stdout:
                record["stdout_bytes"] = bytes(header)
                record["stdout_binary"] = True
            return record

        id_ctrl = {"status": "OK", "stdout": '{"lpa":30,"pels":65536}'}
        with patch.object(app, "run_command", side_effect=fake_command) as run:
            records = app.collect_persistent_event_log("/dev/nvme0", id_ctrl)
        self.assertEqual(records["nvme-persistent-event-log"]["status"], "OK")
        self.assertEqual(records["nvme-persistent-event-log"]["pel_total_events"], 0)
        self.assertEqual(records["nvme-pel-context-release"]["status"], "OK")
        self.assertEqual(run.call_count, 4)

    def test_boot_disk_ancestry_is_protected(self):
        inverse = {
            "/dev/sda2": '{"blockdevices":[{"name":"/dev/sda2","type":"part","children":[{"name":"/dev/sda","type":"disk"}]}]}',
            "/dev/sda1": '{"blockdevices":[{"name":"/dev/sda1","type":"part","children":[{"name":"/dev/sda","type":"disk"}]}]}',
        }
        protected, errors = app.resolve_protected_disks(
            {"/": "/dev/sda2", "/boot/efi": "/dev/sda1"},
            inverse,
        )
        self.assertEqual(protected, {"/dev/sda"})
        self.assertEqual(errors, [])

    def test_capture_global_evidence_records_detected_protected_disks(self):
        block_payload = '{"blockdevices":[{"path":"/dev/nvme0n1","type":"disk"}]}'
        with patch.object(app, "run_command", return_value={"status": "OK", "stdout": block_payload}), \
             patch.object(
                 app,
                 "detect_protection",
                 return_value=(
                     {"/dev/sda"},
                     {"/": "/dev/sda2", "/boot/efi": "/dev/sda1"},
                     {"/": {"returncode": 0, "status": "OK", "stdout": "/dev/sda2"}},
                     [],
                 ),
             ):
            _, _, protection_records = app.capture_global_evidence()
        self.assertEqual(protection_records[0]["protected_disks"], ["/dev/sda"])

    def test_controller_identity_is_trimmed_and_version_normalized(self):
        disk = {"device_path": "/dev/nvme0n1", "path": "/dev/nvme0n1", "model": "Samsung", "serial": "sn"}
        records = {
            "nvme-id-ctrl": {"status": "OK", "stdout": '{"mn":"Samsung PM9A3    ","sn":"ABC123   ","fr":"GDC51C2Q","vid":5197,"ver":66560}'},
            "nvme-id-ns": {"status": "OK", "stdout": "{}"},
            "nvme-smart-log": {"status": "OK", "stdout": "{}"},
            "smartctl-json": {"status": "OK", "stdout": "{}"},
        }
        normalized = app.normalize_device(disk, records, "ABC123", "now")
        self.assertEqual(app.value_value(normalized["values"], "model"), "Samsung PM9A3")
        self.assertEqual(app.value_value(normalized["values"], "serial"), "ABC123")
        self.assertEqual(app.value_value(normalized["values"], "nvme_version"), "1.4")

    def test_ambiguous_root_fails_closed(self):
        protected, errors = app.resolve_protected_disks(
            {"/": "overlay", "/boot/efi": "/dev/sda1"},
            {"/dev/sda1": '{"blockdevices":[{"name":"/dev/sda1","type":"part","children":[{"name":"/dev/sda","type":"disk"}]}]}'},
        )
        self.assertEqual(protected, {"/dev/sda"})
        self.assertTrue(errors)

    def test_zero_is_distinct_from_unavailable(self):
        observed_zero = app.value_record(0, "test")
        missing = app.value_record(None, "test")
        self.assertEqual(observed_zero["status"], "0")
        self.assertEqual(missing["status"], "UNAVAILABLE")

    def test_counter_anomaly_is_review_not_accusation(self):
        values = {
            "percentage_used": app.value_record(6, "nvme smart-log"),
            "power_on_hours": app.value_record(0, "nvme smart-log"),
            "data_units_written": app.value_record(0, "nvme smart-log"),
            "power_cycles": app.value_record(3, "nvme smart-log"),
            "unsafe_shutdowns": app.value_record(0, "nvme smart-log"),
        }
        result = app.analyze_telemetry(values)
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(result["disposition"], "REVIEW_REQUIRED")
        self.assertIn("LIFETIME_HISTORY_DISCONTINUITY", codes)
        self.assertNotIn("FRAUD", codes)

    @staticmethod
    def samsung_ca_record(*, minimum=0, maximum=1, average=0, wear=0, minutes=2):
        data = bytearray(512)
        entries = {
            0: (0xAB, 0), 12: (0xAC, 0), 24: (0xAD, None), 36: (0xB8, 0),
            48: (0xC7, 0), 60: (0xE2, wear), 72: (0xE3, 100), 84: (0xE4, minutes),
            96: (0xEA, 100), 128: (0xF4, 0), 140: (0xF5, 0),
        }
        for offset, (attribute, raw) in entries.items():
            data[offset] = attribute
            data[offset + 3] = 100 if attribute != 0xAD else max(0, 100 - wear)
            if attribute == 0xAD:
                data[offset + 5:offset + 7] = minimum.to_bytes(2, "little")
                data[offset + 7:offset + 9] = maximum.to_bytes(2, "little")
                data[offset + 9:offset + 11] = average.to_bytes(2, "little")
            else:
                data[offset + 5:offset + 12] = int(raw).to_bytes(7, "little")
        return {"status": "OK", "stdout_bytes": bytes(data), "stderr": ""}

    def test_samsung_extended_smart_decodes_erase_cycles(self):
        result = app.parse_samsung_extended_smart(
            self.samsung_ca_record(minimum=468, maximum=469, average=468, wear=6, minutes=111)
        )
        self.assertEqual(result["status"], "VALUE")
        self.assertEqual(result["values"]["nand_erase_cycles_average"], 468)
        self.assertEqual(result["values"]["vendor_media_wear_percent"], 6)
        self.assertEqual(result["values"]["vendor_workload_timer_minutes"], 111)

    def test_coherent_near_new_profile_is_not_review(self):
        values = {
            "percentage_used": app.value_record(0, "nvme"),
            "vendor_media_wear_percent": app.value_record(0, "samsung"),
            "power_on_hours": app.value_record(0, "nvme"),
            "vendor_workload_timer_minutes": app.value_record(2, "samsung"),
            "data_units_written": app.value_record(0, "nvme"),
            "host_write_commands": app.value_record(0, "nvme"),
            "power_cycles": app.value_record(3, "nvme"),
            "unsafe_shutdowns": app.value_record(1, "nvme"),
            "nand_erase_cycles_minimum": app.value_record(0, "samsung"),
            "nand_erase_cycles_average": app.value_record(0, "samsung"),
            "nand_erase_cycles_maximum": app.value_record(1, "samsung"),
            "global_data_erased": app.value_record(True, "sanitize"),
        }
        result = app.analyze_telemetry(values)
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(result["disposition"], "CONSISTENT")
        self.assertIn("COHERENT_NEAR_NEW_TELEMETRY", codes)
        self.assertIn("POWER_CYCLES_WITH_SUB_HOUR_RUNTIME", codes)

    def test_physical_wear_with_zero_writes_is_review(self):
        values = {
            "percentage_used": app.value_record(6, "nvme"),
            "vendor_media_wear_percent": app.value_record(6, "samsung"),
            "power_on_hours": app.value_record(1, "nvme"),
            "vendor_workload_timer_minutes": app.value_record(111, "samsung"),
            "data_units_written": app.value_record(0, "nvme"),
            "host_write_commands": app.value_record(0, "nvme"),
            "power_cycles": app.value_record(5, "nvme"),
            "unsafe_shutdowns": app.value_record(4, "nvme"),
            "nand_erase_cycles_minimum": app.value_record(468, "samsung"),
            "nand_erase_cycles_average": app.value_record(468, "samsung"),
            "nand_erase_cycles_maximum": app.value_record(469, "samsung"),
            "global_data_erased": app.value_record(True, "sanitize"),
        }
        result = app.analyze_telemetry(values)
        codes = {item["code"] for item in result["findings"]}
        self.assertEqual(result["disposition"], "REVIEW_REQUIRED")
        self.assertIn("LIFETIME_HISTORY_DISCONTINUITY", codes)
        self.assertIn("BLANK_STATE_VS_MEDIA_WEAR_CONFLICT", codes)

    def test_used_below_one_percent_is_observation(self):
        values = {
            "percentage_used": app.value_record(0, "nvme"),
            "vendor_media_wear_percent": app.value_record(0, "samsung"),
            "power_on_hours": app.value_record(52, "nvme"),
            "vendor_workload_timer_minutes": app.value_record(3140, "samsung"),
            "data_units_written": app.value_record(2843445, "nvme"),
            "host_write_commands": app.value_record(62213808, "nvme"),
            "power_cycles": app.value_record(72, "nvme"),
            "unsafe_shutdowns": app.value_record(54, "nvme"),
            "nand_erase_cycles_minimum": app.value_record(2, "samsung"),
            "nand_erase_cycles_average": app.value_record(2, "samsung"),
            "nand_erase_cycles_maximum": app.value_record(6, "samsung"),
            "global_data_erased": app.value_record(False, "sanitize"),
        }
        result = app.analyze_telemetry(values)
        self.assertEqual(result["disposition"], "CONSISTENT")
        self.assertIn("USED_BELOW_ONE_PERCENT_WEAR", {item["code"] for item in result["findings"]})

    def test_full_read_counter_delta_is_verified(self):
        capacity = 960197124096
        expected_units = (capacity + app.NVME_DATA_UNIT_BYTES - 1) // app.NVME_DATA_UNIT_BYTES
        values = {
            name: app.value_record(value, "before") for name, value in {
                "data_units_read": 3, "data_units_written": 0, "host_read_commands": 53,
                "host_write_commands": 0, "critical_warning": 0, "media_errors": 0,
                "num_err_log_entries": 0, "nand_erase_cycles_minimum": 0,
                "nand_erase_cycles_average": 0, "nand_erase_cycles_maximum": 1,
                "vendor_workload_timer_minutes": 2,
            }.items()
        }
        records = {
            "full-capacity-read": {"status": "OK", "complete": True, "expected_bytes": capacity, "bytes_read": capacity, "elapsed_seconds": 320},
            "post-nvme-smart-log": {"status": "OK", "stdout": __import__("json").dumps({
                "data_units_read": 3 + expected_units, "data_units_written": 0,
                "host_read_commands": 7000000, "host_write_commands": 0,
                "critical_warning": 0, "media_errors": 0, "num_err_log_entries": 0,
            })},
            "post-samsung-extended-smart-0xca": self.samsung_ca_record(minimum=0, maximum=1, average=0, wear=0, minutes=8),
        }
        result = app.analyze_read_verification(records, values)
        self.assertEqual(result["status"], "VERIFIED")
        self.assertTrue(result["read_counter_coherent"])

    def test_sanitize_global_data_erased_is_decoded(self):
        record = {"status": "OK", "stdout": "Sanitize Status (SSTAT) : 0x100\n", "stderr": ""}
        result = app.parse_sanitize_log(record)
        self.assertTrue(result["value"]["global_data_erased"])
        self.assertTrue(result["value"]["never_sanitized"])

    def test_nvme_transport_detected_by_path(self):
        transport, _ = app.classify_transport({"path": "/dev/nvme0n1", "tran": None})
        self.assertEqual(transport, "NATIVE_NVME")

    def test_html_escapes_device_fields(self):
        sample = {
            "run_id": "RUN-x",
            "po_batch": "<bad>",
            "completed_utc": "now",
            "target": {"device_path": "/dev/a", "model": "<script>", "serial": "s"},
            "values": {},
            "analysis": {"disposition": "INSUFFICIENT_EVIDENCE", "findings": [], "interpretation": "none"},
            "export": {"status": "PENDING_EXPORT"},
            "warnings": [],
        }
        rendered = app.render_html(sample)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)


if __name__ == "__main__":
    unittest.main()

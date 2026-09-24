import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class MenuIntegrationTests(unittest.TestCase):
    def text(self, name):
        return (ROOT / "integration" / name).read_text(encoding="utf-8")

    def test_top_level_routes_products_only(self):
        text = self.text("cngpu-production-countdown-menu")
        self.assertIn("Dell Server Program", text)
        self.assertIn("CNDriveTrust / Drive Tools", text)
        self.assertIn("/usr/local/bin/cngpu-dell-server-menu", text)
        self.assertIn("/usr/local/bin/cngpu-drive-tools-menu", text)

    def test_dell_options_and_back_navigation_preserved(self):
        text = self.text("cngpu-dell-server-menu")
        for label in ("Update firmware + hardware test", "Update firmware only", "Hardware test only", "Burn-in test"):
            self.assertIn(label, text)
        self.assertIn("[Bb])", text)

    def test_drive_menu_routes_all_four_entries(self):
        text = self.text("cngpu-drive-tools-menu")
        for label in ("Test Disk", "Health & Usage Summary", "Erase / Sanitize", "CNDriveAI"):
            self.assertIn(label, text)
        for command in (
            "cngpu-drive-evidence-test", "cngpu-drive-health-summary",
            "cngpu-drive-erase-capabilities", "cngpu-drive-ai-placeholder",
        ):
            self.assertIn(command, text)
        self.assertIn("[Bb])", text)

    def test_menu_contains_no_destructive_invocation(self):
        text = self.text("cngpu-drive-tools-menu").lower()
        for invocation in ("nvme sanitize", "nvme format", "sg_sanitize", "security-erase", "blkdiscard", "dd if="):
            self.assertNotIn(invocation, text)


if __name__ == "__main__":
    unittest.main()


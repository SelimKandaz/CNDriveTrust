import unittest

from cndrivetrust.ai import STATUS
from cndrivetrust.ai.interface import contract
from cndrivetrust.ai.placeholder import render


class AIContractTests(unittest.TestCase):
    def test_ai_is_not_installed_or_required(self):
        data = contract()
        self.assertEqual(STATUS, "NOT_INSTALLED")
        self.assertEqual(data["status"], "NOT_INSTALLED")
        self.assertFalse(data["model_installed"])
        self.assertFalse(data["inference_runtime_installed"])
        self.assertFalse(data["core_dependency"])

    def test_ai_has_no_destructive_or_deployment_authority(self):
        prohibited = set(contract()["prohibited_authority"])
        self.assertIn("select_erase_target", prohibited)
        self.assertIn("bypass_boot_drive_protection", prohibited)
        self.assertIn("execute_erase_or_sanitize", prohibited)
        self.assertIn("deploy_production_code", prohibited)

    def test_placeholder_is_explicit(self):
        text = render()
        self.assertIn("NOT INSTALLED", text)
        self.assertIn("No AI model or inference runtime", text)


if __name__ == "__main__":
    unittest.main()


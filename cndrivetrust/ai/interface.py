"""Machine-readable future CNDriveAI authority boundary."""

from __future__ import annotations

from typing import Any

READABLE_INPUTS = (
    "normalized_cndrivetrust_json",
    "report_manifests",
    "raw_evidence_when_explicitly_requested",
    "project_documentation",
    "source_code",
    "known_issue_and_runbook_documentation",
    "preserved_previous_reports",
)

ALLOWED_OUTPUTS = (
    "explanations",
    "diagnostic_suggestions",
    "drive_comparisons",
    "code_suggestions",
    "patch_files_in_staging_only",
)

PROHIBITED_AUTHORITY = (
    "select_erase_target",
    "bypass_boot_drive_protection",
    "execute_erase_or_sanitize",
    "format_drive",
    "modify_namespaces",
    "flash_firmware",
    "deploy_production_code",
)


def contract() -> dict[str, Any]:
    return {
        "component": "CNDriveAI",
        "status": "NOT_INSTALLED",
        "optional": True,
        "core_dependency": False,
        "readable_inputs": list(READABLE_INPUTS),
        "allowed_outputs": list(ALLOWED_OUTPUTS),
        "prohibited_authority": list(PROHIBITED_AUTHORITY),
        "future_data_root": "/var/lib/cndriveai/",
        "model_installed": False,
        "inference_runtime_installed": False,
    }


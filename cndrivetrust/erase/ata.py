"""Conservative ATA security/sanitize capability parsing."""

from __future__ import annotations

import re
from typing import Any


def parse_identify(text: str, query_status: str = "OK") -> dict[str, Any]:
    if query_status != "OK":
        return {
            "protocol": "ATA",
            "query_status": query_status,
            "security_feature": "UNKNOWN",
            "secure_erase": "UNKNOWN",
            "enhanced_secure_erase": "UNKNOWN",
            "frozen_state": "UNKNOWN",
            "sanitize_feature": "UNKNOWN",
            "execution": "DISABLED",
        }
    lowered = text.lower()
    security_supported = bool(re.search(r"\bsecurity:\s*(?:\n|\r\n).*?\bsupported\b", lowered, re.S))
    frozen = bool(re.search(r"\bfrozen\b", lowered)) and not bool(re.search(r"\bnot\s+frozen\b", lowered))
    enhanced = bool(re.search(r"enhanced security erase", lowered))
    secure = security_supported and bool(re.search(r"security erase", lowered))
    sanitize = "sanitize feature set" in lowered
    return {
        "protocol": "ATA",
        "query_status": "OK",
        "security_feature": "SUPPORTED" if security_supported else "NOT_REPORTED",
        "secure_erase": "SUPPORTED" if secure else "NOT_REPORTED",
        "enhanced_secure_erase": "SUPPORTED" if enhanced else "NOT_REPORTED",
        "frozen_state": "FROZEN" if frozen else ("NOT_FROZEN" if "not frozen" in lowered else "UNKNOWN"),
        "sanitize_feature": "SUPPORTED" if sanitize else "NOT_REPORTED",
        "execution": "DISABLED",
    }


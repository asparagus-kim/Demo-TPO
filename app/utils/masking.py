"""Masking for personal data that may reach a page or a URL.

APICK returns the 대표명 (representative name) and 전화번호 (registered phone).
For a sole proprietor both are personal data, so only these masked forms ever
leave the server — the lead format of the spec (명세 5장): 「김**」 · 「010-****-5678」.
"""
from __future__ import annotations

import re


def mask_name(name: str | None) -> str:
    """'김민수' -> '김**'. Empty stays empty."""
    n = (name or "").strip()
    return n[0] + "*" * (len(n) - 1) if len(n) > 1 else n


def mask_phone(phone: str | None) -> str:
    """'010-1234-5678' -> '010-****-5678' · '02-123-4567' -> '02-****-4567'.
    Anything that is not a plausible Korean number is dropped, not echoed."""
    d = re.sub(r"\D", "", phone or "")
    if not 9 <= len(d) <= 11 or not d.startswith("0"):
        return ""
    prefix = "02" if d.startswith("02") else d[:3]
    return f"{prefix}-****-{d[-4:]}"

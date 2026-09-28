"""Phone number helpers shared by donor sign-in and registration."""

from __future__ import annotations

import re
from typing import Optional


def normalise_phone(raw: str) -> Optional[str]:
    """
    Return the number in E.164 form, or None if it is not plausible.
    Ten bare digits are treated as an Indian mobile number.
    """
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        return f"+{digits}" if 10 <= len(digits) <= 15 else None
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return None

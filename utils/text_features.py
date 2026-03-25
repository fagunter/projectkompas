"""Keyword extraction from free-text remarks (opmerkingen)."""

from __future__ import annotations

import re

RISK_KEYWORDS: list[str] = [
    "vertraging",
    "afhankelijkheid",
    "scope creep",
    "overrun",
    "non-compliance",
    "incident",
    "geblokkeerd",
    "rework",
    "escalatie",
]

_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in RISK_KEYWORDS), re.IGNORECASE
)


def extract_keywords(text: str | None) -> list[str]:
    """Return deduplicated list of risk keywords found in *text*."""
    if not text or not isinstance(text, str):
        return []
    found = _PATTERN.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for kw in found:
        lower = kw.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(lower)
    return result


def keyword_flag_count(text: str | None) -> int:
    """Return the number of unique risk keywords found in *text*."""
    return len(extract_keywords(text))

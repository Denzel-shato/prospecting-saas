"""Shared, deterministic wording hints for DISCOVERY-RECORD text (directory taglines, profile excerpts).

These flags only help Engine #2 order research; they are never qualification evidence. Shared here so every
directory-style adapter reads software-vs-marketing identity wording the same way.
"""
from __future__ import annotations

import re

SOFTWARE_FOCUS = re.compile(
    r"\b(?:custom software|bespoke software|software development|software solutions|"
    r"software studio|software agency|software consultancy|product studio|"
    r"product development|app development|app developers|development studio)\b", re.I)
MARKETING_FOCUS = re.compile(
    r"\b(?:seo|marketing|branding|advertising|social media|lead generation)\b", re.I)


def identity_hints(*texts: str) -> dict:
    """{'software': bool, 'marketing': bool} for a company's OWN identity wording (name/tagline/excerpt)."""
    wording = " ".join(t for t in texts if isinstance(t, str))
    return {"software": bool(SOFTWARE_FOCUS.search(wording)), "marketing": bool(MARKETING_FOCUS.search(wording))}

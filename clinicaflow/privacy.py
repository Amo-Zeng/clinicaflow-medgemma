from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# Lightweight PHI/PII detection + external-call guard (demo-safe defaults)
# ---------------------------------------------------------------------------
#
# This repository is a competition/demo scaffold and must never encourage
# sending real patient identifiers to third-party endpoints by default.
#
# We use **best-effort heuristics**: they are not comprehensive and can yield
# false positives/negatives. The goal is to provide a practical "privacy
# guardrail" that blocks obvious identifiers from leaving the machine.


PHI_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("phone", re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("mrn", re.compile(r"\b(?:mrn|medical\s*record\s*(?:number|no\.?))\b\s*[:#-]?\s*\d{5,}\b", re.IGNORECASE)),
    (
        "dob",
        re.compile(
            r"\b(?:dob|date\s*of\s*birth)\b\s*[:#-]?\s*(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
            re.IGNORECASE,
        ),
    ),
]


def detect_phi_hits(text: str) -> list[str]:
    """Return a list of detected PHI pattern names.

    The returned values are category labels only (no extracted identifiers).
    """

    raw = str(text or "")
    if not raw.strip():
        return []

    hits: list[str] = []
    for name, pat in PHI_PATTERNS:
        if pat.search(raw):
            hits.append(name)

    # Stable, deduped ordering.
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h in seen:
            continue
        seen.add(h)
        out.append(h)
    return out


def phi_guard_enabled() -> bool:
    """Return True if external calls should be blocked when PHI is detected."""

    raw = os.environ.get("CLINICAFLOW_PHI_GUARD", "1")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def external_calls_allowed(*, phi_hits: list[str]) -> bool:
    """Return True if it's OK to call external backends for this intake."""

    if not phi_hits:
        return True
    return not phi_guard_enabled()

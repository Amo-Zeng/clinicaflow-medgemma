from __future__ import annotations

import re

_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)


def normalize_text(text: str) -> str:
    """Normalize common Unicode punctuation for robust matching."""
    return text.translate(_TRANSLATION)


_INJECTION_LINE_PATTERNS = [
    r"^\s*(system|developer|assistant)\s*:",
    r"\b(ignore|disregard)\b.{0,40}\b(previous|above)\b.{0,20}\b(instruction|message)s?\b",
    r"\breturn\s+only\s+json\b",
    r"\boutput\s*\{",
]


def sanitize_untrusted_text(text: str, *, max_chars: int = 1200) -> str:
    """Remove high-confidence prompt-injection style lines from untrusted text.

    This is intentionally conservative and only removes lines that look like
    prompt-structure instructions (SYSTEM/DEVELOPER/ASSISTANT) or explicit
    "ignore previous instructions" patterns. The raw intake is still preserved
    in the audit bundle; this sanitized variant is used for model prompting.
    """

    raw = normalize_text(text or "")
    if not raw.strip():
        return ""

    kept: list[str] = []
    for line in raw.splitlines():
        l = line.strip()
        if not l:
            continue
        if any(re.search(pat, l, flags=re.IGNORECASE) for pat in _INJECTION_LINE_PATTERNS):
            continue
        kept.append(l)

    out = "\n".join(kept).strip()
    if not out:
        return ""
    return out[: max(0, int(max_chars))]

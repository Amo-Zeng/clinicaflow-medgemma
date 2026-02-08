from __future__ import annotations


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


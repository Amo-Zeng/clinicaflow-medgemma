from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from clinicaflow.text import normalize_text


@dataclass(frozen=True, slots=True)
class PolicySnippet:
    policy_id: str
    title: str
    triggers: list[str]
    recommended_actions: list[str]
    citation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_policy_pack(path: Any) -> list[PolicySnippet]:
    payload = json.loads(_read_text(path))
    snippets = []
    for item in payload.get("policies", []):
        snippets.append(
            PolicySnippet(
                policy_id=str(item["policy_id"]),
                title=str(item["title"]),
                triggers=[str(x) for x in item.get("triggers", [])],
                recommended_actions=[str(x) for x in item.get("recommended_actions", [])],
                citation=str(item.get("citation", "")),
            )
        )
    return snippets


def policy_pack_sha256(path: Any) -> str:
    """Stable digest for governance/audit logs."""
    return hashlib.sha256(_read_bytes(path)).hexdigest()


def match_policies(policies: list[PolicySnippet], *, text: str) -> list[PolicySnippet]:
    text_l = normalize_text(text).lower()
    hits: list[tuple[int, PolicySnippet]] = []
    for policy in policies:
        score = sum(1 for trigger in policy.triggers if normalize_text(trigger).lower() in text_l)
        if score:
            hits.append((score, policy))
    hits.sort(key=lambda x: (-x[0], x[1].policy_id))
    return [p for _, p in hits]


def _read_text(path: Any) -> str:
    if isinstance(path, (str, Path)):
        return Path(path).read_text(encoding="utf-8")
    if hasattr(path, "read_text"):
        try:
            return path.read_text(encoding="utf-8")
        except TypeError:
            return path.read_text()
    if hasattr(path, "open"):
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    raise TypeError(f"Unsupported policy pack path type: {type(path)!r}")


def _read_bytes(path: Any) -> bytes:
    if isinstance(path, (str, Path)):
        return Path(path).read_bytes()
    if hasattr(path, "read_bytes"):
        return path.read_bytes()
    if hasattr(path, "open"):
        with path.open("rb") as f:
            return f.read()
    raise TypeError(f"Unsupported policy pack path type: {type(path)!r}")

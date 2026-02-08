from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PolicySnippet:
    policy_id: str
    title: str
    triggers: list[str]
    recommended_actions: list[str]
    citation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_policy_pack(path: str | Path) -> list[PolicySnippet]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
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


def match_policies(policies: list[PolicySnippet], *, text: str) -> list[PolicySnippet]:
    text_l = text.lower()
    hits: list[tuple[int, PolicySnippet]] = []
    for policy in policies:
        score = sum(1 for trigger in policy.triggers if trigger.lower() in text_l)
        if score:
            hits.append((score, policy))
    hits.sort(key=lambda x: (-x[0], x[1].policy_id))
    return [p for _, p in hits]


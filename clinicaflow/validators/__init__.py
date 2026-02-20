"""Lightweight validators for packaged resources (vignettes, policy packs).

Why this exists:
- The demo UI and benchmarks depend on JSON/JSONL resources shipped with the package.
- A small validator makes it much harder to accidentally ship a broken writeup pack
  or a demo server that only works on the author's machine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ValidationReport:
    ok: bool
    errors: list[str]
    warnings: list[str]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_all() -> ValidationReport:
    """Validate packaged policy pack + all packaged vignette sets."""

    from clinicaflow.benchmarks.vignettes import load_default_vignette_paths
    from clinicaflow.diagnostics import resolve_policy_pack_path
    from clinicaflow.validators.policy_pack import validate_policy_pack
    from clinicaflow.validators.vignettes import validate_vignettes_jsonl

    errors: list[str] = []
    warnings: list[str] = []

    policy_path, policy_source = resolve_policy_pack_path()
    policy_path_str = str(policy_path)
    errors.extend(validate_policy_pack(policy_path))

    sets = ["standard", "adversarial", "extended", "all", "mega"]
    vignette_paths: dict[str, list[str]] = {}
    for set_name in sets:
        paths = [Path(p) for p in load_default_vignette_paths(set_name)]
        vignette_paths[set_name] = [str(p) for p in paths]
        for p in paths:
            errors.extend(validate_vignettes_jsonl(p))

    ok = len(errors) == 0
    return ValidationReport(
        ok=ok,
        errors=errors,
        warnings=warnings,
        meta={
            "policy_pack_source": policy_source,
            "policy_pack_path": policy_path_str,
            "vignette_paths": vignette_paths,
        },
    )


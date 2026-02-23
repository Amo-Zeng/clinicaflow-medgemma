from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


_DEFAULT_VERSION = "0.1.13"


def _installed_version_if_this_package() -> str | None:
    """Return the installed distribution version if it matches this code location.

    In some environments there may be another unrelated `clinicaflow` distribution
    installed. When running from a source checkout (no editable install), prefer
    the repo's default version instead of reporting an unrelated dist version.
    """

    try:
        dist = distribution("clinicaflow")
    except PackageNotFoundError:
        return None

    try:
        base = Path(dist.locate_file("")).resolve()
        here = Path(__file__).resolve()
        if base == here or base in here.parents:
            ver = str(dist.version or "").strip()
            # Prefer the repo version when metadata is stale/mismatched.
            return ver if ver and ver == _DEFAULT_VERSION else None
    except Exception:  # noqa: BLE001
        return None
    return None


__version__ = _installed_version_if_this_package() or _DEFAULT_VERSION

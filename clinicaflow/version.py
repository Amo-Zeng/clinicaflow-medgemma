from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("clinicaflow")
except PackageNotFoundError:
    __version__ = "0.1.5"

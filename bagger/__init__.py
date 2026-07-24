"""bagger — AI Coding Agent Data Collector."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    # Single source of truth is the ``version`` field in pyproject.toml;
    # setuptools exposes it via package metadata at install time.
    __version__ = _pkg_version("bagger")
except PackageNotFoundError:  # pragma: no cover - bagger not installed
    __version__ = "0.0.0"

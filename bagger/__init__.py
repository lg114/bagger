"""bagger — AI Coding Agent Data Collector."""

import logging
import warnings
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# jieba 0.42.x imports pkg_resources at module load (emits a deprecation
# UserWarning) and hard-wires its own logger to DEBUG with a stderr handler —
# the first dictionary load then prints "Building prefix dict ..." twice (its
# own handler plus the root handler). Import it eagerly here so the logger
# exists, then quiet it once; every entrypoint (CLI / API / tests) imports
# this package first, so the noise is gone everywhere.
warnings.filterwarnings("ignore", message=r"pkg_resources is deprecated.*", category=UserWarning)
try:
    import jieba  # noqa: F401
except ImportError:  # pragma: no cover - optional dependency
    pass
else:
    logging.getLogger("jieba").setLevel(logging.WARNING)

try:
    # Single source of truth is the ``version`` field in pyproject.toml;
    # setuptools exposes it via package metadata at install time.
    __version__ = _pkg_version("bagger")
except PackageNotFoundError:  # pragma: no cover - bagger not installed
    __version__ = "0.0.0"

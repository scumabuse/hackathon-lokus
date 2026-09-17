"""Logging configuration and the external-call log helper."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once; quiet the chatty HTTP libraries (we log calls ourselves)."""
    global _CONFIGURED
    root = logging.getLogger()
    numeric = logging.getLevelName(level.upper())
    if not isinstance(numeric, int):
        numeric = logging.INFO
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        )
        root.addHandler(handler)
        _CONFIGURED = True
    root.setLevel(numeric)
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_external_call(
    logger: logging.Logger, service: str, url: str, status: int | str, elapsed_ms: int
) -> None:
    """One line per external call: service, URL (without keys), status, elapsed ms."""
    logger.info("%s GET %s -> %s %dms", service, url, status, elapsed_ms)

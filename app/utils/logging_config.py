"""Centralised logging setup."""

from __future__ import annotations

import logging
import sys

from app.utils.request_context import get_request_id


class _RequestIdFilter(logging.Filter):
    """Injects the current request id into every log record.

    Lets a single webhook be traced through parse → enrich → screen →
    alert by grepping one request id, instead of correlating by
    timestamp proximity across log lines.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)

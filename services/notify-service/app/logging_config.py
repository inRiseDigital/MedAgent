"""Structured JSON logging — re-exported from the shared py_common package
(Stage C). Import sites unchanged (`from app.logging_config import ...`)."""

from __future__ import annotations

from py_common.logging_config import JsonFormatter, configure_logging

__all__ = ["JsonFormatter", "configure_logging"]

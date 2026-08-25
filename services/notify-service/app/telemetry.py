"""Observability wiring — re-exported from the shared py_common package
(Stage C). Import sites unchanged (`from app.telemetry import ...`)."""

from __future__ import annotations

from py_common.telemetry import configure_telemetry

__all__ = ["configure_telemetry"]

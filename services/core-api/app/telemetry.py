"""OpenTelemetry wiring — TODO stub (10 §6).

Dependencies (opentelemetry-api/sdk, FastAPI instrumentation) are declared in
pyproject.toml so the wiring below is a drop-in during S3's observability
build-out. Until then this is an explicit no-op so every call-site exists.

TODO(S3):
- TracerProvider + OTLP exporter to the otel-collector (compose `observability`
  profile), W3C traceparent propagation from the gateway.
- FastAPIInstrumentor, HTTPXClientInstrumentor, SQLAlchemyInstrumentor,
  RedisInstrumentor auto-instrumentation.
- trace_id injection into JSON log records (logging_config.py).
- No PHI in span attributes — opaque resource IDs only (10 §6.1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def configure_telemetry(app: "FastAPI") -> None:
    """No-op until OTel wiring lands in S3."""
    _ = app

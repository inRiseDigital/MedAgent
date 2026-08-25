"""Observability wiring (10 §6) — shared across all Python services.

Exposes Prometheus metrics at `/metrics` for the observability profile's
prometheus, which scrapes `<service>:8000/metrics` and labels each series with
`service` (infra/observability/prometheus/prometheus.yml). The instrumentator
emits exactly the names the golden-signals dashboard queries —
`http_requests_total`, `http_request_duration_seconds_*` — and prometheus_client
adds the `process_*` gauges the saturation panel uses.

Set `OTEL_SDK_DISABLED=true` to skip wiring (e.g. an isolated unit-test app).

TODO(next): OTLP trace/log export to the otel-collector (tempo/loki). Kept out
for now so the default dev stack (observability profile down) emits no
exporter-connection noise; the /metrics endpoint is cheap and always safe.
No PHI in labels — method/handler/status only (10 §6.1).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import FastAPI


def configure_telemetry(app: "FastAPI") -> None:
    """Instrument the app and expose Prometheus metrics at /metrics."""
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return

    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,   # 2xx/4xx/5xx buckets for the error panel
        should_ignore_untemplated=True,    # avoid unbounded label cardinality
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

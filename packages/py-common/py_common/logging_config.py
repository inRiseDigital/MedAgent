"""Structured JSON logging (10 §6.1) — shared across all Python services.

Rules:
- Logs are structured JSON, one object per line.
- **No PHI ever** — patient references are logged as opaque resource IDs only
  (PHN/MPI UUID/ext_face_id are opaque identifiers; names, NICs, phone numbers,
  demographics payloads must never appear in a log record).
- `trace_id` correlation is attached once OTel wiring lands (py_common.telemetry).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
    "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
    "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc_type"] = record.exc_info[0].__name__
            payload["exc"] = self.formatException(record.exc_info)
        # Structured extras (e.g. logger.info("...", extra={"event_id": ...})).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_") and key not in payload:
                payload[key] = value
        return json.dumps(payload, default=str)


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    root.handlers = [handler]
    # Uvicorn's access log duplicates gateway logs; keep error channel only.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

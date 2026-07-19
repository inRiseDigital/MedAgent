"""SMS adapter interface + logging stub (real local-gateway adapter lands S5)."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SmsAdapter(Protocol):
    """Send an SMS. Implementations must not log message bodies or full numbers (no PHI)."""

    async def send_sms(self, to: str, message: str) -> None: ...


class LoggingSmsAdapter:
    """Dev/test stub: records the send without exposing PHI in logs."""

    async def send_sms(self, to: str, message: str) -> None:
        logger.info(
            "sms send (stub)",
            extra={"to_suffix": to[-3:] if len(to) >= 3 else "***", "length": len(message)},
        )

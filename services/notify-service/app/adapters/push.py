"""Web-push adapter interface + logging stub (real web push lands S5)."""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class PushAdapter(Protocol):
    """Send a push notification to a device subscription (opaque token)."""

    async def send_push(self, subscription_token: str, title: str, body: str) -> None: ...


class LoggingPushAdapter:
    """Dev/test stub: records the send without exposing PHI in logs."""

    async def send_push(self, subscription_token: str, title: str, body: str) -> None:
        logger.info(
            "push send (stub)",
            extra={"token_prefix": subscription_token[:8], "title_length": len(title)},
        )

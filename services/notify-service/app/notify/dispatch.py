"""Channel dispatch (FR-15.x). Routes a notification to the right adapter
(email → SMTP/mailpit, sms/push → logging stubs in dev). Channel preference and
consent are enforced by the caller (core-api / reminder scan), not here.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

Channel = Literal["email", "sms", "push"]


async def dispatch(app_state: Any, channel: Channel, to: str, subject: str, body: str) -> None:
    if channel == "email":
        await app_state.email_adapter.send_email(to, subject, body)
    elif channel == "sms":
        await app_state.sms_adapter.send_sms(to, f"{subject}: {body}")
    elif channel == "push":
        await app_state.push_adapter.send_push(to, subject, body)
    else:  # pragma: no cover - Literal guards this
        raise ValueError(f"unknown channel {channel}")
    logger.info("notification dispatched", extra={"channel": channel})

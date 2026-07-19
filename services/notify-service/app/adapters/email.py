"""Email adapter: SMTP stub (mailpit catches all outbound mail in dev, 10 §2.1)."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class EmailAdapter(Protocol):
    """Send an email. Implementations must not log addresses or bodies (no PHI)."""

    async def send_email(self, to: str, subject: str, body: str) -> None: ...


class SmtpEmailAdapter:
    """Plain-SMTP sender aimed at mailpit in dev.

    Uses stdlib smtplib in a worker thread to keep the event loop free; a
    production-grade async client (and TLS/auth) is an S5 concern.
    """

    def __init__(self, host: str, port: int, sender: str) -> None:
        self._host = host
        self._port = port
        self._sender = sender

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            smtp.send_message(message)

    async def send_email(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)
        logger.info("email sent (smtp stub)", extra={"subject_length": len(subject)})

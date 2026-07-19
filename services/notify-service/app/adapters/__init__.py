"""Notification channel adapters (07, FR-15.x).

S1 ships the interfaces plus logging/SMTP stubs; the real SMS gateway and web
push land in S5. Channel preference + consent checks are enforced by the
callers (core-api pipelines), not here.
"""

from app.adapters.email import EmailAdapter, SmtpEmailAdapter
from app.adapters.push import LoggingPushAdapter, PushAdapter
from app.adapters.sms import LoggingSmsAdapter, SmsAdapter

__all__ = [
    "EmailAdapter",
    "LoggingPushAdapter",
    "LoggingSmsAdapter",
    "PushAdapter",
    "SmsAdapter",
    "SmtpEmailAdapter",
]

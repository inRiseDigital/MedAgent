"""Notification send API + reminder trigger (FR-15.x)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import Principal, require_user
from app.config import Settings
from app.notify.dispatch import dispatch
from app.notify.reminders import run_reminders

router = APIRouter(prefix="/notify", tags=["notifications"])
internal_router = APIRouter(prefix="/internal/notify", tags=["notifications-internal"])


class SendRequest(BaseModel):
    channel: Literal["email", "sms", "push"]
    to: str = Field(min_length=1)
    subject: str
    body: str


@router.post("/send", status_code=202)
async def send(
    body: SendRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict[str, str]:
    await dispatch(request.app.state, body.channel, body.to, body.subject, body.body)
    return {"status": "sent"}


@internal_router.post("/reminders/run")
async def run(request: Request, force: bool = False) -> dict[str, int]:
    """Run the appointment reminder scan now (ops/tests + the scheduled loop)."""
    settings: Settings = request.app.state.settings
    return await run_reminders(settings, request.app.state, force=force)

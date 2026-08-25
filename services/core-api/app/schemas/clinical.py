"""Response schemas for referral + imaging read endpoints (A1)."""

from __future__ import annotations

from pydantic import BaseModel


# --- referrals -------------------------------------------------------------
class ReferralItem(BaseModel):
    task_id: str
    referral_ref: str | None = None
    patient_ref: str | None = None
    patient_name: str | None = None
    to_facility: str | None = None
    specialty: str | None = None
    reason: str | None = None
    priority: str | None = None
    status: str | None = None
    requested_by: str | None = None
    authored_on: str | None = None


class ReferralInbox(BaseModel):
    facility: str
    count: int
    items: list[ReferralItem]


# --- imaging ---------------------------------------------------------------
class ImagingReport(BaseModel):
    ref: str
    code: str | None = None
    conclusion: str | None = None
    issued: str | None = None
    flag: str | None = None
    needs_review: bool | None = None
    matched: str | None = None


class ImagingReports(BaseModel):
    patient: str
    count: int
    reports: list[ImagingReport]

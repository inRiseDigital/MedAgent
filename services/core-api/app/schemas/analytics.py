"""Response schemas for the national analytics endpoints (A1)."""

from __future__ import annotations

from pydantic import BaseModel


class AnalyticsOverview(BaseModel):
    as_of: str
    patients_registered: int
    lab_reports: int
    imaging_studies: int
    immunizations: int
    referrals_open: int
    appointments: int
    notifiable_cases: int
    notifiable_by_disease: dict[str, int]


class OutbreakSignal(BaseModel):
    disease: str
    cases: int
    watch_at: int
    alert_at: int
    signal: str


class OutbreakView(BaseModel):
    as_of: str
    any_alert: bool
    signals: list[OutbreakSignal]


class CapacityTotals(BaseModel):
    waitlist: int
    free_slots: int
    open_referrals: int


class CapacityRow(BaseModel):
    facility: str
    waitlist: int
    free_slots: int
    open_referrals: int


class CapacityView(BaseModel):
    as_of: str
    totals: CapacityTotals
    by_facility: list[CapacityRow]

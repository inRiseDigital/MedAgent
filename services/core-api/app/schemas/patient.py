"""Response schemas for the patient read endpoints (A1).

These give the endpoints real OpenAPI response models (so the generated ts-sdk
carries precise types instead of `unknown`) and mirror exactly the shapes the web
client consumes in apps/web/lib/api.ts. Fields are optional wherever the FHIR
projection can omit them, so response validation never 500s on sparse records.
"""

from __future__ import annotations

from pydantic import BaseModel


# --- summary ---------------------------------------------------------------
class SummaryPatient(BaseModel):
    phn: str
    name: str
    gender: str | None = None
    birthDate: str | None = None


class RefItem(BaseModel):
    text: str
    ref: str


class AllergyItem(BaseModel):
    text: str
    criticality: str = "unknown"
    ref: str


class VitalItem(BaseModel):
    text: str
    value: float | None = None
    unit: str | None = None
    when: str | None = None


class AppointmentItem(BaseModel):
    start: str | None = None
    status: str | None = None


class ResultItem(BaseModel):
    text: str
    conclusion: str | None = None
    critical: bool = False
    ref: str


class PatientSummary(BaseModel):
    patient: SummaryPatient
    problems: list[RefItem]
    medications: list[RefItem]
    allergies: list[AllergyItem]
    vitals: list[VitalItem]
    appointments: list[AppointmentItem]
    results: list[ResultItem]


# --- brief -----------------------------------------------------------------
class SafetyFlag(BaseModel):
    severity: str
    kind: str
    text: str
    code: str | None = None
    cite: str | None = None


class PatientBrief(BaseModel):
    headline: str
    problems: list[str]
    flags: list[SafetyFlag]


# --- immunizations ---------------------------------------------------------
class ImmunizationRow(BaseModel):
    key: str
    name: str
    due: str | None = None
    status: str
    given_on: str | None = None


class ImmunizationSchedule(BaseModel):
    schedule: list[ImmunizationRow]
    overdue: int


# --- vital trends ----------------------------------------------------------
class VitalPoint(BaseModel):
    value: float
    when: str | None = None


class VitalSeries(BaseModel):
    name: str
    unit: str | None = None
    points: list[VitalPoint]


class VitalTrends(BaseModel):
    series: list[VitalSeries]


# --- child health development record (CHDR) --------------------------------
class ChildDemographics(BaseModel):
    phn: str
    name: str
    sex: str | None = None
    birth_date: str | None = None
    age_months: float | None = None


class GrowthPoint(BaseModel):
    date: str
    age_months: float | None = None
    kind: str
    value: float
    flags: list[str]


class GrowthHistory(BaseModel):
    latest_flags: list[str]
    points: list[GrowthPoint]


class ChildAlert(BaseModel):
    severity: str
    text: str


class ChildHealthRecord(BaseModel):
    child: ChildDemographics
    immunizations: ImmunizationSchedule
    growth: GrowthHistory
    alerts: list[ChildAlert]

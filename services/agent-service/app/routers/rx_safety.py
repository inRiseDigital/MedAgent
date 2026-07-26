"""POST /api/v1/rx-safety/screen — deterministic drug-safety verdict (04 §7).

The write-back sign-off flow calls this before a prescription proposal is shown,
and again at commit; the verdict is authoritative and computed by the engine,
never the LLM (ADR AG-2).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import Principal, require_user
from app.rxsafety import screen

router = APIRouter(prefix="/rx-safety", tags=["rx-safety"])


class AllergyIn(BaseModel):
    substance: str
    criticality: str = "unknown"


class ScreenRequest(BaseModel):
    proposed_drug: str = Field(min_length=1)
    current_meds: list[str] = Field(default_factory=list)
    allergies: list[AllergyIn] = Field(default_factory=list)
    dose_mg_per_day: float | None = None


@router.post("/screen")
async def screen_endpoint(
    body: ScreenRequest,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict:
    v = screen(
        body.proposed_drug,
        body.current_meds,
        [a.model_dump() for a in body.allergies],
        body.dose_mg_per_day,
    )
    return v.to_dict()


class ReviewRequest(BaseModel):
    meds: list[str] = Field(default_factory=list)
    allergies: list[AllergyIn] = Field(default_factory=list)


@router.post("/review")
async def review_endpoint(
    body: ReviewRequest,
    principal: Annotated[Principal, Depends(require_user)],
) -> dict:
    """Screen an EXISTING medication list + allergies for interactions and
    allergy conflicts already present in the record (ambient safety, backlog 3.1).
    Each med is screened against the others + the allergies; findings are deduped.
    Same deterministic engine as prescribing — this just points it at the record."""
    allergies = [a.model_dump() for a in body.allergies]
    seen: set[tuple[str, str]] = set()
    flags: list[dict] = []
    worst = "pass"
    for i, med in enumerate(body.meds):
        others = [m for j, m in enumerate(body.meds) if j != i]
        v = screen(med, others, allergies, None)
        if v.verdict == "block" or (v.verdict == "warn" and worst == "pass"):
            worst = v.verdict
        for f in v.findings:
            key = (f.get("code", ""), f.get("rationale", ""))
            if key in seen:
                continue
            seen.add(key)
            flags.append({**f, "drug": med})
    return {"verdict": worst, "flags": flags, "count": len(flags)}

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

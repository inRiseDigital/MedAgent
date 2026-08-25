"""Regression tests for the shared FHIR/router helpers (P3.1).

These back all 10 routers, so a regression here is wide-reaching. Pure logic with
a tiny fake FHIR client / request.
"""

from __future__ import annotations

from typing import Any

from app.fhir import helpers as h


def test_cc_text_prefers_text_then_coding() -> None:
    assert h.cc_text({"text": "Diabetes"}) == "Diabetes"
    assert h.cc_text({"coding": [{"display": "Asthma", "code": "J45"}]}) == "Asthma"
    assert h.cc_text({"coding": [{"code": "J45"}]}) == "J45"  # falls back to code
    assert h.cc_text({}) == ""
    assert h.cc_text(None) == ""


class _Req:
    def __init__(self, auth: str | None) -> None:
        self._h = {"authorization": auth} if auth is not None else {}

    @property
    def headers(self) -> dict[str, str]:
        return self._h


def test_bearer_extracts_case_insensitively() -> None:
    assert h.bearer(_Req("Bearer abc.def")) == "abc.def"
    assert h.bearer(_Req("bearer xyz")) == "xyz"  # lowercase scheme
    assert h.bearer(_Req("Basic abc")) is None
    assert h.bearer(_Req(None)) is None


class _FakeFhir:
    """Records calls; returns canned search/read results."""

    def __init__(self, search_rows: list[dict[str, Any]] | None = None,
                 read_res: dict[str, Any] | None = None, read_raises: bool = False) -> None:
        self._search = search_rows or []
        self._read = read_res
        self._read_raises = read_raises
        self.calls: list[str] = []

    async def search(self, _rt: str, _params: dict[str, str]) -> list[dict[str, Any]]:
        self.calls.append("search")
        return self._search

    async def read(self, _rt: str, _rid: str) -> dict[str, Any]:
        self.calls.append("read")
        if self._read_raises:
            raise RuntimeError("boom")
        assert self._read is not None
        return self._read


async def test_resolve_pid_digit_uses_search() -> None:
    f = _FakeFhir(search_rows=[{"id": "p1"}])
    assert await h.resolve_pid(f, "55246820131") == {"id": "p1"}
    assert f.calls == ["search"]  # digit PHN → search, not read


async def test_resolve_pid_nondigit_uses_read_and_degrades() -> None:
    f = _FakeFhir(read_res={"id": "p2"})
    assert await h.resolve_pid(f, "abc-uuid") == {"id": "p2"}
    assert f.calls == ["read"]
    # a failing read is treated as "not found", never raised
    f2 = _FakeFhir(read_raises=True)
    assert await h.resolve_pid(f2, "bad-id") is None


async def test_resolve_patient_id_returns_id_string() -> None:
    f = _FakeFhir(search_rows=[{"id": 99}])
    assert await h.resolve_patient_id(f, "55246820131") == "99"
    f2 = _FakeFhir(search_rows=[], read_res={"id": "p3"})
    assert await h.resolve_patient_id(f2, "raw-id") == "p3"

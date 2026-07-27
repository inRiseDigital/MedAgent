"""Audit hash-chain regression tests (03 §5.4, backlog 0.2).

These guard the three integrity bugs found and fixed while building Track 5/6:
  1. tamper detection — altering an event breaks the chain;
  2. duplicate-sequence fork — the concurrency/stale-head signature;
  3. false-pass guard — verify must never say intact=true when it could not read.
All pure (no FHIR/DB): they exercise `evaluate_chain` + `_chain_hash` directly.
"""

from __future__ import annotations

from typing import Any

from app.audit import AUDIT_HASH_EXT, _GENESIS, _chain_basis, _chain_hash, evaluate_chain


def _event(seq: int, prev_hash: str, *, etype: str = "test_event", actor: str = "u1",
           recorded: str = "2026-07-27T00:00:00+00:00") -> dict[str, Any]:
    """Build a chained AuditEvent whose stored hash is correct for its content."""
    ae: dict[str, Any] = {
        "resourceType": "AuditEvent",
        "type": {"code": etype},
        "action": "C",
        "recorded": recorded,
        "agent": [{"who": {"display": actor}, "requestor": True}],
        "outcome": "0",
    }
    h = _chain_hash(prev_hash, ae)
    ae["extension"] = [{"url": AUDIT_HASH_EXT, "extension": [
        {"url": "seq", "valueInteger": seq},
        {"url": "prevHash", "valueString": prev_hash},
        {"url": "hash", "valueString": h},
    ]}]
    return ae


def _hash_of(ae: dict[str, Any]) -> str:
    return ae["extension"][0]["extension"][2]["valueString"]


def _valid_chain(n: int) -> list[dict[str, Any]]:
    events, prev = [], _GENESIS
    for i in range(1, n + 1):
        ae = _event(i, prev, etype=f"e{i}")
        events.append(ae)
        prev = _hash_of(ae)  # next event links to this event's stored hash
    return events


def test_chain_hash_is_deterministic_and_content_sensitive() -> None:
    a = {"type": {"code": "x"}, "action": "C", "recorded": "t", "agent": [], "outcome": "0"}
    assert _chain_hash("PREV", a) == _chain_hash("PREV", a)  # deterministic
    b = dict(a, action="U")
    assert _chain_hash("PREV", a) != _chain_hash("PREV", b)  # content change -> different
    assert _chain_hash("PREV", a) != _chain_hash("OTHER", a)  # prev change -> different


def test_basis_excludes_volatile_fields() -> None:
    a = {"type": {"code": "x"}, "action": "C", "recorded": "t", "agent": [], "outcome": "0",
         "id": "123", "meta": {"lastUpdated": "now"}}
    b = {"type": {"code": "x"}, "action": "C", "recorded": "t", "agent": [], "outcome": "0"}
    assert _chain_basis(a) == _chain_basis(b)  # id/meta are ignored


def test_intact_chain_verifies() -> None:
    events = _valid_chain(5)
    r = evaluate_chain(events, total=5)
    assert r["intact"] is True and r["broken_at_seq"] is None and r["events"] == 5


def test_tamper_breaks_chain() -> None:
    events = _valid_chain(4)
    events[2]["action"] = "D"  # alter content of seq 3 without recomputing its stored hash
    r = evaluate_chain(events, total=4)
    assert r["intact"] is False and r["broken_at_seq"] == 3


def test_duplicate_sequence_is_a_fork() -> None:
    events = _valid_chain(3)
    events.append(_event(2, events[0]["extension"][0]["extension"][1]["valueString"], etype="dup"))
    r = evaluate_chain(events, total=4)
    assert r["intact"] is False and r["broken_at_seq"] == 2 and "fork" in r["error"]


def test_false_pass_guard_when_read_returns_nothing() -> None:
    # Store reports events exist but the search returned none -> must NOT be intact:true.
    r = evaluate_chain([], total=10)
    assert r["intact"] is None and "could not read" in r["error"]


def test_empty_store_is_intact() -> None:
    r = evaluate_chain([], total=0)
    assert r["intact"] is True and r["events"] == 0


def test_truncated_read_is_not_a_pass() -> None:
    events = _valid_chain(3)
    r = evaluate_chain(events, total=99)  # we only saw 3 of 99
    assert r["intact"] is None and "tail not read" in r["error"]

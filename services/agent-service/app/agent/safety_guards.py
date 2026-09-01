"""Deterministic PHI/PII outbound guard for web search (Horizon-0, S2).

The agent's `web_search` tool ships its query verbatim to a third-party engine
(DuckDuckGo). Nothing else sits between the model and the wire, so this module is
the ONLY thing stopping patient identifiers — NICs, PHNs, phone numbers, emails,
FHIR record references, dates of birth — from leaking off-platform inside a search
string.

It is intentionally dumb: pure regex, no network, no LLM, no state. Determinism is
the whole point — the same query always scrubs the same way, so the behaviour is
auditable and the guard itself can never become a source of failure on a turn.
"""

from __future__ import annotations

import re

# Neutral token every hit is rewritten to. Carries no digits/word content of its
# own, so once a span is redacted it can never be re-matched by a later rule.
_REDACTED = "[redacted]"

# Ordered (compiled pattern, human label) rules. Order is load-bearing: structured
# / stronger identifiers run before looser digit runs so a value is labelled as the
# right thing (a phone, not a bare ID) and a longer form wins over a shorter one.
_RULES: list[tuple[re.Pattern[str], str]] = [
    # Record citations we emit downstream in [source: …] form — never echo one out.
    (re.compile(r"\[source:[^\]]*\]"), "a record reference"),
    # FHIR resource references, e.g. Patient/abc-123, Observation/42.
    (re.compile(
        r"\b(?:Patient|MedicationRequest|Condition|AllergyIntolerance|Observation|"
        r"Immunization|Encounter|DiagnosticReport|Procedure|Appointment)"
        r"/[A-Za-z0-9._-]+\b"
    ), "a record reference"),
    # Email addresses.
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "an email"),
    # Sri Lanka NIC — old (9 digits + V/X) then new (12 digits) format.
    (re.compile(r"\b\d{9}[VXvx]\b"), "an ID number"),
    (re.compile(r"\b\d{12}\b"), "an ID number"),
    # Phone numbers — SL (+94 / 0 prefixed) and a generic grouped form. These run
    # BEFORE the bare long-digit rule so they read as phones rather than IDs.
    (re.compile(r"\b(?:\+?94|0)\d{9,10}\b"), "a phone number"),
    (re.compile(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{4}\b"), "a phone number"),
    # PHN / any other long digit run (10+) — catches the 11-digit patient health no.
    (re.compile(r"\b\d{10,}\b"), "an ID number"),
    # Dates: an explicit DOB label, and any ISO calendar date (redact the date).
    (re.compile(r"\bDOB\b", re.IGNORECASE), "a date of birth"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "a date"),
]

# Two or more placeholders in a row (whitespace/punctuation between) fold to one, so
# scrubbing a run of PHI does not leave a wall of [redacted] tokens behind.
_COLLAPSE = re.compile(r"\[redacted\](?:[\s./,;:|_-]*\[redacted\])+")
_WS = re.compile(r"\s+")
# A "meaningful" char is a letter or digit that survives once placeholders are gone.
_WORDCHAR = re.compile(r"[^\W_]")

# Below this many meaningful chars the query is essentially all PHI → block outright.
_MIN_MEANINGFUL = 3


def _join(labels: list[str]) -> str:
    """Grammatical 'a', 'a and b', 'a, b and c' join for the human-readable note."""
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def sanitize_web_query(query: str) -> tuple[str | None, str]:
    """Scrub likely PHI/PII from an outbound web-search query.

    Returns (safe_query, note):
      - safe_query is the redacted query to actually send, or None if the query
        should be BLOCKED (it was essentially all PHI / meaningless after redaction).
      - note is a short human-readable explanation of what was done ('' if nothing).
    Deterministic and side-effect free.
    """
    if not query or not query.strip():
        # Nothing to search — treat as a block so callers uniformly get None back.
        return None, "blocked — query was empty"

    safe = query
    labels: list[str] = []
    for pattern, label in _RULES:
        safe, hits = pattern.subn(_REDACTED, safe)
        if hits and label not in labels:  # note each category once, in firing order
            labels.append(label)

    # Tidy up: fold runs of placeholders, then normalise whitespace.
    safe = _COLLAPSE.sub(_REDACTED, safe)
    safe = _WS.sub(" ", safe).strip()

    # If almost nothing real survives once placeholders are stripped out, the query
    # was basically an identifier — block rather than search an empty husk.
    residue = safe.replace(_REDACTED, " ")
    if len(_WORDCHAR.findall(residue)) < _MIN_MEANINGFUL:
        return None, "blocked — query was essentially personal data"

    note = f"redacted {_join(labels)}" if labels else ""
    return safe, note

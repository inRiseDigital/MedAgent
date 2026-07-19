"""PHN issuance and validation (02 §8.1, ADR I-6).

Format: **11 digits = 10 significant digits + 1 Verhoeff check digit.**

- Verhoeff over mod-11 alternatives because it catches ALL single-digit errors
  and ALL adjacent transpositions on a digits-only alphabet — PHNs are read
  over phones and typed at kiosks.
- No embedded semantics (no DOB, no facility prefix): meaningful digits leak
  data and break when people move.
- Rendered grouped `XXX XXX XXX XX` for humans; stored canonical 11-digit.
- The scheme is deliberately configuration-shaped ("PHN scheme" = issuer URI +
  validator function) so adopting a national MoH/NDHX format is a config
  change, not a migration (02 §8.1 alignment caveat).
- Per-facility allocated blocks (offline-safe rural issuance) are Phase B;
  S1 issues from cryptographically random significant digits with a DB
  uniqueness constraint as the collision guard.
"""

from __future__ import annotations

import secrets

PHN_SYSTEM_URI = "https://fhir.medagent.health.lk/id/phn"
PHN_LENGTH = 11
_SIGNIFICANT_DIGITS = PHN_LENGTH - 1

# Verhoeff tables: dihedral group D5 multiplication, permutation, and inverse.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff_check_digit(significant: str) -> str:
    """Compute the Verhoeff check digit for a string of digits."""
    if not significant.isdigit():
        raise ValueError("significant part must be digits only")
    c = 0
    # The check digit will occupy position 0 (rightmost), so significant
    # digits are processed from position 1 upward.
    for i, ch in enumerate(reversed(significant)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def _verhoeff_valid(number: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def generate_phn() -> str:
    """Issue a new canonical 11-digit PHN (10 random significant + check digit).

    First digit is non-zero so every PHN renders at full visual length.
    Uniqueness is guaranteed by the `patients_mpi.phn` unique constraint at
    insert time (caller retries on collision — astronomically rare).
    """
    first = str(1 + secrets.randbelow(9))
    rest = "".join(str(secrets.randbelow(10)) for _ in range(_SIGNIFICANT_DIGITS - 1))
    significant = first + rest
    return significant + verhoeff_check_digit(significant)


def validate_phn(phn: str) -> bool:
    """True iff `phn` is a canonical 11-digit, Verhoeff-valid PHN."""
    phn = phn.strip()
    return len(phn) == PHN_LENGTH and phn.isdigit() and _verhoeff_valid(phn)


def format_phn(phn: str) -> str:
    """Human rendering: `XXX XXX XXX XX` (02 §8.1)."""
    if not validate_phn(phn):
        raise ValueError("not a valid PHN")
    return f"{phn[0:3]} {phn[3:6]} {phn[6:9]} {phn[9:11]}"


def normalize_phn(phn: str) -> str:
    """Strip grouping whitespace back to the canonical 11-digit form."""
    return "".join(phn.split())

"""PHN issuance unit tests (02 §8.1: 11 digits = 10 significant + Verhoeff check)."""

from __future__ import annotations

import pytest

from app.mpi.phn import (
    PHN_LENGTH,
    format_phn,
    generate_phn,
    normalize_phn,
    validate_phn,
    verhoeff_check_digit,
)


def test_verhoeff_known_vector() -> None:
    # Canonical Verhoeff example: check digit of "236" is 3.
    assert verhoeff_check_digit("236") == "3"
    assert validate_phn is not None  # sanity for import


def test_generated_phn_is_canonical_and_valid() -> None:
    for _ in range(100):
        phn = generate_phn()
        assert len(phn) == PHN_LENGTH
        assert phn.isdigit()
        assert phn[0] != "0"
        assert validate_phn(phn)


def test_single_digit_error_is_detected() -> None:
    phn = generate_phn()
    for pos in range(PHN_LENGTH):
        original = int(phn[pos])
        mutated = phn[:pos] + str((original + 1) % 10) + phn[pos + 1 :]
        assert not validate_phn(mutated), f"single-digit error at {pos} not caught"


def test_adjacent_transposition_is_detected() -> None:
    phn = generate_phn()
    for pos in range(PHN_LENGTH - 1):
        if phn[pos] == phn[pos + 1]:
            continue  # transposing equal digits is not an error
        swapped = phn[:pos] + phn[pos + 1] + phn[pos] + phn[pos + 2 :]
        assert not validate_phn(swapped), f"adjacent transposition at {pos} not caught"


def test_validate_rejects_malformed_input() -> None:
    assert not validate_phn("")
    assert not validate_phn("1234567890")  # 10 digits
    assert not validate_phn("123456789012")  # 12 digits
    assert not validate_phn("1234567890a")


def test_format_and_normalize_round_trip() -> None:
    phn = generate_phn()
    display = format_phn(phn)
    assert display == f"{phn[0:3]} {phn[3:6]} {phn[6:9]} {phn[9:11]}"
    assert normalize_phn(display) == phn


def test_format_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="not a valid PHN"):
        format_phn("00000000000")

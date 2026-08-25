"""Tests for the notifiable-disease outbreak early-warning signal (FR-12, P6).

Pure threshold logic: a case count is `alert` at/above the disease's alert
threshold, `watch` at/above its watch threshold, else `none`. Elimination-target
diseases (cholera/rabies/diphtheria) trip `alert` on a single case; unknown
diseases fall back to the default (5, 15) threshold.
"""

from __future__ import annotations

import pytest

from app.routers.analytics import outbreak_signal


@pytest.mark.parametrize(
    ("disease", "cases", "expected"),
    [
        ("dengue", 2, "none"),    # watch=3
        ("dengue", 3, "watch"),
        ("dengue", 7, "watch"),
        ("dengue", 8, "alert"),   # alert=8
        ("dengue", 20, "alert"),
        ("measles", 1, "watch"),  # (1, 2)
        ("measles", 2, "alert"),
        ("cholera", 0, "none"),   # (1, 1) — single case = alert
        ("cholera", 1, "alert"),
        ("rabies", 1, "alert"),
        ("unknown-disease", 4, "none"),   # default (5, 15)
        ("unknown-disease", 5, "watch"),
        ("unknown-disease", 15, "alert"),
    ],
)
def test_outbreak_signal(disease: str, cases: int, expected: str) -> None:
    assert outbreak_signal(disease, cases) == expected

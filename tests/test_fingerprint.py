"""Tests for audio-envelope duplicate detection.

These tests use synthetic signals, so they run offline in milliseconds and do not
need any real media. They encode the two parameter lessons directly: the
alignment search window and the analysis window length.
"""

from __future__ import annotations

import numpy as np
import pytest

from cap.fingerprint import (
    MAX_SHIFT,
    VERDICT_DIFFERENT,
    VERDICT_PARTIAL,
    VERDICT_SAME,
    best_corr,
    classify_coefficient,
)

FRAME_MS = 20  # 50 frames per second


def envelope(seed: int, n: int = 4500) -> np.ndarray:
    """A pseudo-random envelope standing in for 90 s of speech energy."""
    return np.random.default_rng(seed).random(n).astype(np.float32)


def test_identical_envelopes_correlate_at_one():
    a = envelope(1)
    corr, shift = best_corr(a, a.copy())
    assert corr is not None and corr > 0.999
    assert shift == 0


def test_offset_within_search_window_is_aligned():
    """A 7 s offset is what a trimmed intro produces; it must still align.

    7 s / 20 ms = 350 frames. This is the case that a +/-3 s window reported as
    "unrelated" (0.2457) for two copies of the same recording.
    """
    a = envelope(2)
    offset = 350
    b = np.roll(a, offset)
    corr, shift = best_corr(a, b, max_shift=MAX_SHIFT)
    assert corr is not None and corr > 0.99
    assert abs(abs(shift) - offset) <= 2


def test_narrow_search_window_produces_a_false_negative():
    """Documents *why* MAX_SHIFT is 1250 rather than 150.

    With a +/-3 s window the same pair scores low, which would be read as
    "different content". Keeping this as a test stops anyone from "optimising"
    the constant back down.
    """
    a = envelope(3)
    b = np.roll(a, 350)

    narrow, _ = best_corr(a, b, max_shift=150)
    wide, _ = best_corr(a, b, max_shift=MAX_SHIFT)

    assert narrow is not None and narrow < 0.5, "narrow window should fail to align"
    assert wide is not None and wide > 0.9, "wide window should align"
    assert classify_coefficient(narrow) == VERDICT_DIFFERENT
    assert classify_coefficient(wide) == VERDICT_SAME


def test_unrelated_envelopes_do_not_correlate():
    """Negative control: two different lectures must not look like duplicates."""
    corr, _ = best_corr(envelope(4), envelope(5))
    assert corr is not None and abs(corr) < 0.2
    assert classify_coefficient(corr) == VERDICT_DIFFERENT


def test_short_envelope_returns_none():
    corr, shift = best_corr(np.zeros(10), np.zeros(10))
    assert corr is None
    assert shift == 0


def test_constant_signal_returns_none():
    """Zero variance carries no information and must not divide by zero."""
    corr, _ = best_corr(np.ones(1000), np.ones(1000))
    assert corr is None


@pytest.mark.parametrize(
    ("coefficient", "expected"),
    [
        (1.0, VERDICT_SAME),
        (0.70, VERDICT_SAME),
        (0.69, VERDICT_PARTIAL),
        (0.35, VERDICT_PARTIAL),
        (0.34, VERDICT_DIFFERENT),
        (0.0, VERDICT_DIFFERENT),
    ],
)
def test_threshold_boundaries(coefficient, expected):
    assert classify_coefficient(coefficient) == expected


def test_frame_rate_constant_matches_documented_value():
    assert FRAME_MS == 20
    assert MAX_SHIFT == 1250, "MAX_SHIFT is +/-25 s; see docs/design-notes.md"

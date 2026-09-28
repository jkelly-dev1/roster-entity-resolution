"""The sweep's own guard, exercised rather than described.

tests/test_results_invariants.py asserts that the shipped curve is not one
point repeated. That test reads a stored run, so it says nothing about whether
sweep() itself refuses a degenerate curve.

This file calls sweep() with input that must produce a degenerate curve and
requires it to refuse.
"""

import pytest

import exp2_threshold


def _scores_and_labels():
    scores = [float(i) for i in range(200)]
    labels = [1 if s >= 150 else 0 for s in scores]
    return scores, labels


def test_sweep_refuses_a_curve_that_is_one_point_repeated():
    """A grid entirely below the scores accepts everything at every threshold.

    That is the same shape a grid walked in the wrong direction produces:
    tp and fp are running totals, so the first threshold takes every pair and
    the rest report its counts back. The cause differs; the tell is identical,
    and the tell is that the two ends of the curve agree.
    """
    scores, labels = _scores_and_labels()
    grid = [-1000.0 + i for i in range(20)]        # every point below min(scores)
    with pytest.raises(AssertionError, match="one point repeated"):
        exp2_threshold.sweep(scores, labels, sum(labels), grid)


def test_sweep_accepts_a_grid_that_actually_straddles_the_scores():
    """The control. A guard that fires on everything pins nothing either."""
    scores, labels = _scores_and_labels()
    grid = [float(i) for i in range(0, 200, 10)]
    curve = exp2_threshold.sweep(scores, labels, sum(labels), grid)
    assert len(curve) == 20
    assert curve[0]["threshold"] < curve[-1]["threshold"]     # ascending, for reading
    assert curve[0]["tp"] > curve[-1]["tp"]                   # and it moves


def test_a_real_sweep_never_reports_recall_rising():
    """The property the monotonicity guard in sweep() enforces, on a real
    sweep. This does not exercise the guard itself: a correct accumulator
    cannot produce a rising curve from any input, so the guard fires only on
    a broken sweep() and no input here can reach it.
    """
    scores, labels = _scores_and_labels()
    grid = [float(i) for i in range(0, 200, 10)]
    curve = exp2_threshold.sweep(scores, labels, sum(labels), grid)
    # Confirm the property the other guard enforces holds on a real sweep, so
    # this file says which of the two guards each assertion is about.
    for a, b in zip(curve, curve[1:]):
        assert b["recall"] <= a["recall"] + 1e-9

import math

import pytest

from redsailcut.cut_optimizer import (
    CutOptimizerOptions,
    optimize_polylines_for_cutting,
)


def test_optimizer_removes_jitter_points_but_preserves_shape():
    noisy_line = [
        (0.0, 0.0),
        (1.0, 0.03),
        (2.0, -0.04),
        (3.0, 0.02),
        (4.0, 0.0),
    ]

    result = optimize_polylines_for_cutting([noisy_line])

    assert result.polylines == [[(0.0, 0.0), (4.0, 0.0)]]
    assert result.report.input_points == 5
    assert result.report.output_points == 2
    assert result.report.removed_points == 3
    assert result.report.input_cut_length_mm == pytest.approx(4.005, abs=0.01)
    assert result.report.output_cut_length_mm == pytest.approx(4.0)


def test_optimizer_keeps_closed_paths_closed():
    square_with_noise = [
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 5.0),
        (10.0, 10.0),
        (0.0, 10.0),
        (0.0, 0.0),
    ]

    result = optimize_polylines_for_cutting([square_with_noise])
    optimized = result.polylines[0]

    assert optimized[0] == optimized[-1]
    assert math.isclose(result.report.output_cut_length_mm, 40.0, abs_tol=0.01)


def test_smoothing_mode_rounds_a_zigzag_into_more_gradual_segments():
    zigzag = [(0.0, 0.0), (1.0, 1.0), (2.0, 0.0), (3.0, 1.0), (4.0, 0.0)]
    options = CutOptimizerOptions(
        simplify_tolerance_mm=0.0,
        smoothing_iterations=1,
    )

    result = optimize_polylines_for_cutting([zigzag], options)
    smoothed = result.polylines[0]

    assert smoothed[0] == zigzag[0]
    assert smoothed[-1] == zigzag[-1]
    assert len(smoothed) > len(zigzag)
    assert max(y for _, y in smoothed) < 1.0

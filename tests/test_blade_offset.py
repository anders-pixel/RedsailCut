import math

import pytest

from redsailcut.blade_offset import compensate_polylines


def test_offset_zero_is_bit_perfect():
    polys = [
        [(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)],
        [(1.0, 1.0), (2.0, 2.0)],
    ]
    result = compensate_polylines(polys, offset_mm=0.0)
    # Deep-equal the coordinates
    assert len(result) == len(polys)
    for r, p in zip(result, polys):
        assert list(r) == list(p)


def test_straight_line_endpoint_extended_by_offset():
    # 10 mm horizontal line, offset 0.25 mm -> endpoint extended 0.25 mm in +X
    result = compensate_polylines([[(0.0, 0.0), (10.0, 0.0)]],
                                  offset_mm=0.25)[0]
    assert len(result) == 2
    assert result[0] == (0.0, 0.0)  # start unchanged
    assert result[1] == pytest.approx((10.25, 0.0))


def test_l_corner_each_arm_extended_along_its_own_direction():
    # L-shape: (0,0) -> (10,0) -> (10,10) with a sharp 90° corner
    result = compensate_polylines(
        [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]],
        offset_mm=0.25,
        corner_threshold_deg=5.0,
    )[0]
    assert len(result) == 3
    assert result[0] == (0.0, 0.0)
    # Incoming arm extended 0.25 mm in +X past the corner
    assert result[1] == pytest.approx((10.25, 0.0))
    # Outgoing arm's endpoint extended 0.25 mm in +Y past (10,10)
    assert result[2] == pytest.approx((10.0, 10.25))


def test_circle_below_threshold_produces_no_pivots():
    # 100-point circle, each segment turns 360/100 = 3.6°, below threshold 5°
    n = 100
    r = 20.0
    cx = cy = 20.0
    circle = [
        (cx + r * math.cos(2 * math.pi * k / n),
         cy + r * math.sin(2 * math.pi * k / n))
        for k in range(n + 1)  # include closure
    ]
    result = compensate_polylines(
        [circle],
        offset_mm=0.25,
        overcut_mm=0.0,
        corner_threshold_deg=5.0,
    )[0]
    # No pivots added → output point count equals input point count
    # (endpoints still pass through; they just aren't extended)
    assert len(result) == len(circle)
    # And every point should be unchanged (no extension at any corner)
    for actual, expected in zip(result, circle):
        assert actual == pytest.approx(expected, abs=1e-9)


def test_closed_square_overcut_adds_one_point_extending_last_segment():
    # Closed square drawn (0,0) -> (10,0) -> (10,10) -> (0,10) -> (0,0).
    # Last segment is (0,10) -> (0,0), direction (0,-1).
    # Overcut continues past (0,0) along (0,-1) by 0.5 mm.
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    result = compensate_polylines(
        [square], offset_mm=0.25, overcut_mm=0.5, corner_threshold_deg=5.0
    )[0]
    # Original 5 points + 1 overcut point = 6
    assert len(result) == 6
    # Every sharp 90° corner gets extended along the incoming direction.
    # i=1 (10,0): incoming +X, extend -> (10.25, 0)
    # i=2 (10,10): incoming +Y, extend -> (10, 10.25)
    # i=3 (0,10): incoming -X, extend -> (-0.25, 10)
    # i=4 (0,0):  incoming -Y, extend -> (0, -0.25)  — closed-last-point checks
    #                                                  turn to first segment (+X),
    #                                                  90° ≥ threshold, so extend.
    assert result[1] == pytest.approx((10.25, 0.0))
    assert result[2] == pytest.approx((10.0, 10.25))
    assert result[3] == pytest.approx((-0.25, 10.0))
    assert result[4] == pytest.approx((0.0, -0.25))
    # Overcut point: from compensated last (0, -0.25) along last-segment (0,-1) by 0.5
    assert result[5] == pytest.approx((0.0, -0.75))


def test_non_closed_polyline_gets_no_overcut_even_when_requested():
    result = compensate_polylines(
        [[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]],
        offset_mm=0.25,
        overcut_mm=0.5,
    )[0]
    # 3 input points + 0 overcut (not closed) = 3
    assert len(result) == 3


def test_closure_tolerance_accepts_tiny_drift():
    # End point 0.05 mm away from start — still counts as closed
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.03, 0.02)]
    result = compensate_polylines(
        [pts], offset_mm=0.25, overcut_mm=0.5, corner_threshold_deg=5.0
    )[0]
    assert len(result) == 6  # overcut point appended


def test_closure_tolerance_rejects_obvious_gaps():
    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (5.0, 5.0)]
    result = compensate_polylines(
        [pts], offset_mm=0.25, overcut_mm=0.5, corner_threshold_deg=5.0
    )[0]
    assert len(result) == 5  # no overcut


def test_degenerate_zero_length_segments_are_skipped_not_crashing():
    pts = [(0.0, 0.0), (0.0, 0.0), (10.0, 0.0)]
    result = compensate_polylines([pts], offset_mm=0.25)[0]
    # Duplicate (0,0) is skipped; we should still get (0,0) start and extended end
    assert result[0] == (0.0, 0.0)
    assert result[-1] == pytest.approx((10.25, 0.0))


def test_single_point_or_empty_polyline_passes_through():
    result = compensate_polylines([[(5.0, 5.0)], []], offset_mm=0.25)
    assert result == [[(5.0, 5.0)], []]


def test_corner_threshold_above_all_angles_disables_compensation_internally():
    # Threshold 170° → almost no turn qualifies; only U-turns (>170°) do
    result = compensate_polylines(
        [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]],
        offset_mm=0.25,
        corner_threshold_deg=170.0,
    )[0]
    # Inner corner (90°) is below threshold → not extended
    # Last point of open polyline → always extended
    assert result[1] == pytest.approx((10.0, 0.0))  # unchanged
    assert result[2] == pytest.approx((10.0, 10.25))  # still extended (open endpoint)

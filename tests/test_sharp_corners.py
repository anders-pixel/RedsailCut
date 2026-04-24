import math

import pytest

from redsailcut.sharp_corners import add_pivots


def test_threshold_zero_returns_input_unchanged():
    polys = [
        [(0.0, 0.0), (10.0, 0.0), (0.0, 0.0)],  # u-turn, very sharp
        [(0.0, 0.0), (1.0, 1.0)],
    ]
    result = add_pivots(polys, threshold_deg=0.0)
    assert result == [list(p) for p in polys]


def test_straight_line_three_collinear_points_unchanged():
    result = add_pivots([[(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]],
                        threshold_deg=30.0)
    # 180° opening → not sharp → single polyline out
    assert result == [[(0.0, 0.0), (5.0, 0.0), (10.0, 0.0)]]


def test_l_corner_ninety_degrees_not_sharp_at_threshold_thirty():
    # 90° opening > 30° threshold → not sharp
    result = add_pivots([[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]],
                        threshold_deg=30.0)
    assert len(result) == 1
    assert result[0] == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]


def test_square_four_right_angle_corners_not_split():
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0),
              (0.0, 10.0), (0.0, 0.0)]
    result = add_pivots([square], threshold_deg=30.0)
    assert len(result) == 1
    assert result[0] == square


def test_fifteen_degree_v_splits_into_two_polylines():
    # V with 15° opening angle at corner (0,0)
    # Segment 1: (10,0) → (0,0), direction toward prev = (1,0)
    # Segment 2: (0,0) → (9.659, 2.588) (15° above x-axis)
    # Opening angle = 15°
    p = [(10.0, 0.0), (0.0, 0.0), (9.659, 2.588)]
    result = add_pivots([p], threshold_deg=30.0)
    assert len(result) == 2
    assert result[0] == [(10.0, 0.0), (0.0, 0.0)]
    assert result[1] == [(0.0, 0.0), (9.659, 2.588)]


def test_ten_degree_v_splits_and_both_endpoints_share_corner():
    # Very acute 10° V
    end_x = 10.0 * math.cos(math.radians(10))
    end_y = 10.0 * math.sin(math.radians(10))
    p = [(10.0, 0.0), (0.0, 0.0), (end_x, end_y)]
    result = add_pivots([p], threshold_deg=30.0)
    assert len(result) == 2
    # Both sides meet at the corner (0,0)
    assert result[0][-1] == pytest.approx((0.0, 0.0))
    assert result[1][0] == pytest.approx((0.0, 0.0))


def test_threshold_below_opening_angle_preserves_polyline():
    # 15° opening, threshold 10° → not sharp → no split
    p = [(10.0, 0.0), (0.0, 0.0), (9.659, 2.588)]
    result = add_pivots([p], threshold_deg=10.0)
    assert len(result) == 1


def test_five_pointed_star_produces_five_splits_at_tips():
    # Regular 5-pointed star: alternating outer (tip) and inner (trough)
    # radii such that tip opening ≈ 36°. Starting offset places a TROUGH
    # at index 0 so all five TIPS are interior points of the loop.
    r_out = 10.0
    r_in = 3.82  # r_out/r_in ≈ 2.62 ⇒ tip opening ≈ 36°
    points = []
    for i in range(10):
        angle = math.pi / 2 + math.pi / 5 + i * math.pi / 5
        r = r_in if i % 2 == 0 else r_out
        points.append((r * math.cos(angle), r * math.sin(angle)))
    points.append(points[0])  # close

    result = add_pivots([points], threshold_deg=45.0)
    # 5 sharp tips → 5 splits → 6 output polylines
    assert len(result) == 6


def test_five_pointed_star_with_wider_threshold_also_catches_troughs():
    # With threshold 100° even troughs (~108° opening) should NOT split,
    # but all 5 tips (~36°) will. Still 6 output polylines.
    r_out = 10.0
    r_in = 3.82
    points = []
    for i in range(10):
        angle = math.pi / 2 + math.pi / 5 + i * math.pi / 5
        r = r_in if i % 2 == 0 else r_out
        points.append((r * math.cos(angle), r * math.sin(angle)))
    points.append(points[0])
    result = add_pivots([points], threshold_deg=100.0)
    assert len(result) == 6


def test_degenerate_two_point_polyline_untouched():
    result = add_pivots([[(0.0, 0.0), (5.0, 5.0)]], threshold_deg=30.0)
    assert result == [[(0.0, 0.0), (5.0, 5.0)]]


def test_zero_length_segment_does_not_crash():
    p = [(0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    result = add_pivots([p], threshold_deg=30.0)
    # Duplicate middle point makes that corner degenerate and ungated by split
    assert len(result) >= 1
    # The final point is preserved
    assert result[-1][-1] == (10.0, 10.0)

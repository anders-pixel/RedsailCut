import pytest

from redsailcut.rotate import rotate_polylines


def _square_10x5():
    # Rectangle (0,0)-(10,0)-(10,5)-(0,5)-(0,0)
    return [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0), (0.0, 0.0)]


def test_zero_degrees_returns_input_unchanged():
    polys = [_square_10x5(), [(2.0, 1.0), (3.0, 4.0)]]
    out, w, h = rotate_polylines(polys, 0, 10.0, 5.0)
    assert out == [list(p) for p in polys]
    assert w == 10.0
    assert h == 5.0


def test_360_normalises_to_zero():
    polys = [_square_10x5()]
    out, w, h = rotate_polylines(polys, 360, 10.0, 5.0)
    assert out == [_square_10x5()]
    assert w == 10.0 and h == 5.0


def test_ninety_degrees_clockwise_swaps_dimensions():
    polys = [_square_10x5()]
    out, w, h = rotate_polylines(polys, 90, 10.0, 5.0)
    # Width and height swap on 90°
    assert w == 5.0
    assert h == 10.0
    # (x, y) -> (height - y, x)
    expected = [(5.0, 0.0), (5.0, 10.0), (0.0, 10.0), (0.0, 0.0), (5.0, 0.0)]
    assert out[0] == pytest.approx(expected)


def test_one_eighty_degrees_keeps_dimensions_flips_both_axes():
    polys = [_square_10x5()]
    out, w, h = rotate_polylines(polys, 180, 10.0, 5.0)
    assert w == 10.0
    assert h == 5.0
    expected = [(10.0, 5.0), (0.0, 5.0), (0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]
    assert out[0] == pytest.approx(expected)


def test_two_seventy_degrees_swaps_dimensions():
    polys = [_square_10x5()]
    out, w, h = rotate_polylines(polys, 270, 10.0, 5.0)
    assert w == 5.0
    assert h == 10.0
    # (x, y) -> (y, width - x)
    expected = [(0.0, 10.0), (0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)]
    assert out[0] == pytest.approx(expected)


def test_origin_corner_stays_in_positive_quadrant_for_all_rotations():
    polys = [_square_10x5()]
    for deg in (0, 90, 180, 270):
        out, w, h = rotate_polylines(polys, deg, 10.0, 5.0)
        for x, y in out[0]:
            assert 0 - 1e-9 <= x <= w + 1e-9, f"x={x} out of [0, {w}] at deg={deg}"
            assert 0 - 1e-9 <= y <= h + 1e-9, f"y={y} out of [0, {h}] at deg={deg}"


def test_invalid_rotation_raises():
    with pytest.raises(ValueError):
        rotate_polylines([], 45, 10.0, 5.0)
    with pytest.raises(ValueError):
        rotate_polylines([], 91, 10.0, 5.0)


def test_empty_polylines_passes_through():
    out, w, h = rotate_polylines([], 90, 10.0, 5.0)
    assert out == []
    # Dimensions still swap for 90°
    assert w == 5.0
    assert h == 10.0


def test_full_360_round_trip_returns_to_original_geometry():
    polys = [_square_10x5(), [(2.0, 1.0), (8.0, 3.0)]]
    rotated, w, h = rotate_polylines(polys, 90, 10.0, 5.0)
    rotated, w, h = rotate_polylines(rotated, 90, w, h)
    rotated, w, h = rotate_polylines(rotated, 90, w, h)
    rotated, w, h = rotate_polylines(rotated, 90, w, h)
    assert w == 10.0 and h == 5.0
    # Each polyline should be back to its original (within float precision)
    for actual, original in zip(rotated, polys):
        for (ax, ay), (ox, oy) in zip(actual, original):
            assert ax == pytest.approx(ox, abs=1e-9)
            assert ay == pytest.approx(oy, abs=1e-9)

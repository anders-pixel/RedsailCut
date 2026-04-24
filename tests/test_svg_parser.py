import math
from pathlib import Path

import pytest
from svgelements import Arc, CubicBezier, Line, Point, QuadraticBezier

from redsailcut.svg_parser import (
    _fast_segment_length,
    polyline_bbox,
    svg_to_polylines,
    total_cut_length_mm,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _write_svg(tmp_path: Path, name: str, body: str, width_mm: float,
               height_mm: float, viewbox: str) -> Path:
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width_mm}mm" height="{height_mm}mm" viewBox="{viewbox}">\n'
        f'{body}\n</svg>\n'
    )
    path = tmp_path / name
    path.write_text(svg)
    return path


def test_simple_square_fixture_has_four_sides_and_closes(tmp_path):
    polylines, w_mm, h_mm = svg_to_polylines(FIXTURES / "simple_square.svg",
                                             target_width_mm=50.0)
    assert w_mm == pytest.approx(50.0)
    assert h_mm == pytest.approx(50.0)
    assert len(polylines) == 1
    perimeter = total_cut_length_mm(polylines)
    # Scaled square: side 50mm, perimeter 200mm
    assert perimeter == pytest.approx(200.0, abs=0.5)


def test_simple_square_produces_exactly_five_points_no_oversampling():
    """A square has zero curvature — the parser must NOT uniformly sample
    along its perimeter. Expected output: the move endpoint (0,0), then one
    point per corner, then the closing point back to (0,0) — exactly 5 points.
    """
    polylines, _, _ = svg_to_polylines(FIXTURES / "simple_square.svg",
                                       target_width_mm=50.0)
    assert len(polylines) == 1
    points = polylines[0]
    assert len(points) == 5, f"expected 5 points, got {len(points)}: {points}"
    expected = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0), (0.0, 0.0)]
    for actual, exp in zip(points, expected):
        assert actual[0] == pytest.approx(exp[0], abs=0.01)
        assert actual[1] == pytest.approx(exp[1], abs=0.01)


def test_bbox_of_square_matches_target_width(tmp_path):
    polylines, w_mm, _ = svg_to_polylines(FIXTURES / "simple_square.svg",
                                          target_width_mm=80.0)
    min_x, min_y, max_x, max_y = polyline_bbox(polylines)
    assert min_x == pytest.approx(0.0, abs=0.01)
    assert min_y == pytest.approx(0.0, abs=0.01)
    assert max_x == pytest.approx(80.0, abs=0.5)
    assert max_y == pytest.approx(80.0, abs=0.5)


def test_circle_radial_deviation_under_half_mm():
    # curved_path.svg is a circle centered at (10,10) with r=10 in a 20mm-wide SVG
    polylines, w_mm, h_mm = svg_to_polylines(FIXTURES / "curved_path.svg",
                                             target_width_mm=40.0)
    # After scaling 2x: center (20,20), r=20
    assert w_mm == pytest.approx(40.0)
    assert h_mm == pytest.approx(40.0)
    assert len(polylines) == 1
    points = polylines[0]
    assert len(points) >= 4
    # Max radial deviation from expected circle
    deviations = [abs(math.hypot(x - 20.0, y - 20.0) - 20.0) for x, y in points]
    assert max(deviations) < 0.5, f"worst deviation {max(deviations):.3f} mm"


def test_barcelona_fixture_bbox_matches_artboard_within_tolerance():
    polylines, w_mm, h_mm = svg_to_polylines(FIXTURES / "barcelona.svg",
                                             target_width_mm=400.0)
    assert w_mm == pytest.approx(400.0)
    assert h_mm == pytest.approx(278.41, abs=0.5)
    assert len(polylines) > 0
    min_x, min_y, max_x, max_y = polyline_bbox(polylines)
    # Design has margins inside the artboard, so bbox ⊂ [0,400]×[0,280]
    assert 0 <= min_x
    assert max_x <= 400.0 + 0.1
    assert 0 <= min_y
    assert max_y <= 280.0


def test_reify_bakes_transform_matches_flat_equivalent(tmp_path):
    # Same line (10,10)→(30,10) drawn flat vs via translate(10,10)
    flat = _write_svg(
        tmp_path, "flat.svg",
        '<path d="M 10 10 L 30 10" stroke="black"/>',
        width_mm=40, height_mm=20, viewbox="0 0 40 20",
    )
    transformed = _write_svg(
        tmp_path, "transformed.svg",
        '<g transform="translate(10,10)"><path d="M 0 0 L 20 0" stroke="black"/></g>',
        width_mm=40, height_mm=20, viewbox="0 0 40 20",
    )
    polys_flat, _, _ = svg_to_polylines(flat, target_width_mm=40.0)
    polys_tx, _, _ = svg_to_polylines(transformed, target_width_mm=40.0)

    bbox_flat = polyline_bbox(polys_flat)
    bbox_tx = polyline_bbox(polys_tx)
    for a, b in zip(bbox_flat, bbox_tx):
        assert a == pytest.approx(b, abs=0.05), (
            f"bboxes diverge: {bbox_flat} vs {bbox_tx}")


def test_degenerate_paths_are_skipped(tmp_path):
    # Zero-length path + real line — zero-length one should be skipped
    path = _write_svg(
        tmp_path, "degenerate.svg",
        '<path d="M 5 5 L 5 5" stroke="black"/>'
        '<path d="M 0 0 L 40 0" stroke="black"/>',
        width_mm=40, height_mm=20, viewbox="0 0 40 20",
    )
    polylines, _, _ = svg_to_polylines(path, target_width_mm=40.0)
    assert len(polylines) == 1


def test_adaptive_sampling_density_scales_with_length(tmp_path):
    body = '<path d="M 0 0 A 2 2 0 0 1 4 0" stroke="black"/>'
    small_path = _write_svg(tmp_path, "small.svg", body,
                            width_mm=10, height_mm=10, viewbox="0 0 10 10")
    big_path = _write_svg(tmp_path, "big.svg", body,
                          width_mm=200, height_mm=200, viewbox="0 0 10 10")
    small_polys, _, _ = svg_to_polylines(small_path, target_width_mm=10.0)
    big_polys, _, _ = svg_to_polylines(big_path, target_width_mm=200.0)
    # Big arc (scaled 20x) should sample strictly more densely than small arc
    assert len(big_polys[0]) > len(small_polys[0])
    assert len(big_polys[0]) <= 201  # max 200 steps → 201 points


def test_invalid_target_width_raises():
    with pytest.raises(ValueError):
        svg_to_polylines(FIXTURES / "simple_square.svg", target_width_mm=0.0)
    with pytest.raises(ValueError):
        svg_to_polylines(FIXTURES / "simple_square.svg", target_width_mm=-10.0)


# --- _fast_segment_length unit tests ---------------------------------------

def test_fast_length_exact_for_line():
    line = Line(start=Point(0, 0), end=Point(10, 0))
    assert _fast_segment_length(line) == pytest.approx(10.0)


def test_fast_length_exact_for_diagonal_line():
    line = Line(start=Point(0, 0), end=Point(3, 4))
    assert _fast_segment_length(line) == pytest.approx(5.0)


def test_fast_length_nearly_straight_cubic_within_5pct_of_exact():
    # Nearly-straight cubic: control points slightly off the line
    cb = CubicBezier(
        start=Point(0, 0),
        control1=Point(3.0, 0.1),
        control2=Point(7.0, 0.1),
        end=Point(10.0, 0.0),
    )
    exact = cb.length(error=1e-4)
    approx = _fast_segment_length(cb)
    # Control-polygon is an upper bound; for a nearly-straight curve
    # it should overshoot by well under 5%.
    assert approx >= exact
    assert approx == pytest.approx(exact, rel=0.05)


def test_fast_length_cubic_with_pronounced_bend_is_upper_bound():
    # S-curve: control points yank the curve well off the straight line
    cb = CubicBezier(
        start=Point(0, 0),
        control1=Point(0, 10),
        control2=Point(10, -10),
        end=Point(10, 0),
    )
    exact = cb.length(error=1e-4)
    approx = _fast_segment_length(cb)
    # Control polygon = 10 + sqrt(10²+20²) + 10 = 10 + 22.36 + 10 = 42.36
    # Real arc length of this S ≈ 21 (much shorter because the curve
    # doesn't actually go through the control points). Approx must
    # strictly upper-bound the arc length.
    assert approx > exact
    assert approx == pytest.approx(42.36, abs=0.1)


def test_fast_length_quadratic_bezier_sum_of_two_control_legs():
    qb = QuadraticBezier(
        start=Point(0, 0), control=Point(5, 10), end=Point(10, 0),
    )
    # Expected: sqrt(25+100) + sqrt(25+100) = 2*sqrt(125) ≈ 22.36
    assert _fast_segment_length(qb) == pytest.approx(2 * math.sqrt(125))


def test_fast_length_arc_uses_chord_times_half_pi():
    # Arc with chord of 10 units — approx returns ~15.708 (upper bound).
    arc = Arc(
        start=Point(0, 0),
        end=Point(10, 0),
        rx=5, ry=5, rotation=0, arc=0, sweep=1,
    )
    assert _fast_segment_length(arc) == pytest.approx(10 * math.pi / 2, rel=1e-3)


def test_fast_length_degenerate_line_is_zero():
    line = Line(start=Point(5, 5), end=Point(5, 5))
    assert _fast_segment_length(line) == 0.0


def test_barcelona_parse_under_1_second():
    """Regression test: control-polygon approx should keep this under 1 s."""
    import time
    t0 = time.time()
    polylines, _, _ = svg_to_polylines(FIXTURES / "barcelona.svg",
                                       target_width_mm=400.0)
    elapsed = time.time() - t0
    assert elapsed < 1.0, f"parse took {elapsed:.2f}s (expected <1s)"
    # Geometry should remain functionally unchanged.
    assert len(polylines) == 401

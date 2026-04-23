import math
from pathlib import Path

import pytest

from redsailcut.svg_parser import (
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

import pytest

from redsailcut.hpgl import UNITS_PER_MM, polylines_to_hpgl


def split(hpgl: str) -> list[str]:
    return [ln for ln in hpgl.splitlines() if ln]


def test_empty_polylines_emits_header_and_footer_only():
    out = split(polylines_to_hpgl([], height_mm=100.0))
    assert out == [
        "IN;",
        "SP1;",
        "VS20;",
        "!FS80;",
        "FS80;",
        "PA;",
        "PU0,0;",
        "PU0,0;",
        "SP0;",
    ]


def test_header_command_order_and_parameters():
    out = split(polylines_to_hpgl([], height_mm=100.0, speed_cm_s=15, force_g=120))
    header = out[:7]
    assert header == [
        "IN;",
        "SP1;",
        "VS15;",
        "!FS120;",
        "FS120;",
        "PA;",
        "PU0,0;",
    ]


def test_every_line_ends_with_semicolon():
    poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    out = split(polylines_to_hpgl([poly], height_mm=50.0))
    for line in out:
        assert line.endswith(";"), f"missing semicolon: {line!r}"


def test_horizontal_line_scales_to_40_units_per_mm():
    # 10 mm horizontal line at y = 0 (which is TOP of an 50 mm canvas in SVG
    # coords) — so after Y-flip it sits at the TOP of HPGL coords (y = 50*40).
    poly = [(0.0, 0.0), (10.0, 0.0)]
    out = split(polylines_to_hpgl([poly], height_mm=50.0))
    top_y = 50 * UNITS_PER_MM  # 2000
    assert f"PU0,{top_y};" in out
    assert f"PD400,{top_y};" in out
    assert out.count("PU;") == 1  # one lift after the polyline


def test_y_flip_places_svg_origin_at_top():
    # SVG (0,0) is top-left; with height 100mm, HPGL y should be 100 * 40 = 4000
    poly = [(0.0, 0.0), (1.0, 0.0)]
    out = split(polylines_to_hpgl([poly], height_mm=100.0))
    assert "PU0,4000;" in out


def test_y_flip_places_svg_bottom_at_hpgl_zero():
    # SVG y = height_mm means bottom of canvas; HPGL y should be 0
    poly = [(0.0, 100.0), (1.0, 100.0)]
    out = split(polylines_to_hpgl([poly], height_mm=100.0))
    assert "PU0,0;" in out  # start of polyline, also matches header PU0,0 — so
    # check that there's a travel line for the second point as well
    assert "PD40,0;" in out


def test_rounding_uses_banker_round_not_truncation():
    # 0.0126 mm * 40 = 0.504 → round to 1
    poly_up = [(0.0, 0.0), (0.0126, 0.0)]
    out_up = split(polylines_to_hpgl([poly_up], height_mm=10.0))
    assert any(ln.startswith("PD1,") for ln in out_up)

    # 0.0124 mm * 40 = 0.496 → round to 0
    poly_dn = [(0.0, 0.0), (0.0124, 0.0)]
    out_dn = split(polylines_to_hpgl([poly_dn], height_mm=10.0))
    assert any(ln.startswith("PD0,") for ln in out_dn)


def test_multiple_polylines_each_get_pen_up_lift():
    polys = [
        [(0.0, 0.0), (10.0, 0.0)],
        [(20.0, 0.0), (30.0, 0.0)],
        [(40.0, 0.0), (50.0, 0.0)],
    ]
    out = split(polylines_to_hpgl(polys, height_mm=50.0))
    # One PU; pen-lift after each polyline (not counting the PU<x>,<y>; travels)
    pen_lifts = [ln for ln in out if ln == "PU;"]
    assert len(pen_lifts) == 3


def test_single_point_polyline_is_skipped():
    polys = [[(5.0, 5.0)], [(0.0, 0.0), (1.0, 0.0)]]
    out = split(polylines_to_hpgl(polys, height_mm=10.0))
    # Only one PD should appear (from the second polyline)
    pd_lines = [ln for ln in out if ln.startswith("PD")]
    assert len(pd_lines) == 1


def test_footer_returns_to_origin_and_deselects_pen():
    out = split(polylines_to_hpgl([[(0.0, 0.0), (1.0, 0.0)]], height_mm=10.0))
    assert out[-2] == "PU0,0;"
    assert out[-1] == "SP0;"


def test_invalid_height_raises():
    with pytest.raises(ValueError):
        polylines_to_hpgl([], height_mm=0.0)
    with pytest.raises(ValueError):
        polylines_to_hpgl([], height_mm=-1.0)


@pytest.mark.parametrize("speed", [0, 81, -5])
def test_invalid_speed_raises(speed):
    with pytest.raises(ValueError):
        polylines_to_hpgl([], height_mm=10.0, speed_cm_s=speed)


@pytest.mark.parametrize("force", [0, 201, -1])
def test_invalid_force_raises(force):
    with pytest.raises(ValueError):
        polylines_to_hpgl([], height_mm=10.0, force_g=force)


def test_trailing_newline_on_output():
    out = polylines_to_hpgl([], height_mm=10.0)
    assert out.endswith("\n")

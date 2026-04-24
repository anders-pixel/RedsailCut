"""Parse an SVG into flattened polylines in millimetres.

We rely on svgelements with `reify=True` so all transforms (including nested
`<g transform>` chains and flipped scales) are baked into path coordinates
before we sample. Curves are flattened by *per-segment* adaptive sampling;
straight segments (`Line`/`Close`) emit only their endpoint, so a square
produces exactly the five points you'd expect, not 200 uniform samples along
an already-straight perimeter.
"""

from __future__ import annotations

import math
from pathlib import Path as FsPath

from svgelements import (
    SVG,
    Arc,
    Close,
    CubicBezier,
    Line,
    Move,
    Path,
    QuadraticBezier,
    Shape,
)

Polyline = list[tuple[float, float]]

MIN_SUBPATH_LENGTH_MM = 0.1
MAX_CURVE_STEPS = 200
MIN_CURVE_STEPS = 4
PPI = 96.0

_CURVE_TYPES = (CubicBezier, QuadraticBezier, Arc)


def svg_to_polylines(
    svg_path: str | FsPath,
    target_width_mm: float,
) -> tuple[list[Polyline], float, float]:
    """Parse SVG and return (polylines, width_mm, height_mm).

    Polylines are in SVG coordinate orientation: y grows downward, origin
    top-left. The HPGL layer is responsible for flipping Y.
    """
    if target_width_mm <= 0:
        raise ValueError(f"target_width_mm must be positive, got {target_width_mm}")

    svg = SVG.parse(str(svg_path), reify=True, ppi=PPI)
    src_w = float(svg.width)
    src_h = float(svg.height)
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"SVG has non-positive dimensions: {src_w} x {src_h}")

    scale = target_width_mm / src_w
    height_mm = src_h * scale

    polylines: list[Polyline] = []

    for element in svg.elements():
        if not isinstance(element, Shape):
            continue
        path = Path(element)
        for subpath in path.as_subpaths():
            sub = Path(subpath)
            # Rough length from summed segment approximations — cheap filter
            # before the expensive sampling loop.
            approx_len_mm = sum(_fast_segment_length(s) for s in sub) * scale
            if approx_len_mm < MIN_SUBPATH_LENGTH_MM:
                continue
            polyline = _subpath_to_polyline(sub, scale)
            if len(polyline) >= 2:
                polylines.append(polyline)

    return polylines, target_width_mm, height_mm


def _fast_segment_length(segment) -> float:
    """Approximate segment length in user units.

    Lines (and degenerate Move/Close) get exact Euclidean distance.
    Bezier segments use the control-polygon sum — an upper bound on the
    true arc length, within ~20% on realistic curves, and roughly a
    thousand times cheaper than svgelements' recursive Simpson integration
    (`segment.length(error=1e-3)`). Arcs use a chord-based upper bound
    that's accurate enough for deciding sampling density.

    We only need this for "sample 10 vs 50 points?" decisions, not for
    metrology — over-sampling by a handful of points is free compared to
    the 5 ms per call that `length()` costs.
    """
    if isinstance(segment, (Line, Close, Move)):
        s, e = segment.start, segment.end
        if s is None or e is None:
            return 0.0
        return math.hypot(e.x - s.x, e.y - s.y)

    if isinstance(segment, CubicBezier):
        p = (segment.start, segment.control1, segment.control2, segment.end)
        return (
            math.hypot(p[1].x - p[0].x, p[1].y - p[0].y)
            + math.hypot(p[2].x - p[1].x, p[2].y - p[1].y)
            + math.hypot(p[3].x - p[2].x, p[3].y - p[2].y)
        )

    if isinstance(segment, QuadraticBezier):
        p = (segment.start, segment.control, segment.end)
        return (
            math.hypot(p[1].x - p[0].x, p[1].y - p[0].y)
            + math.hypot(p[2].x - p[1].x, p[2].y - p[1].y)
        )

    if isinstance(segment, Arc):
        s, e = segment.start, segment.end
        if s is None or e is None:
            return 0.0
        chord = math.hypot(e.x - s.x, e.y - s.y)
        # Upper bound for sweeps up to 180°: arc ≤ chord * π/2 ≈ 1.57.
        # Sampling density is insensitive to this being a slight overshoot.
        return chord * 1.5708

    return 0.0


def _subpath_to_polyline(sub: Path, scale: float) -> Polyline:
    polyline: Polyline = []
    for seg in sub:
        if isinstance(seg, Move):
            if seg.end is not None:
                polyline.append((seg.end.x * scale, seg.end.y * scale))
        elif isinstance(seg, _CURVE_TYPES):
            seg_len_mm = _fast_segment_length(seg) * scale
            steps = max(MIN_CURVE_STEPS, min(MAX_CURVE_STEPS, int(seg_len_mm * 2)))
            # Skip i=0 — that's the endpoint of the previous segment, already appended.
            for i in range(1, steps + 1):
                pt = seg.point(i / steps)
                polyline.append((pt.x * scale, pt.y * scale))
        elif isinstance(seg, (Line, Close)):
            if seg.end is not None:
                polyline.append((seg.end.x * scale, seg.end.y * scale))
        else:
            # Unknown segment type — fall back to endpoint only.
            end = getattr(seg, "end", None)
            if end is not None:
                polyline.append((end.x * scale, end.y * scale))
    return polyline


def polyline_bbox(polylines: list[Polyline]) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) over every point. Empty input → zeros."""
    if not polylines:
        return 0.0, 0.0, 0.0, 0.0
    xs = [x for poly in polylines for x, _ in poly]
    ys = [y for poly in polylines for _, y in poly]
    return min(xs), min(ys), max(xs), max(ys)


def total_cut_length_mm(polylines: list[Polyline]) -> float:
    """Sum of segment lengths across all polylines, in mm. Used for time estimation."""
    total = 0.0
    for poly in polylines:
        for (x0, y0), (x1, y1) in zip(poly, poly[1:]):
            dx = x1 - x0
            dy = y1 - y0
            total += (dx * dx + dy * dy) ** 0.5
    return total


def total_travel_length_mm(polylines: list[Polyline]) -> float:
    """Sum of pen-up travel between consecutive polylines, in mm."""
    total = 0.0
    prev_end: tuple[float, float] | None = (0.0, 0.0)  # start at origin
    for poly in polylines:
        if not poly:
            continue
        if prev_end is not None:
            x0, y0 = prev_end
            x1, y1 = poly[0]
            total += ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        prev_end = poly[-1]
    return total

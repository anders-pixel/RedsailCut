"""Parse an SVG into flattened polylines in millimetres.

We rely on svgelements with `reify=True` so all transforms (including nested
`<g transform>` chains and flipped scales) are baked into path coordinates
before we sample. Curves are flattened by uniform parametric sampling.
"""

from __future__ import annotations

from pathlib import Path as FsPath

from svgelements import SVG, Path, Shape

Polyline = list[tuple[float, float]]

MIN_SUBPATH_LENGTH_MM = 0.1
MAX_INTERPOLATION_STEPS = 200
MIN_INTERPOLATION_STEPS = 4
PPI = 96.0


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
            length_user = sub.length(error=1e-3)
            length_mm = length_user * scale
            if length_mm < MIN_SUBPATH_LENGTH_MM:
                continue
            steps = max(
                MIN_INTERPOLATION_STEPS,
                min(MAX_INTERPOLATION_STEPS, int(length_mm * 2)),
            )
            polyline: Polyline = []
            for i in range(steps + 1):
                pt = sub.point(i / steps)
                polyline.append((pt.x * scale, pt.y * scale))
            polylines.append(polyline)

    return polylines, target_width_mm, height_mm


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

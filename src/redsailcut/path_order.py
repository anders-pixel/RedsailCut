"""Sort polylines so inner shapes get cut before the outer shapes that
contain them. When an outer contour is cut first, the vinyl piece loses
its anchor and can shift while the knife works on inner detail — think
of the counter inside an O, A, or D.

The containment test is a bounding-box approximation: polyline A is
"inside" polyline B if A's bbox fits entirely within B's bbox. This is
cheap (O(n²) comparisons, constant per pair) and rare to get wrong on
typical sign-cutting input where shapes are strictly nested or strictly
disjoint. Point-in-polygon would be more precise but is unnecessary in
practice.

Open polylines (start ≠ end) are never containers. They're appended
after the closed, sorted-inside-first block, ordered by their top Y.
"""

from __future__ import annotations

from collections.abc import Sequence

Polyline = list[tuple[float, float]]

CLOSURE_TOLERANCE_MM = 0.1


def sort_inside_first(
    polylines: Sequence[Sequence[tuple[float, float]]],
) -> list[Polyline]:
    closed_polys: list[Polyline] = []
    closed_idx: list[int] = []
    open_polys: list[Polyline] = []
    for idx, p in enumerate(polylines):
        poly = list(p)
        if len(poly) >= 2 and _is_closed(poly):
            closed_polys.append(poly)
            closed_idx.append(idx)
        else:
            open_polys.append(poly)

    bboxes = [_bbox(p) for p in closed_polys]
    depths = [0] * len(closed_polys)
    for i, inner in enumerate(bboxes):
        for j, outer in enumerate(bboxes):
            if i == j:
                continue
            if _bbox_contains(outer, inner):
                depths[i] += 1

    # Sort closed by descending depth. Break ties by original index so the
    # ordering stays stable and deterministic when depths match.
    order = sorted(
        range(len(closed_polys)),
        key=lambda k: (-depths[k], closed_idx[k]),
    )
    sorted_closed = [closed_polys[k] for k in order]

    # Open polylines: order by top-most Y (smallest y in SVG coords).
    sorted_open = sorted(open_polys, key=_min_y)

    return sorted_closed + sorted_open


def sort_nearest_neighbor(
    polylines: Sequence[Sequence[tuple[float, float]]],
    start: tuple[float, float] | None = None,
) -> list[Polyline]:
    """Order paths to minimise pen-up travel without changing path direction."""
    remaining = [list(p) for p in polylines]
    if not remaining:
        return []

    if start is None:
        ordered = [remaining.pop(0)]
    else:
        best_i = min(
            range(len(remaining)),
            key=lambda idx: _distance(start, _first_point(remaining[idx])),
        )
        ordered = [remaining.pop(best_i)]
    current = _last_point(ordered[-1])
    while remaining:
        best_i = min(
            range(len(remaining)),
            key=lambda idx: _distance(current, _first_point(remaining[idx])),
        )
        polyline = remaining.pop(best_i)
        ordered.append(polyline)
        current = _last_point(polyline)
    return ordered


def _is_closed(points: Polyline) -> bool:
    return (
        abs(points[0][0] - points[-1][0]) < CLOSURE_TOLERANCE_MM
        and abs(points[0][1] - points[-1][1]) < CLOSURE_TOLERANCE_MM
    )


def _bbox(points: Polyline) -> tuple[float, float, float, float]:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
) -> bool:
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return ox0 <= ix0 and oy0 <= iy0 and ox1 >= ix1 and oy1 >= iy1


def _min_y(points: Polyline) -> float:
    return min((y for _, y in points), default=0.0)


def _first_point(points: Polyline) -> tuple[float, float]:
    return points[0] if points else (0.0, 0.0)


def _last_point(points: Polyline) -> tuple[float, float]:
    return points[-1] if points else (0.0, 0.0)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return (dx * dx + dy * dy) ** 0.5

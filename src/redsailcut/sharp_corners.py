"""Split polylines at sharp corners so the drag-knife can lift, rotate, and
re-enter the material, instead of dragging through a tight pivot.

Typical problem shapes: italic letterforms (the bottom of an R, k, Z),
ornamental flourishes, thin stars. When the blade is asked to pivot
through a very acute angle, its tip skips instead of cutting, leaving
a micro-bridge that needs a weed knife to finish.

Terminology — *opening angle* at a corner:
  - 180° = perfectly straight (no turn)
  -  90° = right angle
  -   0° = U-turn (segment reverses)

If the opening angle is below `threshold_deg`, the polyline splits there:
one polyline ends at the corner, another begins at the same point with
the next segment. The HPGL layer turns that gap into a pen-up lift.

This post-processing step runs BEFORE `blade_offset.compensate_polylines`
because compensation shifts endpoints and would distort angle readings.

`threshold_deg <= 0` disables the feature (input returned unchanged).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Polyline = list[tuple[float, float]]

_EPS = 1e-9


def add_pivots(
    polylines: Sequence[Sequence[tuple[float, float]]],
    threshold_deg: float = 30.0,
) -> list[Polyline]:
    if threshold_deg <= 0:
        return [list(p) for p in polylines]
    cos_threshold = math.cos(math.radians(threshold_deg))
    result: list[Polyline] = []
    for poly in polylines:
        result.extend(_split_at_sharp_corners(list(poly), cos_threshold))
    return result


def _split_at_sharp_corners(
    points: Polyline, cos_threshold: float
) -> list[Polyline]:
    if len(points) < 3:
        return [points]

    parts: list[Polyline] = []
    current: Polyline = [points[0]]

    for i in range(1, len(points) - 1):
        current.append(points[i])

        prev_pt, curr_pt, next_pt = points[i - 1], points[i], points[i + 1]
        ax = prev_pt[0] - curr_pt[0]
        ay = prev_pt[1] - curr_pt[1]
        bx = next_pt[0] - curr_pt[0]
        by = next_pt[1] - curr_pt[1]
        a_len = math.hypot(ax, ay)
        b_len = math.hypot(bx, by)
        if a_len < _EPS or b_len < _EPS:
            continue  # degenerate segment — can't measure angle
        ax /= a_len
        ay /= a_len
        bx /= b_len
        by /= b_len

        # cos(opening) where opening is the angle between (corner→prev) and
        # (corner→next). Sharp corner -> small opening -> large cosine.
        cos_opening = ax * bx + ay * by
        if cos_opening > cos_threshold:
            parts.append(current)
            current = [curr_pt]

    current.append(points[-1])
    parts.append(current)
    return parts

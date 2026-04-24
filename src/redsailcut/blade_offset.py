"""Drag-knife offset compensation.

A drag-knife blade trails the tool axle by a fixed physical offset. If the
axle follows the intended path exactly, the blade lags behind — corners get
rounded and closed shapes leave a small 'tag' at the starting point.

Compensation pushes the axle path so the BLADE follows the intended one:

- **Offset**: at each corner, extend the endpoint by `offset_mm` along the
  incoming segment's direction. The tool overshoots past the corner, giving
  the blade time to rotate to the new direction before cutting resumes.
- **Overcut**: on closed polylines, continue `overcut_mm` past the closing
  point along the last segment's direction so the blade catches up to the
  starting point and separates the vinyl cleanly.
- **Corner threshold**: only extend at corners whose turn angle exceeds
  `corner_threshold_deg`. Below that, consecutive micro-segments in
  sampled curves would each accumulate a tiny offset and drift the whole
  curve outward.

Default is pen-mode (`offset_mm = 0`): polylines pass through unchanged.
Users must explicitly enable compensation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Polyline = list[tuple[float, float]]

CLOSURE_TOLERANCE_MM = 0.1
_EPS = 1e-9


def compensate_polylines(
    polylines: Sequence[Sequence[tuple[float, float]]],
    offset_mm: float = 0.0,
    overcut_mm: float = 0.0,
    corner_threshold_deg: float = 5.0,
) -> list[Polyline]:
    """Apply drag-knife compensation to every polyline.

    Returns a new list of polylines. When `offset_mm <= 0` the input is
    returned as a deep-ish copy (each polyline becomes a fresh list) so
    callers can always treat the output as owned.
    """
    if offset_mm <= 0:
        return [list(p) for p in polylines]
    return [
        _compensate_polyline(
            list(p), offset_mm, overcut_mm, corner_threshold_deg
        )
        for p in polylines
    ]


def _compensate_polyline(
    points: Polyline,
    offset: float,
    overcut: float,
    corner_threshold_deg: float,
) -> Polyline:
    if len(points) < 2:
        return list(points)

    n = len(points)
    closed = _is_closed(points)
    threshold_cos = math.cos(math.radians(corner_threshold_deg))
    result: Polyline = [points[0]]

    for i in range(1, n):
        prev = points[i - 1]
        curr = points[i]
        dx, dy = curr[0] - prev[0], curr[1] - prev[1]
        length = math.hypot(dx, dy)
        if length < _EPS:
            continue  # skip degenerate segment
        ux, uy = dx / length, dy / length

        extend = _should_extend_at(
            points, i, closed, ux, uy, threshold_cos
        )
        if extend:
            result.append((curr[0] + ux * offset, curr[1] + uy * offset))
        else:
            result.append(curr)

    # Overcut on closed polylines: continue past the last point along the
    # last segment's direction. That direction is what the blade was heading,
    # so extending it is what makes the blade physically reach the start.
    if overcut > 0 and closed and len(points) >= 2:
        last_seg_prev = points[-2]
        last_seg_end = points[-1]
        dx = last_seg_end[0] - last_seg_prev[0]
        dy = last_seg_end[1] - last_seg_prev[1]
        length = math.hypot(dx, dy)
        if length > _EPS:
            ux, uy = dx / length, dy / length
            anchor = result[-1]
            result.append(
                (anchor[0] + ux * overcut, anchor[1] + uy * overcut)
            )

    return result


def _is_closed(points: Polyline) -> bool:
    return (
        abs(points[0][0] - points[-1][0]) < CLOSURE_TOLERANCE_MM
        and abs(points[0][1] - points[-1][1]) < CLOSURE_TOLERANCE_MM
    )


def _should_extend_at(
    points: Polyline,
    i: int,
    closed: bool,
    in_ux: float,
    in_uy: float,
    threshold_cos: float,
) -> bool:
    """Decide whether to apply offset-extension at point i.

    - Inner point: extend only if the turn angle to the next segment
      exceeds the corner threshold.
    - Last point of an OPEN polyline: always extend (it's the final
      endpoint; the blade has to physically reach past it).
    - Last point of a CLOSED polyline: check turn angle to the FIRST
      segment; skip if below threshold (prevents drift on sampled circles).
    """
    n = len(points)
    if i < n - 1:
        out = points[i + 1]
        dx, dy = out[0] - points[i][0], out[1] - points[i][1]
    elif closed:
        # Closing back into the first segment
        out = points[1]
        dx, dy = out[0] - points[0][0], out[1] - points[0][1]
    else:
        return True  # last point of open polyline

    length = math.hypot(dx, dy)
    if length < _EPS:
        return True
    ux, uy = dx / length, dy / length
    cos_turn = in_ux * ux + in_uy * uy
    # cos_turn == 1 → straight (no turn); cos_turn <= threshold_cos → turn exceeds threshold
    return cos_turn <= threshold_cos

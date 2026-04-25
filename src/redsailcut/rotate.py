"""Rotate polylines in 90° increments around the SVG bounding box origin.

After rotation the polylines are translated so the bbox is back at (0, 0)
in the positive quadrant. The function reports the new canvas dimensions —
for 90° and 270° rotations width and height swap.

Positive `rotation_deg` is clockwise in the SVG y-down coordinate system,
matching what the user sees in the preview.
"""

from __future__ import annotations

from collections.abc import Sequence

Polyline = list[tuple[float, float]]

VALID_ROTATIONS = (0, 90, 180, 270)


def rotate_polylines(
    polylines: Sequence[Sequence[tuple[float, float]]],
    rotation_deg: int,
    width_mm: float,
    height_mm: float,
) -> tuple[list[Polyline], float, float]:
    """Rotate every polyline. rotation_deg must be one of 0/90/180/270."""
    norm = rotation_deg % 360
    if norm not in VALID_ROTATIONS:
        raise ValueError(
            f"rotation_deg must be a multiple of 90 (0/90/180/270), got {rotation_deg}"
        )

    if norm == 0:
        return [list(p) for p in polylines], width_mm, height_mm

    if norm == 90:
        # (x, y) -> (height - y, x). New bbox [0, height] × [0, width].
        rotated = [
            [(height_mm - y, x) for x, y in poly] for poly in polylines
        ]
        return rotated, height_mm, width_mm

    if norm == 180:
        rotated = [
            [(width_mm - x, height_mm - y) for x, y in poly] for poly in polylines
        ]
        return rotated, width_mm, height_mm

    # norm == 270
    # (x, y) -> (y, width - x). New bbox [0, height] × [0, width].
    rotated = [
        [(y, width_mm - x) for x, y in poly] for poly in polylines
    ]
    return rotated, height_mm, width_mm

"""Generate HPGL for a Redsail vinyl cutter from polylines in millimetres.

1 HPGL unit = 0.025 mm, i.e. 40 units/mm.
HPGL origin is bottom-left with Y pointing up, so we flip Y relative to SVG.
"""

from collections.abc import Sequence

Polyline = Sequence[tuple[float, float]]

UNITS_PER_MM = 40


def polylines_to_hpgl(
    polylines: Sequence[Polyline],
    height_mm: float,
    speed_cm_s: int = 20,
    force_g: int = 80,
) -> str:
    if height_mm <= 0:
        raise ValueError(f"height_mm must be positive, got {height_mm}")
    if not 1 <= speed_cm_s <= 80:
        raise ValueError(f"speed_cm_s out of range 1..80, got {speed_cm_s}")
    if not 1 <= force_g <= 200:
        raise ValueError(f"force_g out of range 1..200, got {force_g}")

    def to_units(x_mm: float, y_mm: float) -> tuple[int, int]:
        return (
            round(x_mm * UNITS_PER_MM),
            round((height_mm - y_mm) * UNITS_PER_MM),
        )

    lines: list[str] = [
        "IN;",
        "SP1;",
        f"VS{speed_cm_s};",
        f"FS{force_g};",
        "PA;",
        "PU0,0;",
    ]
    # NOTE: we deliberately do NOT emit the HP-GL/2 style `!FS{n};` variant
    # even though it's harmless on paper-authentic HP plotters. Verified on a
    # Redsail RS720C: the `!` prefix is parsed as an unknown command and the
    # cutter discards the rest of the buffer, resulting in a cut that sends
    # bytes fine but never moves the head. Plain `FS{n};` works on the RS720C
    # and every other plotter we'd realistically ship to.

    for polyline in polylines:
        pts = list(polyline)
        if len(pts) < 2:
            continue
        x0, y0 = to_units(*pts[0])
        lines.append(f"PU{x0},{y0};")
        for x_mm, y_mm in pts[1:]:
            xu, yu = to_units(x_mm, y_mm)
            lines.append(f"PD{xu},{yu};")
        lines.append("PU;")

    lines.append("PU0,0;")
    lines.append("SP0;")
    return "\n".join(lines) + "\n"

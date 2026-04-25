"""Generate HPGL for a Redsail vinyl cutter from polylines in millimetres.

1 HPGL unit = 0.025 mm, i.e. 40 units/mm.
HPGL origin is bottom-left with Y pointing up, so we flip Y relative to SVG.
"""

from collections.abc import Sequence
from dataclasses import dataclass
import math
import re

Polyline = Sequence[tuple[float, float]]

UNITS_PER_MM = 40
MAX_PD_COORD_PAIRS = 1
_COORD_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


class HpglSafetyError(ValueError):
    """Raised when generated HPGL contains a movement we should not send."""


@dataclass(frozen=True)
class HpglSafetyReport:
    cut_segments: int
    travel_segments: int
    max_cut_segment_mm: float
    max_travel_segment_mm: float
    max_coordinate_mm: float


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

    normalised_polylines, output_height_mm = _normalise_to_positive_area(
        polylines, height_mm
    )

    def to_units(x_mm: float, y_mm: float) -> tuple[int, int]:
        return (
            round(x_mm * UNITS_PER_MM),
            round((output_height_mm - y_mm) * UNITS_PER_MM),
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

    current_units = (0, 0)
    cut_anything = False
    for polyline in normalised_polylines:
        pts = list(polyline)
        if len(pts) < 2:
            continue
        x0, y0 = to_units(*pts[0])
        lines.append(f"PU{current_units[0]},{current_units[1]};")
        lines.append(f"PU{x0},{y0};")
        current_units = (x0, y0)
        pd_coords: list[str] = []
        for idx, (x_mm, y_mm) in enumerate(pts[1:], start=1):
            xu, yu = to_units(x_mm, y_mm)
            pd_coords.append(f"{xu},{yu}")
            if len(pd_coords) == MAX_PD_COORD_PAIRS or idx == len(pts) - 1:
                lines.append("PD" + ",".join(pd_coords) + ";")
                pd_coords = []
            current_units = (xu, yu)
        cut_anything = True
        # The next path starts with a duplicate coordinate-bearing `PUx,y;`.
        # This lifts the tool and gives the sender a safe settle point without
        # relying on standalone `PU;`, which some Redsail firmwares mis-parse
        # in long streams.

    if cut_anything:
        lines.append(f"PU{current_units[0]},{current_units[1]};")
    lines.append("SP0;")
    return "\n".join(lines) + "\n"


def validate_hpgl_safety(
    hpgl: str,
    *,
    max_cut_segment_mm: float,
) -> HpglSafetyReport:
    """Preflight generated HPGL before streaming it to the cutter.

    The important failure mode is an unintended `PD` connector between two
    shapes. If that exists in the generated file, this catches it before the
    plotter can draw a long diagonal scar across the vinyl.
    """
    if max_cut_segment_mm <= 0:
        raise ValueError("max_cut_segment_mm must be positive")

    x = 0.0
    y = 0.0
    absolute = True
    cut_segments = 0
    travel_segments = 0
    max_cut_units = 0.0
    max_travel_units = 0.0
    max_coordinate_units = 0.0

    for line_no, command in _iter_hpgl_commands(hpgl):
        op = command[:2].upper()
        args = command[2:]

        if op == "IN":
            x = y = 0.0
            absolute = True
            continue
        if op == "PA":
            absolute = True
            continue
        if op == "PR":
            absolute = False
            continue
        if op not in {"PU", "PD"}:
            continue

        numbers = [float(m.group(0)) for m in _COORD_RE.finditer(args)]
        if len(numbers) < 2:
            continue

        for x_arg, y_arg in zip(numbers[0::2], numbers[1::2]):
            target_x = x_arg if absolute else x + x_arg
            target_y = y_arg if absolute else y + y_arg
            if target_x < 0 or target_y < 0:
                raise HpglSafetyError(
                    "HPGL preflight stopped the job: negative coordinates "
                    f"on line {line_no} ({target_x:.0f},{target_y:.0f})."
                )

            distance = math.hypot(target_x - x, target_y - y)
            max_coordinate_units = max(max_coordinate_units, target_x, target_y)
            if op == "PD":
                cut_segments += 1
                max_cut_units = max(max_cut_units, distance)
                distance_mm = distance / UNITS_PER_MM
                if distance_mm > max_cut_segment_mm:
                    raise HpglSafetyError(
                        "HPGL preflight stopped the job: a cutting segment "
                        f"of {distance_mm:.1f} mm on line {line_no}. "
                        f"The limit for this job is {max_cut_segment_mm:.1f} mm."
                    )
            else:
                travel_segments += 1
                max_travel_units = max(max_travel_units, distance)
            x, y = target_x, target_y

    return HpglSafetyReport(
        cut_segments=cut_segments,
        travel_segments=travel_segments,
        max_cut_segment_mm=max_cut_units / UNITS_PER_MM,
        max_travel_segment_mm=max_travel_units / UNITS_PER_MM,
        max_coordinate_mm=max_coordinate_units / UNITS_PER_MM,
    )


def _iter_hpgl_commands(hpgl: str):
    for line_no, line in enumerate(hpgl.splitlines(), start=1):
        for raw in line.split(";"):
            command = raw.strip()
            if command:
                yield line_no, command


def _normalise_to_positive_area(
    polylines: Sequence[Polyline],
    height_mm: float,
) -> tuple[list[list[tuple[float, float]]], float]:
    """Shift geometry into positive HPGL coordinates after cut compensation.

    Drag-knife compensation and overcut can push points slightly outside the
    original SVG artboard. Redsail controllers are much happier with positive
    absolute coordinates, so we translate only when needed and expand the HPGL
    height used for Y-flip accordingly. Normal in-artboard jobs remain
    bit-for-bit compatible with the old coordinate mapping.
    """
    copied = [list(polyline) for polyline in polylines]
    points = [point for polyline in copied for point in polyline]
    if not points:
        return copied, height_mm

    min_x = min(x for x, _ in points)
    min_y = min(y for _, y in points)
    max_y = max(y for _, y in points)
    x_shift = -min_x if min_x < 0 else 0.0
    y_shift = -min_y if min_y < 0 else 0.0
    output_height_mm = max(height_mm + y_shift, max_y + y_shift)

    if x_shift <= 0 and y_shift <= 0 and output_height_mm == height_mm:
        return copied, height_mm

    shifted = [
        [(x + x_shift, y + y_shift) for x, y in polyline]
        for polyline in copied
    ]
    return shifted, output_height_mm

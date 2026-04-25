"""Clean and simplify parsed cut geometry for vinyl cutters.

The SVG parser converts paths into polylines. Real-world SVGs often come from
bitmap tracing or filled silhouette conversion, so they can contain thousands
of tiny jitter segments that make stepper-based cutters vibrate. This module
keeps the visible shape within a small tolerance while removing redundant
points and returning a report that the UI can show on import.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

Polyline = list[tuple[float, float]]


@dataclass(frozen=True)
class CutOptimizerOptions:
    point_epsilon_mm: float = 0.01
    simplify_tolerance_mm: float = 0.15
    smoothing_iterations: int = 0
    closure_epsilon_mm: float = 0.1
    small_segment_threshold_mm: float = 1.0


@dataclass(frozen=True)
class CutOptimizerReport:
    input_polylines: int
    output_polylines: int
    input_points: int
    output_points: int
    input_segments: int
    output_segments: int
    input_small_segments: int
    output_small_segments: int
    input_cut_length_mm: float
    output_cut_length_mm: float

    @property
    def removed_points(self) -> int:
        return self.input_points - self.output_points


@dataclass(frozen=True)
class CutOptimizerResult:
    polylines: list[Polyline]
    report: CutOptimizerReport


DEFAULT_OPTIONS = CutOptimizerOptions()
IMPORT_CLEANUP_PRESETS: dict[str, CutOptimizerOptions] = {
    "off": CutOptimizerOptions(point_epsilon_mm=0.0, simplify_tolerance_mm=0.0),
    "normal": CutOptimizerOptions(simplify_tolerance_mm=0.15),
    "strong": CutOptimizerOptions(simplify_tolerance_mm=0.35),
    "max": CutOptimizerOptions(simplify_tolerance_mm=0.5),
    "smooth": CutOptimizerOptions(simplify_tolerance_mm=0.35, smoothing_iterations=1),
}


def options_for_import_cleanup(mode: str) -> CutOptimizerOptions:
    return IMPORT_CLEANUP_PRESETS.get(mode, IMPORT_CLEANUP_PRESETS["strong"])


def optimize_polylines_for_cutting(
    polylines: Sequence[Sequence[tuple[float, float]]],
    options: CutOptimizerOptions = DEFAULT_OPTIONS,
) -> CutOptimizerResult:
    input_polylines = [list(poly) for poly in polylines]
    optimized: list[Polyline] = []

    for polyline in input_polylines:
        cleaned = _dedupe_polyline(polyline, options.point_epsilon_mm)
        simplified = _simplify_polyline(cleaned, options)
        smoothed = _smooth_polyline(simplified, options)
        if len(smoothed) >= 2:
            optimized.append(smoothed)

    report = CutOptimizerReport(
        input_polylines=len(input_polylines),
        output_polylines=len(optimized),
        input_points=sum(len(poly) for poly in input_polylines),
        output_points=sum(len(poly) for poly in optimized),
        input_segments=sum(_segment_count(poly) for poly in input_polylines),
        output_segments=sum(_segment_count(poly) for poly in optimized),
        input_small_segments=_small_segment_count(
            input_polylines, options.small_segment_threshold_mm
        ),
        output_small_segments=_small_segment_count(
            optimized, options.small_segment_threshold_mm
        ),
        input_cut_length_mm=_total_length(input_polylines),
        output_cut_length_mm=_total_length(optimized),
    )
    return CutOptimizerResult(optimized, report)


def _dedupe_polyline(points: Polyline, epsilon_mm: float) -> Polyline:
    if epsilon_mm <= 0 or not points:
        return list(points)

    result: Polyline = []
    for x, y in points:
        if result and _point_distance((x, y), result[-1]) < epsilon_mm:
            continue
        result.append((x, y))
    return result


def _simplify_polyline(points: Polyline, options: CutOptimizerOptions) -> Polyline:
    tolerance_mm = options.simplify_tolerance_mm
    if tolerance_mm <= 0 or len(points) <= 3:
        return points
    if _is_closed_polyline(points, options.closure_epsilon_mm):
        ring = points[:-1]
        if len(ring) <= 3:
            return points
        split = max(
            range(1, len(ring)),
            key=lambda i: _point_distance(ring[0], ring[i]),
        )
        first = _rdp(ring[: split + 1], tolerance_mm)
        second = _rdp(ring[split:] + [ring[0]], tolerance_mm)
        simplified = first[:-1] + second
        if _point_distance(simplified[0], simplified[-1]) >= options.closure_epsilon_mm:
            simplified.append(simplified[0])
        return simplified
    return _rdp(points, tolerance_mm)


def _rdp(points: Polyline, tolerance_mm: float) -> Polyline:
    """Ramer-Douglas-Peucker simplification for plotter-friendly output."""
    if len(points) <= 2:
        return points

    start = points[0]
    end = points[-1]
    max_distance = -1.0
    split_index = 0
    for idx, point in enumerate(points[1:-1], start=1):
        distance = _point_to_segment_distance(point, start, end)
        if distance > max_distance:
            max_distance = distance
            split_index = idx

    if max_distance > tolerance_mm:
        left = _rdp(points[: split_index + 1], tolerance_mm)
        right = _rdp(points[split_index:], tolerance_mm)
        return left[:-1] + right
    return [start, end]


def _smooth_polyline(points: Polyline, options: CutOptimizerOptions) -> Polyline:
    result = points
    for _ in range(max(0, options.smoothing_iterations)):
        result = _chaikin(result, options.closure_epsilon_mm)
    return result


def _chaikin(points: Polyline, closure_epsilon_mm: float) -> Polyline:
    if len(points) < 3:
        return points

    if _is_closed_polyline(points, closure_epsilon_mm):
        ring = points[:-1]
        result: Polyline = []
        for idx, p0 in enumerate(ring):
            p1 = ring[(idx + 1) % len(ring)]
            result.append(_lerp(p0, p1, 0.25))
            result.append(_lerp(p0, p1, 0.75))
        result.append(result[0])
        return result

    result = [points[0]]
    for p0, p1 in zip(points, points[1:]):
        result.append(_lerp(p0, p1, 0.25))
        result.append(_lerp(p0, p1, 0.75))
    result.append(points[-1])
    return result


def _lerp(
    a: tuple[float, float],
    b: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _point_to_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    x0, y0 = start
    x1, y1 = end
    dx = x1 - x0
    dy = y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return _point_distance(point, start)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
    proj = (x0 + t * dx, y0 + t * dy)
    return _point_distance(point, proj)


def _point_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _is_closed_polyline(points: Polyline, closure_epsilon_mm: float) -> bool:
    return (
        len(points) >= 3
        and _point_distance(points[0], points[-1]) < closure_epsilon_mm
    )


def _segment_count(points: Sequence[tuple[float, float]]) -> int:
    return max(0, len(points) - 1)


def _small_segment_count(
    polylines: Sequence[Sequence[tuple[float, float]]],
    threshold_mm: float,
) -> int:
    return sum(
        1
        for polyline in polylines
        for start, end in zip(polyline, polyline[1:])
        if _point_distance(start, end) < threshold_mm
    )


def _total_length(polylines: Sequence[Sequence[tuple[float, float]]]) -> float:
    return sum(
        _point_distance(start, end)
        for polyline in polylines
        for start, end in zip(polyline, polyline[1:])
    )

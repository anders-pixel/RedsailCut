"""Typed wrapper around QSettings for RedsailCut.

Keys are namespaced by QSettings(ORG, APP). On first launch, `dry_run` is
True — do not let a user-triggered CUT hit hardware by accident.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from redsailcut.serial_io import FlowControl

ORG = "dk.loow"
APP = "RedsailCut"


class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings(ORG, APP)

    # Serial
    @property
    def port(self) -> str:
        return self._s.value("port", "", type=str)

    @port.setter
    def port(self, v: str) -> None:
        self._s.setValue("port", v)

    @property
    def baud(self) -> int:
        return int(self._s.value("baud", 9600, type=int))

    @baud.setter
    def baud(self, v: int) -> None:
        self._s.setValue("baud", int(v))

    @property
    def flow_control(self) -> FlowControl:
        raw = self._s.value("flow_control", FlowControl.NONE.value, type=str)
        try:
            return FlowControl(raw)
        except ValueError:
            return FlowControl.NONE

    @flow_control.setter
    def flow_control(self, v: FlowControl) -> None:
        self._s.setValue("flow_control", v.value)

    # Cutting parameters
    @property
    def speed(self) -> int:
        return int(self._s.value("speed", 20, type=int))

    @speed.setter
    def speed(self, v: int) -> None:
        self._s.setValue("speed", int(v))

    @property
    def force(self) -> int:
        return int(self._s.value("force", 80, type=int))

    @force.setter
    def force(self, v: int) -> None:
        self._s.setValue("force", int(v))

    # UI state
    @property
    def dry_run(self) -> bool:
        # Default True — first run must not cut by accident
        raw = self._s.value("dry_run", True, type=bool)
        return bool(raw)

    @dry_run.setter
    def dry_run(self, v: bool) -> None:
        self._s.setValue("dry_run", bool(v))

    @property
    def lock_ratio(self) -> bool:
        return bool(self._s.value("lock_ratio", True, type=bool))

    @lock_ratio.setter
    def lock_ratio(self, v: bool) -> None:
        self._s.setValue("lock_ratio", bool(v))

    @property
    def rotation_deg(self) -> int:
        v = int(self._s.value("rotation_deg", 0, type=int))
        return v if v in (0, 90, 180, 270) else 0

    @rotation_deg.setter
    def rotation_deg(self, v: int) -> None:
        self._s.setValue("rotation_deg", int(v))

    @property
    def import_cleanup(self) -> str:
        raw = self._s.value("import_cleanup", "strong", type=str)
        return raw if raw in {"off", "normal", "strong", "max", "smooth"} else "strong"

    @import_cleanup.setter
    def import_cleanup(self, v: str) -> None:
        self._s.setValue("import_cleanup", v)

    # Blade compensation (pen-mode defaults — users opt in)
    @property
    def blade_offset_mm(self) -> float:
        return float(self._s.value("blade_offset_mm", 0.0, type=float))

    @blade_offset_mm.setter
    def blade_offset_mm(self, v: float) -> None:
        self._s.setValue("blade_offset_mm", float(v))

    @property
    def overcut_mm(self) -> float:
        return float(self._s.value("overcut_mm", 0.5, type=float))

    @overcut_mm.setter
    def overcut_mm(self, v: float) -> None:
        self._s.setValue("overcut_mm", float(v))

    @property
    def corner_threshold_deg(self) -> int:
        return int(self._s.value("corner_threshold_deg", 5, type=int))

    @corner_threshold_deg.setter
    def corner_threshold_deg(self, v: int) -> None:
        self._s.setValue("corner_threshold_deg", int(v))

    # Path ordering
    @property
    def sort_inside_first(self) -> bool:
        return bool(self._s.value("sort_inside_first", True, type=bool))

    @sort_inside_first.setter
    def sort_inside_first(self, v: bool) -> None:
        self._s.setValue("sort_inside_first", bool(v))

    # Sharp-corner pivots
    @property
    def lift_sharp_corners(self) -> bool:
        return bool(self._s.value("lift_sharp_corners", True, type=bool))

    @lift_sharp_corners.setter
    def lift_sharp_corners(self, v: bool) -> None:
        self._s.setValue("lift_sharp_corners", bool(v))

    @property
    def sharp_corner_threshold_deg(self) -> int:
        return int(self._s.value("sharp_corner_threshold_deg", 30, type=int))

    @sharp_corner_threshold_deg.setter
    def sharp_corner_threshold_deg(self, v: int) -> None:
        self._s.setValue("sharp_corner_threshold_deg", int(v))

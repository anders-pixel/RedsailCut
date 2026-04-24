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

"""Serial communication with a Redsail vinyl cutter.

Flow control defaults to hardware RTS/CTS; some CH340-based USB-to-serial
adapters advertise it but mishandle it — fall back to XON/XOFF via the
FlowControl enum if the user reports buffer overruns.

Errors are normalised into `SerialError`, a user-facing exception whose
message is safe to surface verbatim in a dialog or log line.
"""

from __future__ import annotations

import enum
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import serial

ABORT_SEQUENCE = "PU;PU0,0;SP0;\n"


class FlowControl(enum.Enum):
    NONE = "none"
    RTS_CTS = "rtscts"
    XON_XOFF = "xonxoff"


class SerialError(Exception):
    """User-facing serial error. The message is safe to show."""


class SerialPortLike(Protocol):
    def write(self, data: bytes) -> int: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


def open_cutter(
    port: str,
    baud: int = 9600,
    flow: FlowControl = FlowControl.NONE,
) -> serial.Serial:
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
            write_timeout=5.0,
            rtscts=(flow is FlowControl.RTS_CTS),
            xonxoff=(flow is FlowControl.XON_XOFF),
            dsrdtr=False,
        )
        # Assert DTR and RTS high explicitly. On FT232R the post-open state of
        # these lines isn't guaranteed; some cutters (Redsail RS720C included)
        # apparently refuse to process incoming bytes until they see the host
        # driving them high. Without this step, bytes stream out over the wire
        # but the cutter head never moves — identical symptom to wiring failure.
        # The 300 ms settle matches what worked in the terminal smoke test.
        if flow is not FlowControl.RTS_CTS:
            ser.rts = True
        ser.dtr = True
        time.sleep(0.3)
        ser.reset_input_buffer()
        return ser
    except PermissionError as e:
        raise SerialError(
            f"macOS blocked access to the port ({port}). "
            "Open System Settings > Privacy & Security, allow RedsailCut "
            "to use serial communication, and try again."
        ) from e
    except serial.SerialException as e:
        # pyserial sometimes wraps PermissionError inside SerialException
        if isinstance(e.__cause__, PermissionError) or "permission" in str(e).lower():
            raise SerialError(
                f"macOS blocked access to the port ({port}). "
                "Open System Settings > Privacy & Security, allow RedsailCut "
                "to use serial communication, and try again."
            ) from e
        raise SerialError(f"Could not open port {port}: {e}") from e


DEFAULT_INTER_LINE_DELAY_S = 0.015
HPGL_UNITS_PER_MM = 40
MOTION_LOOKAHEAD_S = 0.15
PEN_UP_SETTLE_DELAY_S = 0.12
PEN_UP_TRAVEL_SPEED_FACTOR = 1.7
_VS_DEFAULT_CM_S = 20
_COORD_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class _HpglPacingState:
    x: float = 0.0
    y: float = 0.0
    absolute: bool = True
    speed_cm_s: float = _VS_DEFAULT_CM_S
    queued_motion_s: float = 0.0
    pen_down: bool = False


def send_hpgl(
    ser: SerialPortLike,
    hpgl: str,
    on_progress: Callable[[int, int], None],
    abort_flag: threading.Event,
    inter_line_delay_s: float = DEFAULT_INTER_LINE_DELAY_S,
) -> bool:
    """Send HPGL line-by-line. Returns True on normal completion, False if aborted.

    `inter_line_delay_s` is the minimum pacing delay. Coordinate-bearing
    `PU`/`PD` commands are paced by estimated physical move time while allowing
    a small lookahead queue. That keeps the cutter fed through curves without
    dumping the whole job into its small serial buffer.
    """
    if hasattr(ser, "reset_output_buffer"):
        try:
            ser.reset_output_buffer()
        except Exception:
            pass
    lines = hpgl.splitlines(keepends=True)
    total = len(lines)
    pacing = _HpglPacingState()
    for i, line in enumerate(lines):
        if abort_flag.is_set():
            ser.write(ABORT_SEQUENCE.encode("ascii"))
            ser.flush()
            return False
        ser.write(line.encode("ascii"))
        ser.flush()
        on_progress(i + 1, total)
        if inter_line_delay_s > 0:
            delay_s = _line_delay_s(line, pacing, inter_line_delay_s)
            if delay_s > 0:
                time.sleep(delay_s)
    return True


def _line_delay_s(
    line: str,
    state: _HpglPacingState,
    minimum_delay_s: float,
) -> float:
    """Return the delay needed after sending one HPGL command line.

    This parser intentionally covers the small HPGL subset we generate:
    `VS`, `PA`, `PR`, `PU` and `PD` with optional coordinate pairs.
    Unknown commands get the minimum delay.
    """
    cmd = line.strip().rstrip(";")
    if not cmd:
        return minimum_delay_s

    op = cmd[:2].upper()
    args = cmd[2:]

    if op == "VS":
        try:
            speed = float(args)
        except ValueError:
            return _consume_queued_motion(state, minimum_delay_s)
        if speed > 0:
            state.speed_cm_s = speed
        return _consume_queued_motion(state, minimum_delay_s)

    if op == "PA":
        state.absolute = True
        return _consume_queued_motion(state, minimum_delay_s)

    if op == "PR":
        state.absolute = False
        return _consume_queued_motion(state, minimum_delay_s)

    if op not in {"PU", "PD"}:
        return _consume_queued_motion(state, minimum_delay_s)

    was_pen_down = state.pen_down
    numbers = [float(m.group(0)) for m in _COORD_RE.finditer(args)]
    state.pen_down = op == "PD"
    if len(numbers) < 2:
        if op == "PU" and was_pen_down:
            return max(minimum_delay_s, PEN_UP_SETTLE_DELAY_S)
        return 0.0

    distance_units = 0.0
    for x_arg, y_arg in zip(numbers[0::2], numbers[1::2]):
        if state.absolute:
            target_x, target_y = x_arg, y_arg
        else:
            target_x, target_y = state.x + x_arg, state.y + y_arg
        distance_units += math.hypot(target_x - state.x, target_y - state.y)
        state.x, state.y = target_x, target_y

    speed_units_s = max(state.speed_cm_s, 1.0) * 10.0 * HPGL_UNITS_PER_MM
    if op == "PU":
        speed_units_s *= PEN_UP_TRAVEL_SPEED_FACTOR
    move_delay_s = distance_units / speed_units_s
    lift_delay_s = PEN_UP_SETTLE_DELAY_S if op == "PU" and was_pen_down else 0.0
    if move_delay_s <= 0:
        return max(minimum_delay_s, lift_delay_s) if lift_delay_s > 0 else 0.0
    state.queued_motion_s += move_delay_s
    delay_s = max(
        minimum_delay_s,
        lift_delay_s,
        state.queued_motion_s - MOTION_LOOKAHEAD_S,
    )
    return _consume_queued_motion(state, delay_s)


def _consume_queued_motion(state: _HpglPacingState, delay_s: float) -> float:
    state.queued_motion_s = max(0.0, state.queued_motion_s - delay_s)
    return delay_s


def probe_cutter(
    port: str,
    baud: int,
    flow: FlowControl = FlowControl.NONE,
    queries: tuple[str, ...] = ("OI;", "OS;", "OE;", "OA;"),
    read_timeout_s: float = 2.0,
) -> str:
    """Connection diagnostic: send HPGL identification queries and return
    whatever the cutter replies. If the cutter is wired, powered, and in
    HPGL mode, `OI;` yields a model string; no reply means bytes aren't
    making it there (or the cutter doesn't understand HP-GL/2 queries)."""
    import time
    ser = open_cutter(port, baud, flow=flow)
    try:
        ser.timeout = read_timeout_s
        ser.reset_input_buffer()
        lines: list[str] = []
        for q in queries:
            ser.write(q.encode("ascii") + b"\n")
            ser.flush()
            time.sleep(0.2)  # give cutter time to respond
            chunk = ser.read(256)
            text = chunk.decode("ascii", errors="replace").strip() if chunk else ""
            lines.append(f"  {q:<5} -> {text!r}" if text else f"  {q:<5} -> (no reply)")
        return "\n".join(lines)
    finally:
        try:
            ser.close()
        except Exception:
            pass

"""Serial communication with a Redsail vinyl cutter.

Flow control defaults to hardware RTS/CTS; some CH340-based USB-to-serial
adapters advertise it but mishandle it — fall back to XON/XOFF via the
FlowControl enum if the user reports buffer overruns.

Errors are normalised into `SerialError`, a user-facing exception whose
message (in Danish, to match the GUI language) is safe to surface verbatim
in a dialog or log line.
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
    """User-facing serial error. The message is in Danish and safe to show."""


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
            f"macOS blokerer adgangen til porten ({port}). "
            "Åbn Systemindstillinger > Privatliv & Sikkerhed og tillad "
            "RedsailCut at bruge seriel kommunikation, og prøv igen."
        ) from e
    except serial.SerialException as e:
        # pyserial sometimes wraps PermissionError inside SerialException
        if isinstance(e.__cause__, PermissionError) or "permission" in str(e).lower():
            raise SerialError(
                f"macOS blokerer adgangen til porten ({port}). "
                "Åbn Systemindstillinger > Privatliv & Sikkerhed og tillad "
                "RedsailCut at bruge seriel kommunikation, og prøv igen."
            ) from e
        raise SerialError(f"Kunne ikke åbne porten {port}: {e}") from e


DEFAULT_INTER_LINE_DELAY_S = 0.02
HPGL_UNITS_PER_MM = 40
_VS_DEFAULT_CM_S = 20
_COORD_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class _HpglPacingState:
    x: float = 0.0
    y: float = 0.0
    absolute: bool = True
    speed_cm_s: float = _VS_DEFAULT_CM_S


def send_hpgl(
    ser: SerialPortLike,
    hpgl: str,
    on_progress: Callable[[int, int], None],
    abort_flag: threading.Event,
    inter_line_delay_s: float = DEFAULT_INTER_LINE_DELAY_S,
) -> bool:
    """Send HPGL line-by-line. Returns True on normal completion, False if aborted.

    `inter_line_delay_s` is the minimum pacing delay. Coordinate-bearing
    `PU`/`PD` commands wait for their estimated physical move time too, so
    the cutter's small input buffer doesn't receive hundreds of commands while
    the carriage is still executing one long move. With no reliable hardware
    flow control, overflowing that buffer silently drops commands and desyncs
    pen state/absolute position, producing random-looking lines.
    """
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
            time.sleep(_line_delay_s(line, pacing, inter_line_delay_s))
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
            return minimum_delay_s
        if speed > 0:
            state.speed_cm_s = speed
        return minimum_delay_s

    if op == "PA":
        state.absolute = True
        return minimum_delay_s

    if op == "PR":
        state.absolute = False
        return minimum_delay_s

    if op not in {"PU", "PD"}:
        return minimum_delay_s

    numbers = [float(m.group(0)) for m in _COORD_RE.finditer(args)]
    if len(numbers) < 2:
        return minimum_delay_s

    distance_units = 0.0
    for x_arg, y_arg in zip(numbers[0::2], numbers[1::2]):
        if state.absolute:
            target_x, target_y = x_arg, y_arg
        else:
            target_x, target_y = state.x + x_arg, state.y + y_arg
        distance_units += math.hypot(target_x - state.x, target_y - state.y)
        state.x, state.y = target_x, target_y

    speed_units_s = max(state.speed_cm_s, 1.0) * 10.0 * HPGL_UNITS_PER_MM
    move_delay_s = distance_units / speed_units_s
    return max(minimum_delay_s, move_delay_s)


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

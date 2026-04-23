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
import threading
from collections.abc import Callable
from typing import Protocol

import serial

ABORT_SEQUENCE = "PU;PU0,0;SP0;\n"


class FlowControl(enum.Enum):
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
    flow: FlowControl = FlowControl.RTS_CTS,
) -> serial.Serial:
    try:
        return serial.Serial(
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


def send_hpgl(
    ser: SerialPortLike,
    hpgl: str,
    on_progress: Callable[[int, int], None],
    abort_flag: threading.Event,
) -> bool:
    """Send HPGL line-by-line. Returns True on normal completion, False if aborted."""
    lines = hpgl.splitlines(keepends=True)
    total = len(lines)
    for i, line in enumerate(lines):
        if abort_flag.is_set():
            ser.write(ABORT_SEQUENCE.encode("ascii"))
            ser.flush()
            return False
        ser.write(line.encode("ascii"))
        ser.flush()
        on_progress(i + 1, total)
    return True


def probe_cutter(
    port: str,
    baud: int,
    flow: FlowControl = FlowControl.RTS_CTS,
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

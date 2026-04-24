import threading
from unittest.mock import MagicMock, call, patch

import pytest
import serial

from redsailcut.serial_io import (
    ABORT_SEQUENCE,
    FlowControl,
    SerialError,
    open_cutter,
    send_hpgl,
)


class FakePort:
    """In-memory SerialPortLike that records writes and flushes in order."""

    def __init__(self):
        self.events: list[tuple[str, bytes | None]] = []

    def write(self, data: bytes) -> int:
        self.events.append(("write", data))
        return len(data)

    def flush(self) -> None:
        self.events.append(("flush", None))

    def close(self) -> None:
        self.events.append(("close", None))


def test_send_hpgl_writes_every_line_in_order_followed_by_flush():
    hpgl = "IN;\nSP1;\nVS20;\nPU0,0;\n"
    port = FakePort()
    aborted = threading.Event()
    progress: list[tuple[int, int]] = []

    # Zero delay to keep unit tests fast; pacing semantics are covered below.
    result = send_hpgl(port, hpgl, lambda d, t: progress.append((d, t)),
                      aborted, inter_line_delay_s=0.0)

    assert result is True
    writes = [e for e in port.events if e[0] == "write"]
    assert [w[1] for w in writes] == [
        b"IN;\n", b"SP1;\n", b"VS20;\n", b"PU0,0;\n",
    ]
    # Every write is immediately followed by a flush
    for i, (kind, _) in enumerate(port.events):
        if kind == "write":
            assert port.events[i + 1][0] == "flush"
    assert progress == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_abort_flag_mid_stream_triggers_emergency_sequence_and_stops():
    # Use a progress callback that flips the abort flag after N lines
    hpgl = "IN;\nSP1;\nVS20;\nPU0,0;\nPD10,10;\nPD20,20;\nSP0;\n"
    port = FakePort()
    aborted = threading.Event()
    sent_before_abort = []

    def on_progress(done: int, total: int):
        sent_before_abort.append(done)
        if done == 3:  # after VS20; is written, request abort
            aborted.set()

    result = send_hpgl(port, hpgl, on_progress, aborted, inter_line_delay_s=0.0)

    assert result is False  # aborted
    writes = [e[1] for e in port.events if e[0] == "write"]
    # Exactly the first 3 lines should have been written normally
    assert writes[:3] == [b"IN;\n", b"SP1;\n", b"VS20;\n"]
    # Then the abort sequence
    assert writes[3] == ABORT_SEQUENCE.encode("ascii")
    # No further normal lines after abort
    assert len(writes) == 4
    assert sent_before_abort == [1, 2, 3]
    # Abort sequence write is followed by a flush and nothing else
    assert port.events[-2:] == [("write", ABORT_SEQUENCE.encode("ascii")), ("flush", None)]


def test_abort_on_empty_hpgl_completes_without_sending():
    port = FakePort()
    aborted = threading.Event()
    result = send_hpgl(port, "", lambda d, t: None, aborted, inter_line_delay_s=0.0)
    assert result is True
    assert port.events == []


def test_inter_line_delay_paces_transmission():
    import time as _time
    port = FakePort()
    aborted = threading.Event()
    hpgl = "A;\nB;\nC;\nD;\nE;\n"
    t0 = _time.monotonic()
    send_hpgl(port, hpgl, lambda d, t: None, aborted, inter_line_delay_s=0.01)
    elapsed = _time.monotonic() - t0
    # 5 lines * 10 ms = 50 ms minimum
    assert elapsed >= 0.045, f"expected ≥ 45 ms pacing, saw {elapsed*1000:.1f} ms"


def test_motion_pacing_waits_for_physical_pd_move_time():
    port = FakePort()
    aborted = threading.Event()
    # 1200 HPGL units = 30 mm. VS3 = 30 mm/s, so the move takes ~1 second.
    hpgl = "VS3;\nPU0,0;\nPD1200,0;\n"

    with patch("redsailcut.serial_io.time.sleep") as sleep:
        send_hpgl(port, hpgl, lambda d, t: None, aborted, inter_line_delay_s=0.02)

    assert sleep.call_args_list == [call(0.02), call(0.02), call(1.0)]


def test_motion_pacing_waits_for_physical_pu_travel_too():
    port = FakePort()
    aborted = threading.Event()
    # 400 HPGL units = 10 mm. VS10 = 100 mm/s, so the travel takes ~0.1 s.
    hpgl = "VS10;\nPU400,0;\n"

    with patch("redsailcut.serial_io.time.sleep") as sleep:
        send_hpgl(port, hpgl, lambda d, t: None, aborted, inter_line_delay_s=0.02)

    assert sleep.call_args_list == [call(0.02), call(0.1)]


def test_zero_inter_line_delay_disables_all_pacing_sleep():
    port = FakePort()
    aborted = threading.Event()
    hpgl = "VS3;\nPU0,0;\nPD1200,0;\n"

    with patch("redsailcut.serial_io.time.sleep") as sleep:
        send_hpgl(port, hpgl, lambda d, t: None, aborted, inter_line_delay_s=0.0)

    sleep.assert_not_called()


def test_permission_error_translated_to_danish_systemindstillinger_message():
    with patch("redsailcut.serial_io.serial.Serial",
               side_effect=PermissionError(13, "Permission denied")):
        with pytest.raises(SerialError) as exc:
            open_cutter("/dev/cu.fake", 9600)
    msg = str(exc.value)
    assert "Systemindstillinger" in msg
    assert "/dev/cu.fake" in msg


def test_serial_exception_wrapping_permission_is_also_translated():
    # pyserial on some OS wraps PermissionError inside SerialException
    inner = PermissionError(13, "Permission denied")
    outer = serial.SerialException("could not open port: Permission denied")
    outer.__cause__ = inner
    with patch("redsailcut.serial_io.serial.Serial", side_effect=outer):
        with pytest.raises(SerialError) as exc:
            open_cutter("/dev/cu.fake", 9600)
    assert "Systemindstillinger" in str(exc.value)


def test_generic_serial_exception_produces_non_permission_message():
    with patch("redsailcut.serial_io.serial.Serial",
               side_effect=serial.SerialException("no such device")):
        with pytest.raises(SerialError) as exc:
            open_cutter("/dev/cu.fake", 9600)
    assert "Systemindstillinger" not in str(exc.value)
    assert "/dev/cu.fake" in str(exc.value)


def test_open_cutter_defaults_to_no_flow_control():
    # Redsail RS720C (and similar cheap cutters) don't wire handshake lines,
    # so defaulting to any handshake silently blocks or false-OKs.
    with patch("redsailcut.serial_io.serial.Serial") as mock:
        open_cutter("/dev/cu.fake", 19200)
    kwargs = mock.call_args.kwargs
    assert kwargs["rtscts"] is False
    assert kwargs["xonxoff"] is False
    assert kwargs["baudrate"] == 19200


def test_open_cutter_rtscts_opt_in():
    with patch("redsailcut.serial_io.serial.Serial") as mock:
        open_cutter("/dev/cu.fake", 9600, flow=FlowControl.RTS_CTS)
    kwargs = mock.call_args.kwargs
    assert kwargs["rtscts"] is True
    assert kwargs["xonxoff"] is False


def test_open_cutter_xonxoff_opt_in():
    with patch("redsailcut.serial_io.serial.Serial") as mock:
        open_cutter("/dev/cu.fake", 9600, flow=FlowControl.XON_XOFF)
    kwargs = mock.call_args.kwargs
    assert kwargs["rtscts"] is False
    assert kwargs["xonxoff"] is True

"""PyQt6 GUI for RedsailCut.

Main window layout follows §4 of the spec. The cutting job runs on a
background QThread; the UI thread remains responsive. Errors from the
serial layer propagate as `SerialError` and surface in a dialog + log.
"""

from __future__ import annotations

import datetime as dt
import sys
import threading
from pathlib import Path

import serial.tools.list_ports
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from redsailcut.hpgl import polylines_to_hpgl
from redsailcut.preview import PreviewWidget
from redsailcut.serial_io import (
    FlowControl,
    SerialError,
    open_cutter,
    send_hpgl,
)
from redsailcut.settings import AppSettings
from redsailcut.svg_parser import (
    Polyline,
    svg_to_polylines,
    total_cut_length_mm,
)

BAUD_CHOICES = [9600, 19200, 38400]


def _now() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


class CutJob(QThread):
    """Background job: open port, stream HPGL, close port."""

    progress = pyqtSignal(int, int)
    log = pyqtSignal(str)
    finished_ok = pyqtSignal(bool)  # True on success, False on abort
    error = pyqtSignal(str)

    def __init__(self, port: str, baud: int, flow: FlowControl, hpgl: str):
        super().__init__()
        self._port = port
        self._baud = baud
        self._flow = flow
        self._hpgl = hpgl
        self.abort_flag = threading.Event()

    def run(self) -> None:
        try:
            ser = open_cutter(self._port, self._baud, flow=self._flow)
        except SerialError as e:
            self.error.emit(str(e))
            return
        self.log.emit(f"Port åbnet: {self._port} @ {self._baud} baud")
        try:
            ok = send_hpgl(ser, self._hpgl, self.progress.emit, self.abort_flag)
        except Exception as e:  # noqa: BLE001  — surface any unexpected I/O error
            self.error.emit(f"Fejl under skæring: {e}")
            return
        finally:
            try:
                ser.close()
                self.log.emit("Port lukket.")
            except Exception:
                pass
        self.finished_ok.emit(ok)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RedsailCut")
        self.resize(1100, 760)
        self.setAcceptDrops(True)

        self._settings = AppSettings()
        self._svg_path: Path | None = None
        self._src_width_mm: float = 0.0
        self._src_height_mm: float = 0.0
        self._cut_job: CutJob | None = None

        self._build_menu()
        self._build_ui()
        self._load_ports()
        self._apply_settings_to_ui()
        self._update_cut_button_state()
        self._log("Klar. Åbn en SVG for at starte.")

    # --- UI construction ---------------------------------------------------
    def _build_menu(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        act_open = QAction("&Open SVG…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._pick_file)
        file_menu.addAction(act_open)
        file_menu.addSeparator()
        act_quit = QAction("&Quit", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        settings_menu = mb.addMenu("&Settings")
        adv = settings_menu.addMenu("&Advanced")
        flow_menu = adv.addMenu("Serial flow control")
        self._flow_group = QActionGroup(self)
        self._flow_group.setExclusive(True)
        for mode, label in [
            (FlowControl.RTS_CTS, "RTS/CTS (default)"),
            (FlowControl.XON_XOFF, "XON/XOFF (fallback)"),
        ]:
            a = QAction(label, self, checkable=True)
            a.setData(mode)
            a.triggered.connect(self._on_flow_control_changed)
            self._flow_group.addAction(a)
            flow_menu.addAction(a)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Top bar: Open + file label
        top = QHBoxLayout()
        self._btn_open = QPushButton("Open SVG…")
        self._btn_open.clicked.connect(self._pick_file)
        self._file_label = QLabel("No file loaded")
        self._file_label.setStyleSheet("color: #666;")
        top.addWidget(self._btn_open)
        top.addWidget(self._file_label, stretch=1)
        root.addLayout(top)

        # Main splitter: preview | controls
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, stretch=1)

        self._preview = PreviewWidget()
        splitter.addWidget(self._preview)

        controls = QWidget()
        c_layout = QVBoxLayout(controls)
        splitter.addWidget(controls)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        # Size group
        size_box = QGroupBox("Size")
        sf = QFormLayout(size_box)
        self._spin_width = QDoubleSpinBox()
        self._spin_width.setRange(1.0, 2000.0)
        self._spin_width.setSuffix(" mm")
        self._spin_width.setDecimals(1)
        self._spin_width.valueChanged.connect(self._on_width_changed)
        self._spin_height = QDoubleSpinBox()
        self._spin_height.setRange(1.0, 2000.0)
        self._spin_height.setSuffix(" mm")
        self._spin_height.setDecimals(1)
        self._spin_height.valueChanged.connect(self._on_height_changed)
        self._chk_lock = QCheckBox("Lock aspect ratio")
        self._chk_lock.setChecked(True)
        self._chk_lock.toggled.connect(lambda v: setattr(self._settings, "lock_ratio", v))
        sf.addRow("Width:", self._spin_width)
        sf.addRow("Height:", self._spin_height)
        sf.addRow(self._chk_lock)
        c_layout.addWidget(size_box)

        # Cutter group
        cut_box = QGroupBox("Cutter")
        cf = QFormLayout(cut_box)
        port_row = QHBoxLayout()
        self._cmb_port = QComboBox()
        self._cmb_port.currentIndexChanged.connect(self._on_port_changed)
        self._btn_refresh = QPushButton("↻")
        self._btn_refresh.setFixedWidth(32)
        self._btn_refresh.setToolTip("Refresh port list")
        self._btn_refresh.clicked.connect(self._load_ports)
        port_row.addWidget(self._cmb_port, stretch=1)
        port_row.addWidget(self._btn_refresh)
        cf.addRow("Port:", port_row)

        self._cmb_baud = QComboBox()
        for b in BAUD_CHOICES:
            self._cmb_baud.addItem(str(b), b)
        self._cmb_baud.currentIndexChanged.connect(self._on_baud_changed)
        cf.addRow("Baud:", self._cmb_baud)
        c_layout.addWidget(cut_box)

        # Cutting parameters group
        params_box = QGroupBox("Cutting parameters")
        pf = QFormLayout(params_box)
        self._spin_speed = QSpinBox()
        self._spin_speed.setRange(1, 80)
        self._spin_speed.setSuffix(" cm/s")
        self._spin_speed.valueChanged.connect(self._on_speed_changed)
        self._spin_force = QSpinBox()
        self._spin_force.setRange(1, 200)
        self._spin_force.setSuffix(" g")
        self._spin_force.valueChanged.connect(self._on_force_changed)
        pf.addRow("Speed:", self._spin_speed)
        pf.addRow("Force:", self._spin_force)
        c_layout.addWidget(params_box)

        # Dry run + est time
        self._chk_dry = QCheckBox("Dry run  —  save .plt to Desktop")
        self._chk_dry.toggled.connect(self._on_dry_run_changed)
        c_layout.addWidget(self._chk_dry)

        self._lbl_est = QLabel("Est. time: —")
        c_layout.addWidget(self._lbl_est)

        # CUT / Stop
        self._btn_cut = QPushButton("CUT")
        self._btn_cut.setMinimumHeight(44)
        self._btn_cut.clicked.connect(self._on_cut_clicked)
        c_layout.addWidget(self._btn_cut)

        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setMinimumHeight(36)
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        self._btn_stop.setVisible(False)
        c_layout.addWidget(self._btn_stop)

        c_layout.addStretch(1)

        # Log pane
        self._log_pane = QPlainTextEdit()
        self._log_pane.setReadOnly(True)
        self._log_pane.setMaximumBlockCount(1000)
        self._log_pane.setPlaceholderText("Log")
        self._log_pane.setFixedHeight(140)
        root.addWidget(self._log_pane)

        self.setStatusBar(QStatusBar())

    # --- Settings persistence ---------------------------------------------
    def _apply_settings_to_ui(self) -> None:
        self._spin_speed.setValue(self._settings.speed)
        self._spin_force.setValue(self._settings.force)
        self._chk_dry.setChecked(self._settings.dry_run)
        self._chk_lock.setChecked(self._settings.lock_ratio)
        baud = self._settings.baud
        idx = self._cmb_baud.findData(baud)
        if idx >= 0:
            self._cmb_baud.setCurrentIndex(idx)
        flow = self._settings.flow_control
        for action in self._flow_group.actions():
            if action.data() is flow:
                action.setChecked(True)
                break

    def _on_speed_changed(self, v: int) -> None:
        self._settings.speed = v
        self._refresh_estimate()

    def _on_force_changed(self, v: int) -> None:
        self._settings.force = v

    def _on_baud_changed(self, idx: int) -> None:
        data = self._cmb_baud.itemData(idx)
        if data is not None:
            self._settings.baud = int(data)

    def _on_dry_run_changed(self, v: bool) -> None:
        self._settings.dry_run = v
        self._update_cut_button_state()

    def _on_port_changed(self, _idx: int) -> None:
        self._settings.port = self._cmb_port.currentData() or ""
        self._update_cut_button_state()

    def _on_flow_control_changed(self) -> None:
        action = self._flow_group.checkedAction()
        if action is not None:
            mode = action.data()
            self._settings.flow_control = mode
            self._log(f"Serial flow control: {mode.value}")

    # --- Ports -------------------------------------------------------------
    def _load_ports(self) -> None:
        current = self._cmb_port.currentData() or self._settings.port
        self._cmb_port.blockSignals(True)
        self._cmb_port.clear()
        self._cmb_port.addItem("— vælg port —", "")
        ports = [p for p in serial.tools.list_ports.comports()
                 if p.device.startswith("/dev/cu.")]
        for p in ports:
            label = f"{p.device}  ({p.description})" if p.description else p.device
            self._cmb_port.addItem(label, p.device)
        # Restore previous selection if still present
        idx = self._cmb_port.findData(current)
        if idx >= 0:
            self._cmb_port.setCurrentIndex(idx)
        self._cmb_port.blockSignals(False)
        self._log(f"Porte: {len(ports)} fundet")
        self._update_cut_button_state()

    # --- File open / drag-drop --------------------------------------------
    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Åbn SVG", "", "SVG files (*.svg)")
        if path:
            self._load_svg(Path(path))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        md = event.mimeData()
        if md.hasUrls() and any(
            u.toLocalFile().lower().endswith(".svg") for u in md.urls()
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.lower().endswith(".svg"):
                self._load_svg(Path(local))
                break

    def _load_svg(self, path: Path) -> None:
        try:
            polylines, w_mm, h_mm = svg_to_polylines(path, target_width_mm=400.0)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "SVG error", f"Kunne ikke læse SVG:\n{e}")
            self._log(f"SVG-fejl: {e}")
            return
        self._svg_path = path
        # Initial display width: the SVG's natural width (if known) or 400 fallback
        # We scaled to 400mm above purely to get proportions; derive native width:
        # svg_to_polylines returns (polylines, width_mm, height_mm) where width_mm
        # is whatever we asked for. Reparse with width = SVG's own intended mm.
        from svgelements import SVG

        raw = SVG.parse(str(path), reify=True, ppi=96.0)
        # svg.width is in user units (pixels at 96 DPI). Convert to mm.
        natural_width_mm = float(raw.width) * 25.4 / 96.0
        natural_height_mm = float(raw.height) * 25.4 / 96.0

        self._src_width_mm = natural_width_mm
        self._src_height_mm = natural_height_mm

        self._file_label.setText(path.name)
        self._log(f"SVG indlæst: {path.name}  ({len(polylines)} polylinjer, "
                  f"{natural_width_mm:.1f}×{natural_height_mm:.1f} mm naturlig)")

        # Set spinboxes without triggering recursive updates
        self._spin_width.blockSignals(True)
        self._spin_height.blockSignals(True)
        self._spin_width.setValue(natural_width_mm)
        self._spin_height.setValue(natural_height_mm)
        self._spin_width.blockSignals(False)
        self._spin_height.blockSignals(False)

        self._preview.load_svg(str(path), natural_width_mm, natural_height_mm)
        self._refresh_estimate()
        self._update_cut_button_state()

    # --- Size editing ------------------------------------------------------
    def _on_width_changed(self, v: float) -> None:
        if self._src_width_mm <= 0:
            return
        if self._chk_lock.isChecked() and v > 0:
            new_h = v * (self._src_height_mm / self._src_width_mm)
            self._spin_height.blockSignals(True)
            self._spin_height.setValue(new_h)
            self._spin_height.blockSignals(False)
        self._preview.update_size_label(v, self._spin_height.value())
        self._refresh_estimate()

    def _on_height_changed(self, v: float) -> None:
        if self._src_height_mm <= 0:
            return
        if self._chk_lock.isChecked() and v > 0:
            new_w = v * (self._src_width_mm / self._src_height_mm)
            self._spin_width.blockSignals(True)
            self._spin_width.setValue(new_w)
            self._spin_width.blockSignals(False)
        self._preview.update_size_label(self._spin_width.value(), v)
        self._refresh_estimate()

    # --- Estimation --------------------------------------------------------
    def _refresh_estimate(self) -> None:
        if self._svg_path is None:
            self._lbl_est.setText("Est. time: —")
            return
        try:
            polylines, _, _ = svg_to_polylines(
                self._svg_path, target_width_mm=self._spin_width.value())
        except Exception:
            self._lbl_est.setText("Est. time: —")
            return
        length_mm = total_cut_length_mm(polylines)
        speed = max(1, self._spin_speed.value())
        secs = length_mm / (speed * 10.0)
        mins, ssec = divmod(int(secs), 60)
        self._lbl_est.setText(f"Est. time: {mins}m {ssec}s  ({length_mm:.0f} mm)")

    # --- CUT button state --------------------------------------------------
    def _update_cut_button_state(self) -> None:
        file_loaded = self._svg_path is not None
        dry = self._chk_dry.isChecked()
        port_selected = bool(self._cmb_port.currentData())
        enable = file_loaded and (dry or port_selected)
        self._btn_cut.setEnabled(enable)
        if not file_loaded:
            self._btn_cut.setToolTip("Indlæs en SVG først")
        elif not (dry or port_selected):
            self._btn_cut.setToolTip("Vælg en port eller slå Dry run til")
        else:
            self._btn_cut.setToolTip("")

    # --- CUT action --------------------------------------------------------
    def _on_cut_clicked(self) -> None:
        if self._svg_path is None:
            return
        width_mm = self._spin_width.value()
        speed = self._spin_speed.value()
        force = self._spin_force.value()
        try:
            polylines, w_mm, h_mm = svg_to_polylines(
                self._svg_path, target_width_mm=width_mm)
            hpgl = polylines_to_hpgl(polylines, height_mm=h_mm,
                                     speed_cm_s=speed, force_g=force)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Fejl", f"Kunne ikke generere HPGL:\n{e}")
            self._log(f"HPGL-fejl: {e}")
            return

        if self._chk_dry.isChecked():
            self._write_dry_run(hpgl)
            return

        port = self._cmb_port.currentData()
        if not port:
            return  # button should've been disabled
        baud = self._cmb_baud.currentData() or 9600
        flow = self._settings.flow_control
        self._start_cut_job(port, int(baud), flow, hpgl)

    def _write_dry_run(self, hpgl: str) -> None:
        desktop = Path.home() / "Desktop"
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        stem = self._svg_path.stem if self._svg_path else "redsailcut"
        out = desktop / f"{stem}_{stamp}.plt"
        try:
            out.write_text(hpgl, encoding="ascii")
        except OSError as e:
            QMessageBox.critical(self, "Filfejl", f"Kunne ikke skrive .plt:\n{e}")
            self._log(f"Filfejl: {e}")
            return
        self._log(f"Dry run: {out}")

    def _start_cut_job(self, port: str, baud: int, flow: FlowControl,
                       hpgl: str) -> None:
        self._cut_job = CutJob(port, baud, flow, hpgl)
        self._cut_job.progress.connect(self._on_progress)
        self._cut_job.log.connect(self._log)
        self._cut_job.error.connect(self._on_cut_error)
        self._cut_job.finished_ok.connect(self._on_cut_finished)
        self._cut_job.finished.connect(self._cut_job_finalised)
        self._btn_cut.setEnabled(False)
        self._btn_stop.setVisible(True)
        self._log(f"Start skæring → {port}")
        self._cut_job.start()

    def _on_stop_clicked(self) -> None:
        if self._cut_job is not None:
            self._cut_job.abort_flag.set()
            self._log("Stop anmodet — sender abort-sekvens…")

    def _on_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Sender HPGL: {done}/{total}")

    def _on_cut_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Serial/cut error", msg)
        self._log(f"FEJL: {msg}")

    def _on_cut_finished(self, success: bool) -> None:
        if success:
            self._log("Skæring færdig.")
        else:
            self._log("Skæring afbrudt.")

    def _cut_job_finalised(self) -> None:
        self._btn_stop.setVisible(False)
        self._cut_job = None
        self._update_cut_button_state()
        self.statusBar().clearMessage()

    # --- Log ---------------------------------------------------------------
    def _log(self, msg: str) -> None:
        self._log_pane.appendPlainText(f"{_now()}  {msg}")


def run_gui() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_gui())

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

from redsailcut.blade_offset import compensate_polylines
from redsailcut.cut_optimizer import options_for_import_cleanup
from redsailcut.hpgl import (
    HpglSafetyError,
    polylines_to_hpgl,
    validate_hpgl_safety,
)
from redsailcut.path_order import (
    sort_inside_first as sort_polylines_inside_first,
)
from redsailcut.preview import PreviewWidget
from redsailcut.rotate import rotate_polylines
from redsailcut.sharp_corners import add_pivots as add_sharp_corner_pivots
from redsailcut.serial_io import (
    FlowControl,
    SerialError,
    open_cutter,
    probe_cutter,
    send_hpgl,
)
from redsailcut.settings import AppSettings
from redsailcut.svg_parser import (
    Polyline,
    svg_to_polylines,
    svg_to_polylines_with_report,
    total_cut_length_mm,
    total_travel_length_mm,
)

WARN_WIDTH_MM = 400.0
WARN_TIME_MINUTES = 60.0
SAFETY_SEGMENT_MARGIN_MM = 25.0
PEN_UP_SPEED_FACTOR = 1.7  # pen-up travel is faster than cutting on the RS720C

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
        self.log.emit(f"Port opened: {self._port} @ {self._baud} baud")
        try:
            ok = send_hpgl(ser, self._hpgl, self.progress.emit, self.abort_flag)
        except Exception as e:  # noqa: BLE001  — surface any unexpected I/O error
            self.error.emit(f"Cutting error: {e}")
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
        self._log("Ready. Open an SVG to start.")

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
        tools_menu = settings_menu.addMenu("&Tools")
        act_probe = QAction("Test cutter connection…", self)
        act_probe.triggered.connect(self._probe_connection)
        tools_menu.addAction(act_probe)

        adv = settings_menu.addMenu("&Advanced")
        flow_menu = adv.addMenu("Serial flow control")
        self._flow_group = QActionGroup(self)
        self._flow_group.setExclusive(True)
        for mode, label in [
            (FlowControl.NONE, "None (default — works with Redsail RS720C)"),
            (FlowControl.RTS_CTS, "RTS/CTS"),
            (FlowControl.XON_XOFF, "XON/XOFF"),
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
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1, 1])

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
        self._cmb_rotation = QComboBox()
        for deg, label in [
            (0, "0°"),
            (90, "90° CW"),
            (180, "180°"),
            (270, "270° CW"),
        ]:
            self._cmb_rotation.addItem(label, deg)
        self._cmb_rotation.setToolTip(
            "Rotate the design in 90° steps. Use this to match the cutter's "
            "physical origin, usually bottom-right on the roll."
        )
        self._cmb_rotation.currentIndexChanged.connect(self._on_rotation_changed)
        sf.addRow("Width:", self._spin_width)
        sf.addRow("Height:", self._spin_height)
        sf.addRow(self._chk_lock)
        sf.addRow("Rotation:", self._cmb_rotation)
        self._cmb_cleanup = QComboBox()
        for mode, label in [
            ("strong", "Strong (recommended)"),
            ("normal", "Normal"),
            ("max", "Maximum"),
            ("smooth", "Smooth curves"),
            ("off", "Off"),
        ]:
            self._cmb_cleanup.addItem(label, mode)
        self._cmb_cleanup.setToolTip(
            "Cleans traced/noisy SVGs on import. Smooth curves can improve "
            "ornaments, but will also slightly round sharp corners."
        )
        self._cmb_cleanup.currentIndexChanged.connect(self._on_cleanup_changed)
        sf.addRow("Import cleanup:", self._cmb_cleanup)
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
        self._chk_sort = QCheckBox("Cut inside shapes first")
        self._chk_sort.setToolTip(
            "Cuts inner details before outer contours. Prevents loose vinyl "
            "pieces from shifting during cutting."
        )
        self._chk_sort.toggled.connect(self._on_sort_inside_first_changed)
        pf.addRow(self._chk_sort)
        c_layout.addWidget(params_box)

        # Blade compensation group (drag-knife offset)
        blade_box = QGroupBox("Blade compensation")
        bf = QFormLayout(blade_box)
        self._spin_offset = QDoubleSpinBox()
        self._spin_offset.setRange(0.0, 1.0)
        self._spin_offset.setSingleStep(0.05)
        self._spin_offset.setDecimals(2)
        self._spin_offset.setSuffix(" mm")
        self._spin_offset.setToolTip("0 = pen-mode (no compensation). "
                                     "Typical drag-knife offset: 0.20–0.30 mm.")
        self._spin_offset.valueChanged.connect(self._on_offset_changed)
        self._spin_overcut = QDoubleSpinBox()
        self._spin_overcut.setRange(0.0, 2.0)
        self._spin_overcut.setSingleStep(0.1)
        self._spin_overcut.setDecimals(1)
        self._spin_overcut.setSuffix(" mm")
        self._spin_overcut.setToolTip("Extends closed paths past the closing "
                                      "point so vinyl separates cleanly.")
        self._spin_overcut.valueChanged.connect(self._on_overcut_changed)
        self._spin_corner = QSpinBox()
        self._spin_corner.setRange(1, 45)
        self._spin_corner.setSingleStep(1)
        self._spin_corner.setSuffix(" °")
        self._spin_corner.setToolTip("Below this turn angle, compensation is "
                                     "skipped — keeps sampled curves from drifting.")
        self._spin_corner.valueChanged.connect(self._on_corner_threshold_changed)
        bf.addRow("Offset:", self._spin_offset)
        bf.addRow("Overcut:", self._spin_overcut)
        bf.addRow("Corner threshold:", self._spin_corner)
        self._chk_lift = QCheckBox("Lift knife at sharp corners")
        self._chk_lift.setToolTip(
            "Lifts the knife at very sharp design corners. Especially useful "
            "for script text and fine ornaments."
        )
        self._chk_lift.toggled.connect(self._on_lift_sharp_changed)
        self._spin_sharp = QSpinBox()
        self._spin_sharp.setRange(5, 60)
        self._spin_sharp.setSingleStep(1)
        self._spin_sharp.setSuffix(" °")
        self._spin_sharp.setToolTip(
            "Corners below this opening angle are lifted. Only active when "
            "offset > 0."
        )
        self._spin_sharp.valueChanged.connect(self._on_sharp_threshold_changed)
        bf.addRow(self._chk_lift)
        bf.addRow("Threshold:", self._spin_sharp)
        c_layout.addWidget(blade_box)

        # Dry run + est time
        self._chk_dry = QCheckBox("Dry run  —  save .plt to Desktop")
        self._chk_dry.toggled.connect(self._on_dry_run_changed)
        c_layout.addWidget(self._chk_dry)

        self._lbl_est = QLabel("Est. time: —")
        c_layout.addWidget(self._lbl_est)

        self._lbl_warn = QLabel("")
        self._lbl_warn.setWordWrap(True)
        self._lbl_warn.setStyleSheet(
            "color: #8a6d00; background: #fff8dd; border: 1px solid #e6d58a; "
            "padding: 4px; border-radius: 4px;"
        )
        self._lbl_warn.setVisible(False)
        c_layout.addWidget(self._lbl_warn)

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
        self._spin_offset.setValue(self._settings.blade_offset_mm)
        self._spin_overcut.setValue(self._settings.overcut_mm)
        self._spin_corner.setValue(self._settings.corner_threshold_deg)
        self._chk_sort.setChecked(self._settings.sort_inside_first)
        self._chk_lift.setChecked(self._settings.lift_sharp_corners)
        self._spin_sharp.setValue(self._settings.sharp_corner_threshold_deg)
        idx = self._cmb_rotation.findData(self._settings.rotation_deg)
        if idx >= 0:
            self._cmb_rotation.setCurrentIndex(idx)
        idx = self._cmb_cleanup.findData(self._settings.import_cleanup)
        if idx >= 0:
            self._cmb_cleanup.setCurrentIndex(idx)
        self._update_overcut_enabled()
        self._update_sharp_enabled()
        baud = self._settings.baud
        idx = self._cmb_baud.findData(baud)
        if idx >= 0:
            self._cmb_baud.setCurrentIndex(idx)
        flow = self._settings.flow_control
        for action in self._flow_group.actions():
            if action.data() is flow:
                action.setChecked(True)
                break

    def _update_overcut_enabled(self) -> None:
        # Overcut only meaningful when offset > 0
        self._spin_overcut.setEnabled(self._spin_offset.value() > 0)

    def _update_sharp_enabled(self) -> None:
        # Sharp-corner lift only effective with drag-knife (offset > 0);
        # threshold spinbox only editable when the feature is on.
        has_offset = self._spin_offset.value() > 0
        self._chk_lift.setEnabled(has_offset)
        self._spin_sharp.setEnabled(has_offset and self._chk_lift.isChecked())

    def _on_speed_changed(self, v: int) -> None:
        self._settings.speed = v
        self._refresh_estimate()

    def _on_force_changed(self, v: int) -> None:
        self._settings.force = v

    def _on_offset_changed(self, v: float) -> None:
        self._settings.blade_offset_mm = v
        self._update_overcut_enabled()
        self._update_sharp_enabled()
        self._refresh_estimate()

    def _on_overcut_changed(self, v: float) -> None:
        self._settings.overcut_mm = v
        self._refresh_estimate()

    def _on_corner_threshold_changed(self, v: int) -> None:
        self._settings.corner_threshold_deg = v
        self._refresh_estimate()

    def _on_sort_inside_first_changed(self, v: bool) -> None:
        self._settings.sort_inside_first = v
        self._refresh_estimate()

    def _on_rotation_changed(self, _idx: int) -> None:
        deg = self._cmb_rotation.currentData()
        if deg is None:
            return
        self._settings.rotation_deg = int(deg)
        self._reload_preview_with_current_size()
        self._refresh_estimate()

    def _on_cleanup_changed(self, _idx: int) -> None:
        mode = self._cmb_cleanup.currentData()
        if mode is None:
            return
        self._settings.import_cleanup = str(mode)
        self._reload_preview_with_current_size()
        self._refresh_estimate()

    def _optimizer_options(self):
        mode = self._cmb_cleanup.currentData() or self._settings.import_cleanup
        return options_for_import_cleanup(str(mode))

    def _cleanup_label(self) -> str:
        mode = self._cmb_cleanup.currentData() or self._settings.import_cleanup
        return {
            "off": "unoptimized",
            "normal": "normal cleanup",
            "strong": "strong cleanup",
            "max": "maximum cleanup",
            "smooth": "smoothed curves",
        }.get(str(mode), "strong cleanup")

    def _reload_preview_with_current_size(self) -> None:
        if self._svg_path is None:
            return
        try:
            polylines, w_mm, h_mm, _ = svg_to_polylines_with_report(
                self._svg_path,
                target_width_mm=self._spin_width.value(),
                optimizer_options=self._optimizer_options(),
            )
        except Exception:
            return
        rotation_deg = int(self._cmb_rotation.currentData() or 0)
        if rotation_deg:
            polylines, w_mm, h_mm = rotate_polylines(
                polylines, rotation_deg, w_mm, h_mm
            )
        label = self._cleanup_label() + (f"  ↻ {rotation_deg}°" if rotation_deg else "")
        self._preview.load_polylines(polylines, w_mm, h_mm, label_extra=label)

    def _on_lift_sharp_changed(self, v: bool) -> None:
        self._settings.lift_sharp_corners = v
        self._update_sharp_enabled()
        self._refresh_estimate()

    def _on_sharp_threshold_changed(self, v: int) -> None:
        self._settings.sharp_corner_threshold_deg = v
        self._refresh_estimate()

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

    # --- Diagnostic probe --------------------------------------------------
    def _probe_connection(self) -> None:
        port = self._cmb_port.currentData()
        if not port:
            QMessageBox.information(self, "Test connection", "Select a port first.")
            return
        baud = int(self._cmb_baud.currentData() or 9600)
        flow = self._settings.flow_control
        self._log(f"Probe: {port} @ {baud} baud, flow={flow.value}")
        try:
            report = probe_cutter(port, baud, flow=flow)
        except SerialError as e:
            QMessageBox.critical(self, "Probe error", str(e))
            self._log(f"Probe error: {e}")
            return
        self._log("Probe response:\n" + report)
        QMessageBox.information(
            self, "Probe result",
            f"Sent to {port}:\n{report}\n\n"
            "If every query shows '(no reply)', the cutter either is not "
            "receiving bytes (cable/flow-control) or does not support "
            "HP-GL/2 query commands.\n"
            "If at least one query has a response, communication works; the "
            "problem is command parsing or the cutter's mode.",
        )

    # --- Ports -------------------------------------------------------------
    def _load_ports(self) -> None:
        current = self._cmb_port.currentData() or self._settings.port
        self._cmb_port.blockSignals(True)
        self._cmb_port.clear()
        self._cmb_port.addItem("— select port —", "")
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
        self._log(f"Ports: {len(ports)} found")
        self._update_cut_button_state()

    # --- File open / drag-drop --------------------------------------------
    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SVG", "", "SVG files (*.svg)")
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
            from svgelements import SVG

            raw = SVG.parse(str(path), reify=True, ppi=96.0)
            # svg.width is in user units (pixels at 96 DPI). Convert to mm.
            natural_width_mm = float(raw.width) * 25.4 / 96.0
            natural_height_mm = float(raw.height) * 25.4 / 96.0
            polylines, w_mm, h_mm, report = svg_to_polylines_with_report(
                path,
                target_width_mm=natural_width_mm,
                optimizer_options=self._optimizer_options(),
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "SVG error", f"Could not read SVG:\n{e}")
            self._log(f"SVG error: {e}")
            return

        self._svg_path = path

        self._src_width_mm = natural_width_mm
        self._src_height_mm = natural_height_mm

        self._file_label.setText(path.name)
        self._log(f"SVG loaded: {path.name}  ({len(polylines)} optimized polylines, "
                  f"{natural_width_mm:.1f}×{natural_height_mm:.1f} mm natural)")
        if report is not None:
            self._log(
                "Import cleanup: "
                f"points {report.input_points}->{report.output_points}, "
                f"segments {report.input_segments}->{report.output_segments}, "
                f"small <1mm {report.input_small_segments}->{report.output_small_segments}"
            )

        # Set spinboxes without triggering recursive updates
        self._spin_width.blockSignals(True)
        self._spin_height.blockSignals(True)
        self._spin_width.setValue(natural_width_mm)
        self._spin_height.setValue(natural_height_mm)
        self._spin_width.blockSignals(False)
        self._spin_height.blockSignals(False)

        rot = int(self._cmb_rotation.currentData() or 0)
        if rot:
            polylines, w_mm, h_mm = rotate_polylines(polylines, rot, w_mm, h_mm)
        label = self._cleanup_label() + (f"  ↻ {rot}°" if rot else "")
        self._preview.load_polylines(polylines, w_mm, h_mm, label_extra=label)
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
        self._reload_preview_with_current_size()
        self._refresh_estimate()

    def _on_height_changed(self, v: float) -> None:
        if self._src_height_mm <= 0:
            return
        if self._chk_lock.isChecked() and v > 0:
            new_w = v * (self._src_width_mm / self._src_height_mm)
            self._spin_width.blockSignals(True)
            self._spin_width.setValue(new_w)
            self._spin_width.blockSignals(False)
        self._reload_preview_with_current_size()
        self._refresh_estimate()

    # --- Estimation --------------------------------------------------------
    def _refresh_estimate(self) -> None:
        if self._svg_path is None:
            self._lbl_est.setText("Est. time: —")
            self._lbl_warn.setVisible(False)
            return
        width_mm = self._spin_width.value()
        try:
            polylines, _, _ = svg_to_polylines(
                self._svg_path,
                target_width_mm=width_mm,
                optimizer_options=self._optimizer_options(),
            )
        except Exception:
            self._lbl_est.setText("Est. time: —")
            self._lbl_warn.setVisible(False)
            return
        # Run the same pipeline as the real cut so the estimate is faithful.
        rotation_deg = int(self._cmb_rotation.currentData() or 0)
        cut_width_mm = width_mm
        cut_height_mm = self._spin_height.value()
        if rotation_deg:
            polylines, cut_width_mm, cut_height_mm = rotate_polylines(
                polylines, rotation_deg, width_mm, self._spin_height.value()
            )
        if self._chk_sort.isChecked():
            polylines = sort_polylines_inside_first(polylines)
        if (self._chk_lift.isChecked() and self._spin_offset.value() > 0):
            polylines = add_sharp_corner_pivots(
                polylines, threshold_deg=self._spin_sharp.value()
            )
        polylines = compensate_polylines(
            polylines,
            offset_mm=self._spin_offset.value(),
            overcut_mm=self._spin_overcut.value(),
            corner_threshold_deg=self._spin_corner.value(),
        )
        cut_mm = total_cut_length_mm(polylines)
        travel_mm = total_travel_length_mm(polylines)
        speed = max(1, self._spin_speed.value())
        cut_secs = cut_mm / (speed * 10.0)
        travel_secs = travel_mm / (speed * 10.0 * PEN_UP_SPEED_FACTOR)
        total_secs = cut_secs + travel_secs
        mins, ssec = divmod(int(total_secs), 60)
        self._lbl_est.setText(
            f"Est. time: {mins}m {ssec}s  (cut {cut_mm:.0f} mm + travel {travel_mm:.0f} mm)"
        )
        self._update_warning_banner(cut_width_mm, cut_height_mm, total_secs)

    def _update_warning_banner(
        self, width_mm: float, height_mm: float, total_secs: float
    ) -> None:
        warnings: list[str] = []
        if width_mm > WARN_WIDTH_MM:
            warnings.append(
                f"Design is {width_mm:.0f} mm wide. The app allows it, but "
                "runs HPGL preflight before sending to catch stray cut lines."
            )
        if total_secs > WARN_TIME_MINUTES * 60:
            mins = int(total_secs / 60)
            warnings.append(
                f"Estimated cut time is {mins} min — consider splitting the design."
            )
        if warnings:
            self._lbl_warn.setText("⚠  " + "  ".join(warnings))
            self._lbl_warn.setVisible(True)
        else:
            self._lbl_warn.setVisible(False)

    # --- CUT button state --------------------------------------------------
    def _update_cut_button_state(self) -> None:
        file_loaded = self._svg_path is not None
        dry = self._chk_dry.isChecked()
        port_selected = bool(self._cmb_port.currentData())
        enable = file_loaded and (dry or port_selected)
        self._btn_cut.setEnabled(enable)
        if not file_loaded:
            self._btn_cut.setToolTip("Load an SVG first")
        elif not (dry or port_selected):
            self._btn_cut.setToolTip("Select a port or enable Dry run")
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
                self._svg_path,
                target_width_mm=width_mm,
                optimizer_options=self._optimizer_options(),
            )
            rotation_deg = int(self._cmb_rotation.currentData() or 0)
            if rotation_deg:
                polylines, w_mm, h_mm = rotate_polylines(
                    polylines, rotation_deg, w_mm, h_mm
                )
            if self._chk_sort.isChecked():
                polylines = sort_polylines_inside_first(polylines)
            if (self._chk_lift.isChecked() and self._spin_offset.value() > 0):
                polylines = add_sharp_corner_pivots(
                    polylines, threshold_deg=self._spin_sharp.value()
                )
            polylines = compensate_polylines(
                polylines,
                offset_mm=self._spin_offset.value(),
                overcut_mm=self._spin_overcut.value(),
                corner_threshold_deg=self._spin_corner.value(),
            )
            hpgl = polylines_to_hpgl(polylines, height_mm=h_mm,
                                     speed_cm_s=speed, force_g=force)
            max_cut_segment_mm = max(w_mm, h_mm) + SAFETY_SEGMENT_MARGIN_MM
            safety = validate_hpgl_safety(
                hpgl, max_cut_segment_mm=max_cut_segment_mm
            )
        except HpglSafetyError as e:
            QMessageBox.critical(self, "HPGL safety stop", str(e))
            self._log(f"HPGL safety stop: {e}")
            return
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"Could not generate HPGL:\n{e}")
            self._log(f"HPGL error: {e}")
            return
        if self._spin_offset.value() > 0:
            self._log(
                f"Blade compensation: offset={self._spin_offset.value():.2f}mm, "
                f"overcut={self._spin_overcut.value():.1f}mm, "
                f"corner={self._spin_corner.value()}°"
            )
        self._log(
            "HPGL preflight OK: "
            f"max cut {safety.max_cut_segment_mm:.1f} mm, "
            f"max travel {safety.max_travel_segment_mm:.1f} mm, "
            f"max coord {safety.max_coordinate_mm:.1f} mm"
        )

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
            QMessageBox.critical(self, "File error", f"Could not write .plt:\n{e}")
            self._log(f"File error: {e}")
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
        self._log(f"Start cutting → {port}")
        self._cut_job.start()

    def _on_stop_clicked(self) -> None:
        if self._cut_job is not None:
            self._cut_job.abort_flag.set()
            self._log("Stop requested — sending abort sequence…")

    def _on_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"Sending HPGL: {done}/{total}")

    def _on_cut_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Serial/cut error", msg)
        self._log(f"ERROR: {msg}")

    def _on_cut_finished(self, success: bool) -> None:
        if success:
            self._log("Cut complete.")
        else:
            self._log("Cut aborted.")

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

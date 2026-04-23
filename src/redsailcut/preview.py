"""SVG preview widget using QGraphicsView + QGraphicsSvgItem.

We render the SVG in its native coordinate system and fit to view on every
resize. A bounding-box overlay with millimetre labels is drawn on top.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)


class PreviewWidget(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor(245, 245, 245)))
        self._svg_item: QGraphicsSvgItem | None = None
        self._bbox_item: QGraphicsRectItem | None = None
        self._label_item: QGraphicsSimpleTextItem | None = None
        self._width_mm = 0.0
        self._height_mm = 0.0

    def clear(self) -> None:
        self._scene.clear()
        self._svg_item = None
        self._bbox_item = None
        self._label_item = None

    def load_svg(self, path: str, width_mm: float, height_mm: float) -> None:
        self.clear()
        self._width_mm = width_mm
        self._height_mm = height_mm
        self._svg_item = QGraphicsSvgItem(path)
        self._svg_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsToShape, False)
        self._scene.addItem(self._svg_item)

        bounds = self._svg_item.boundingRect()
        pen = QPen(QColor(30, 100, 200), 0)
        pen.setCosmetic(True)
        self._bbox_item = self._scene.addRect(bounds, pen, QBrush(Qt.BrushStyle.NoBrush))

        self._label_item = self._scene.addSimpleText(
            f"{width_mm:.1f} × {height_mm:.1f} mm"
        )
        self._label_item.setBrush(QBrush(QColor(30, 100, 200)))
        self._label_item.setPos(bounds.left(), bounds.bottom() + bounds.height() * 0.02)

        padded = QRectF(bounds.adjusted(
            -bounds.width() * 0.05,
            -bounds.height() * 0.05,
            bounds.width() * 0.05,
            bounds.height() * 0.15,  # extra room for the label
        ))
        self._scene.setSceneRect(padded)
        self._fit()

    def update_size_label(self, width_mm: float, height_mm: float) -> None:
        self._width_mm = width_mm
        self._height_mm = height_mm
        if self._label_item is not None:
            self._label_item.setText(f"{width_mm:.1f} × {height_mm:.1f} mm")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._svg_item is None:
            return
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

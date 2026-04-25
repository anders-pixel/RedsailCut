"""SVG preview widget using QGraphicsView + QGraphicsSvgItem.

We render the SVG in its native coordinate system and fit to view on every
resize. A bounding-box overlay with millimetre labels is drawn on top.
The widget can also rotate the visible SVG in 90° increments to mirror
what the user has selected for the cut pipeline.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
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
        self._path_item: QGraphicsPathItem | None = None
        self._bbox_item: QGraphicsRectItem | None = None
        self._label_item: QGraphicsSimpleTextItem | None = None
        self._width_mm = 0.0
        self._height_mm = 0.0
        self._rotation_deg = 0
        self._label_extra = ""

    def clear(self) -> None:
        self._scene.clear()
        self._svg_item = None
        self._path_item = None
        self._bbox_item = None
        self._label_item = None

    def load_svg(
        self,
        path: str,
        width_mm: float,
        height_mm: float,
        rotation_deg: int = 0,
    ) -> None:
        self.clear()
        self._width_mm = width_mm
        self._height_mm = height_mm
        self._rotation_deg = rotation_deg
        self._label_extra = f"  ↻ {rotation_deg}°" if rotation_deg else ""
        self._svg_item = QGraphicsSvgItem(path)
        self._svg_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsToShape, False)

        # Rotate the SVG content around its own centre so the visible motif
        # matches what the cut pipeline will produce after rotation.
        if rotation_deg:
            local_bounds = self._svg_item.boundingRect()
            self._svg_item.setTransformOriginPoint(local_bounds.center())
            self._svg_item.setRotation(rotation_deg)

        self._scene.addItem(self._svg_item)

        # bbox + label use scene coords (after rotation has been applied to the
        # item) so the overlay aligns with the rotated content.
        bounds = self._svg_item.sceneBoundingRect()
        pen = QPen(QColor(30, 100, 200), 0)
        pen.setCosmetic(True)
        self._bbox_item = self._scene.addRect(bounds, pen, QBrush(Qt.BrushStyle.NoBrush))

        self._label_item = self._scene.addSimpleText(
            f"{width_mm:.1f} × {height_mm:.1f} mm{self._label_extra}"
        )
        self._label_item.setBrush(QBrush(QColor(30, 100, 200)))
        self._label_item.setPos(bounds.left(), bounds.bottom() + bounds.height() * 0.02)

        padded = QRectF(bounds.adjusted(
            -bounds.width() * 0.05,
            -bounds.height() * 0.05,
            bounds.width() * 0.05,
            bounds.height() * 0.15,
        ))
        self._scene.setSceneRect(padded)
        self._fit()

    def load_polylines(
        self,
        polylines: list[list[tuple[float, float]]],
        width_mm: float,
        height_mm: float,
        label_extra: str = "",
    ) -> None:
        """Preview the exact optimized geometry that will be sent to HPGL."""
        self.clear()
        self._width_mm = width_mm
        self._height_mm = height_mm
        self._rotation_deg = 0
        self._label_extra = f"  {label_extra}" if label_extra else ""

        path = QPainterPath()
        for polyline in polylines:
            if len(polyline) < 2:
                continue
            x0, y0 = polyline[0]
            path.moveTo(x0, y0)
            for x, y in polyline[1:]:
                path.lineTo(x, y)

        pen = QPen(QColor(20, 20, 20), 0)
        pen.setCosmetic(True)
        self._path_item = self._scene.addPath(path, pen, QBrush(Qt.BrushStyle.NoBrush))

        bounds = QRectF(0, 0, width_mm, height_mm)
        bbox_pen = QPen(QColor(30, 100, 200), 0)
        bbox_pen.setCosmetic(True)
        self._bbox_item = self._scene.addRect(
            bounds, bbox_pen, QBrush(Qt.BrushStyle.NoBrush)
        )

        self._label_item = self._scene.addSimpleText(
            f"{width_mm:.1f} × {height_mm:.1f} mm{self._label_extra}"
        )
        self._label_item.setBrush(QBrush(QColor(30, 100, 200)))
        self._label_item.setPos(bounds.left(), bounds.bottom() + height_mm * 0.02)

        padded = QRectF(bounds.adjusted(
            -width_mm * 0.05,
            -height_mm * 0.05,
            width_mm * 0.05,
            height_mm * 0.15,
        ))
        self._scene.setSceneRect(padded)
        self._fit()

    def update_size_label(self, width_mm: float, height_mm: float) -> None:
        self._width_mm = width_mm
        self._height_mm = height_mm
        if self._label_item is not None:
            self._label_item.setText(
                f"{width_mm:.1f} × {height_mm:.1f} mm{self._label_extra}"
            )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._svg_item is None and self._path_item is None:
            return
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

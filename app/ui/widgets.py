from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

_MIN_DRAG_FRACTION = 0.02
_MARKER_SIZE = 14


def box_to_insets(box: dict) -> dict:
    """Fraction-space {x0,y0,x1,y1} -> the top/right/bottom/left inset shape
    crop_pdf/redact_pdf expect (matching CropSelector.jsx/RedactSelector.jsx's
    own conversion on mouse-up)."""
    return {"top": box["y0"], "left": box["x0"], "right": 1 - box["x1"], "bottom": 1 - box["y1"]}


def insets_to_box(insets: dict) -> dict:
    """Inverse of box_to_insets — used when restoring a previously-drawn box
    (e.g. switching back to an already-annotated page in RedactDialog)."""
    return {"x0": insets["left"], "y0": insets["top"], "x1": 1 - insets["right"], "y1": 1 - insets["bottom"]}


class RectangleOverlayWidget(QWidget):
    """Displays a page-preview QPixmap with drag-to-draw rectangle(s) on top,
    in page-fraction (0-1) coordinates - mirrors CropSelector.jsx's (multi=False)
    or RedactSelector.jsx's (multi=True) exact interaction model.

    multi=False: at most one box, replaced outright by each new drag.
    multi=True: any number of boxes; each gets a small removable marker at its
    top-right corner - clicking one removes that box instead of starting a drag.
    """

    def __init__(self, multi: bool = False, parent=None):
        super().__init__(parent)
        self.multi = multi
        self.pixmap = None
        self.boxes: list[dict] = []
        self._drag_start: tuple[float, float] | None = None
        self._drag_current: tuple[float, float] | None = None

    def set_pixmap(self, pixmap) -> None:
        self.pixmap = pixmap
        self.setFixedSize(pixmap.size())
        self.update()

    def set_boxes(self, boxes: list[dict]) -> None:
        self.boxes = list(boxes)
        self.update()

    def single_box(self) -> dict | None:
        return self.boxes[0] if self.boxes else None

    def _point_from_pos(self, pos) -> tuple[float, float] | None:
        if self.width() == 0 or self.height() == 0:
            return None
        x = min(max(pos.x() / self.width(), 0), 1)
        y = min(max(pos.y() / self.height(), 0), 1)
        return (x, y)

    def _marker_rect(self, box: dict) -> QRect:
        x1_px = box["x1"] * self.width()
        y0_px = box["y0"] * self.height()
        return QRect(int(x1_px - _MARKER_SIZE), int(y0_px), _MARKER_SIZE, _MARKER_SIZE)

    def mousePressEvent(self, e) -> None:
        pos = e.position().toPoint()
        if self.multi:
            for i, box in enumerate(self.boxes):
                if self._marker_rect(box).contains(pos):
                    del self.boxes[i]
                    self.update()
                    return
        point = self._point_from_pos(pos)
        if point is None:
            return
        self._drag_start = point
        self._drag_current = point
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_start is None:
            return
        point = self._point_from_pos(e.position().toPoint())
        if point is None:
            return
        self._drag_current = point
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._drag_start is None:
            return
        point = self._point_from_pos(e.position().toPoint()) or self._drag_current
        x0, x1 = sorted((self._drag_start[0], point[0]))
        y0, y1 = sorted((self._drag_start[1], point[1]))
        self._drag_start = None
        self._drag_current = None
        if x1 - x0 < _MIN_DRAG_FRACTION or y1 - y0 < _MIN_DRAG_FRACTION:
            self.update()
            return
        box = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        if self.multi:
            self.boxes.append(box)
        else:
            self.boxes = [box]
        self.update()

    def _paint_box(self, painter: QPainter, box: dict, draw_marker: bool) -> None:
        x0_px, y0_px = box["x0"] * self.width(), box["y0"] * self.height()
        x1_px, y1_px = box["x1"] * self.width(), box["y1"] * self.height()
        rect = QRect(int(x0_px), int(y0_px), int(x1_px - x0_px), int(y1_px - y0_px))
        painter.setPen(QPen(QColor(220, 40, 40), 2))
        painter.setBrush(QColor(220, 40, 40, 60))
        painter.drawRect(rect)
        if draw_marker:
            marker = self._marker_rect(box)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(220, 40, 40))
            painter.drawEllipse(marker)
            inset = QPoint(3, 3)
            painter.drawLine(marker.topLeft() + inset, marker.bottomRight() - inset)
            painter.drawLine(marker.topRight() + QPoint(-3, 3), marker.bottomLeft() + QPoint(3, -3))

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.pixmap is not None:
            painter.drawPixmap(0, 0, self.pixmap)
        for box in self.boxes:
            self._paint_box(painter, box, draw_marker=self.multi)
        if self._drag_start is not None and self._drag_current is not None:
            x0, x1 = sorted((self._drag_start[0], self._drag_current[0]))
            y0, y1 = sorted((self._drag_start[1], self._drag_current[1]))
            self._paint_box(painter, {"x0": x0, "y0": y0, "x1": x1, "y1": y1}, draw_marker=False)

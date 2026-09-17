from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
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


class SignaturePadWidget(QWidget):
    """A small freehand-drawing canvas for a hand-drawn signature - paints
    directly onto an internal QImage buffer as the mouse drags, matching
    SignCanvas.jsx's own drawing pad (PAD_WIDTH=400, PAD_HEIGHT=150)."""

    def __init__(self, width: int = 400, height: int = 150, parent=None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._image = QImage(width, height, QImage.Format_RGB32)
        self._image.fill(Qt.white)
        self._has_drawing = False
        self._last_point: QPoint | None = None

    def has_drawing(self) -> bool:
        return self._has_drawing

    def clear(self) -> None:
        self._image.fill(Qt.white)
        self._has_drawing = False
        self.update()

    def save_png(self, path: str) -> None:
        self._image.save(path, "PNG")

    def mousePressEvent(self, e) -> None:
        self._last_point = e.position().toPoint()
        self._has_drawing = True

    def mouseMoveEvent(self, e) -> None:
        if self._last_point is None:
            return
        pos = e.position().toPoint()
        painter = QPainter(self._image)
        painter.setPen(QPen(Qt.black, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(self._last_point, pos)
        painter.end()
        self._last_point = pos
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        self._last_point = None

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        painter.drawImage(0, 0, self._image)


_HANDLE_SIZE = 14
_DEFAULT_WIDTH_FRACTION = 0.25
_MAX_HEIGHT_FRACTION = 0.9
_MIN_PLACEMENT_WIDTH_FRACTION = 0.05


class ImagePlacementWidget(QWidget):
    """Displays a page-preview QPixmap with a signature image placed at
    zero or more independent positions - mirrors SignCanvas.jsx's own
    click-to-place / drag-to-move / drag-handle-to-resize / click-to-remove
    model. A click is tested against, in this order: an existing
    placement's removable marker (top-right corner), its resize handle
    (bottom-right corner), its body (starts a move), and - only if none of
    those hit - empty space, which creates a new placement centered on the
    click point."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.page_pixmap = None
        self.signature_pixmap = None
        self.placements: list[dict] = []
        self._drag: dict | None = None

    def set_page_pixmap(self, pixmap) -> None:
        self.page_pixmap = pixmap
        self.setFixedSize(pixmap.size())
        self.update()

    def set_signature_pixmap(self, pixmap) -> None:
        self.signature_pixmap = pixmap
        self.update()

    def set_placements(self, placements: list[dict]) -> None:
        self.placements = list(placements)
        self.update()

    def _point_from_pos(self, pos) -> tuple[float, float] | None:
        if self.width() == 0 or self.height() == 0:
            return None
        x = min(max(pos.x() / self.width(), 0), 1)
        y = min(max(pos.y() / self.height(), 0), 1)
        return (x, y)

    def _placement_rect_px(self, p: dict) -> QRect:
        x0 = p["x"] * self.width()
        y0 = p["y"] * self.height()
        x1 = (p["x"] + p["width"]) * self.width()
        y1 = (p["y"] + p["height"]) * self.height()
        return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def _corner_size(self, rect: QRect) -> int:
        # QRect's bottom()/right() are inclusive (bottom() == top() +
        # height() - 1), so a marker anchored at the top and a handle
        # anchored at the bottom, each sized height()//2, would share one
        # row right where they meet - confirmed empirically. Halving
        # (height() - 1) instead keeps them strictly apart.
        return max(6, min(_MARKER_SIZE, (rect.height() - 1) // 2, (rect.width() - 1) // 2))

    def _marker_rect(self, p: dict) -> QRect:
        rect = self._placement_rect_px(p)
        size = self._corner_size(rect)
        return QRect(rect.right() - size, rect.top(), size, size)

    def _handle_rect(self, p: dict) -> QRect:
        rect = self._placement_rect_px(p)
        size = self._corner_size(rect)
        return QRect(rect.right() - size, rect.bottom() - size, size, size)

    def mousePressEvent(self, e) -> None:
        pos = e.position().toPoint()
        # Hit-test topmost-first (reverse of self.placements order) so this
        # matches paint order in paintEvent, where later entries paint on
        # top - a click on an overlap should hit what's visually on top.
        for i in reversed(range(len(self.placements))):
            p = self.placements[i]
            if self._marker_rect(p).contains(pos):
                del self.placements[i]
                self.update()
                return
        for i in reversed(range(len(self.placements))):
            p = self.placements[i]
            if self._handle_rect(p).contains(pos):
                point = self._point_from_pos(pos)
                self._drag = {"mode": "resize", "index": i, "start": point, "start_placement": dict(p)}
                return
        for i in reversed(range(len(self.placements))):
            p = self.placements[i]
            if self._placement_rect_px(p).contains(pos):
                point = self._point_from_pos(pos)
                self._drag = {"mode": "move", "index": i, "start": point, "start_placement": dict(p)}
                return
        point = self._point_from_pos(pos)
        if point is None or self.signature_pixmap is None:
            return
        sig_w, sig_h = self.signature_pixmap.width(), self.signature_pixmap.height()
        width = _DEFAULT_WIDTH_FRACTION
        height = min(_MAX_HEIGHT_FRACTION, width * (sig_h / sig_w))
        x = min(max(point[0] - width / 2, 0), 1 - width)
        y = min(max(point[1] - height / 2, 0), 1 - height)
        self.placements.append({"x": x, "y": y, "width": width, "height": height})
        self.update()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        point = self._point_from_pos(e.position().toPoint())
        if point is None:
            return
        dx = point[0] - self._drag["start"][0]
        dy = point[1] - self._drag["start"][1]
        sp = self._drag["start_placement"]
        i = self._drag["index"]
        if self._drag["mode"] == "move":
            x = min(max(sp["x"] + dx, 0), 1 - sp["width"])
            y = min(max(sp["y"] + dy, 0), 1 - sp["height"])
            self.placements[i] = {**sp, "x": x, "y": y}
        else:
            aspect = sp["height"] / sp["width"]
            width_cap = min(1 - sp["x"], (1 - sp["y"]) / aspect)
            desired_width = max(_MIN_PLACEMENT_WIDTH_FRACTION, sp["width"] + dx)
            width = min(desired_width, width_cap)
            height = width * aspect
            self.placements[i] = {**sp, "width": width, "height": height}
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.page_pixmap is not None:
            painter.drawPixmap(0, 0, self.page_pixmap)
        for p in self.placements:
            rect = self._placement_rect_px(p)
            if self.signature_pixmap is not None:
                painter.drawPixmap(rect, self.signature_pixmap)
            marker = self._marker_rect(p)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(220, 40, 40))
            painter.drawEllipse(marker)
            inset = QPoint(3, 3)
            painter.drawLine(marker.topLeft() + inset, marker.bottomRight() - inset)
            painter.drawLine(marker.topRight() + QPoint(-3, 3), marker.bottomLeft() + QPoint(3, -3))
            handle = self._handle_rect(p)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(40, 100, 220))
            painter.drawRect(handle)

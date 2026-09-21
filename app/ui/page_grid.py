"""A grid of large page thumbnails - the desktop's counterpart of the web app's
PageGrid: look at the pages, click pages to mark them, or drag them into a new order.

Modes: "view" (just look), "select" (click a page to mark it; marked pages get a
badge and a tint in `select_color`), "reorder" (drag a page to a new place).
Pages can be shown in several sections (Merge: one per file; Split: one per output
file), each with a title. Live previews are painted on the thumbnails by an
`overlay` callback and/or a rotation angle.

Thumbnails are drawn on one background thread and only for pages near the view.
"""
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.core.errors import PDFError
from app.core.pdf_ops import get_page_sizes, render_page_thumbnail
from app.ui.page_zoom import PageZoomMixin, _RenderJob, _RenderSignals
from app.ui.theme import ACCENT, MUTED_FOREGROUND, icon

CELL_WIDTHS = (130, 170, 220, 290, 380)
DEFAULT_CELL_INDEX = 2
GAP = 16
LABEL_HEIGHT = 24
TITLE_HEIGHT = 34
_KEY_STRIDE = 1_000_000  # a cell's render key is section * stride + page number


def _key(section: int, page: int) -> int:
    return section * _KEY_STRIDE + page


class PageCell(QWidget):
    def __init__(self, grid: "PageGridWidget", section: int, page: int, aspect: float):
        super().__init__(grid._canvas)
        self.grid = grid
        self.section = section
        self.page = page
        self.aspect = aspect  # height / width of the page as shown
        self.pixmap: QPixmap | None = None
        self.rendered_width = 0
        self.requested_width = 0
        self._hover = False
        self._press_pos: QPoint | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    @property
    def key(self) -> int:
        return _key(self.section, self.page)

    def box_height(self) -> int:
        return self.height() - LABEL_HEIGHT

    def has_pixmap(self) -> bool:
        return self.pixmap is not None and not self.pixmap.isNull()

    def release_pixmap(self) -> None:
        self.pixmap = None
        self.rendered_width = 0
        self.requested_width = 0
        self.update()

    # ---- painting ----

    def _page_rect(self) -> QRectF:
        """Where the (possibly rotated) page sits inside the card."""
        box = QRectF(6, 6, self.width() - 12, self.box_height() - 12)
        aspect = self.aspect
        if self.grid.rotation % 180 == 90:
            aspect = 1 / aspect
        width = min(box.width(), box.height() / aspect)
        height = width * aspect
        return QRectF(box.center().x() - width / 2, box.center().y() - height / 2, width, height)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        card = QRectF(1, 1, self.width() - 2, self.box_height() - 2)
        p.setPen(QPen(QColor("#e2e8f0"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(card, 6, 6)
        target = self._page_rect()
        angle = self.grid.rotation
        if self.has_pixmap():
            if angle:
                p.save()
                p.translate(target.center())
                p.rotate(angle)
                w, h = (target.height(), target.width()) if angle % 180 == 90 else (target.width(), target.height())
                p.drawPixmap(QRectF(-w / 2, -h / 2, w, h).toRect(), self.pixmap)
                p.restore()
            else:
                p.drawPixmap(target.toRect(), self.pixmap)
        else:
            p.fillRect(target, QColor("#f1f5f9"))
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(target)
        overlay = self.grid.overlay
        if overlay is not None:
            p.save()
            p.setClipRect(target)
            overlay(p, target, self.page, self.grid.total_pages(self.section))
            p.restore()
        selected = self.grid.mode == "select" and self.grid.is_selected(self.key)
        if selected:
            color = QColor(self.grid.select_color)
            tint = QColor(color)
            tint.setAlpha(70)
            p.fillRect(target, tint)
            p.setPen(QPen(color, 3))
            p.drawRect(target.adjusted(-1, -1, 1, 1))
            badge = QRectF(target.right() - 30, target.top() + 6, 24, 24)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(badge)
            p.setPen(QPen(QColor("#ffffff"), 2.4))
            if self.grid.select_badge == "x":
                c = badge.center()
                p.drawLine(QPointF(c.x() - 5, c.y() - 5), QPointF(c.x() + 5, c.y() + 5))
                p.drawLine(QPointF(c.x() + 5, c.y() - 5), QPointF(c.x() - 5, c.y() + 5))
            else:
                c = badge.center()
                p.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() - 2, c.y() + 5))
                p.drawLine(QPointF(c.x() - 2, c.y() + 5), QPointF(c.x() + 6, c.y() - 5))
        elif self._hover and self.grid.mode != "view":
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(target.adjusted(-1, -1, 1, 1))
        p.setPen(QColor(MUTED_FOREGROUND))
        font = QFont(p.font())
        font.setPixelSize(13)
        p.setFont(font)
        p.drawText(QRect(0, self.box_height(), self.width(), LABEL_HEIGHT), Qt.AlignCenter, f"Page {self.page}")

    # ---- interaction ----

    def enterEvent(self, e) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, e) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._press_pos = e.position().toPoint()

    def mouseMoveEvent(self, e) -> None:
        if self.grid.mode == "reorder" and self._press_pos is not None and e.buttons() & Qt.LeftButton:
            if (e.position().toPoint() - self._press_pos).manhattanLength() > 10:
                self._press_pos = None
                self.grid._start_drag(self)

    def mouseReleaseEvent(self, e) -> None:
        pressed, self._press_pos = self._press_pos, None
        if e.button() == Qt.LeftButton and pressed is not None and self.grid.mode == "select":
            self.grid.toggle(self.key)


class _Canvas(QWidget):
    """The surface the cells sit on; it is also where a dragged page is dropped."""

    def __init__(self, grid: "PageGridWidget"):
        super().__init__()
        self.grid = grid
        self.setObjectName("pageCanvas")
        self.setAcceptDrops(True)
        self.drop_line: QRect | None = None

    def paintEvent(self, e) -> None:
        super().paintEvent(e)
        if self.drop_line is not None:
            p = QPainter(self)
            p.fillRect(self.drop_line, QColor(ACCENT))

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat("application/x-pdf-page"):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        index = self.grid._drop_index(e.position().toPoint())
        self.drop_line = self.grid._drop_line_rect(index)
        self.update()
        e.acceptProposedAction()

    def dragLeaveEvent(self, e) -> None:
        self.drop_line = None
        self.update()

    def dropEvent(self, e) -> None:
        index = self.grid._drop_index(e.position().toPoint())
        self.drop_line = None
        self.update()
        page = int(bytes(e.mimeData().data("application/x-pdf-page")).decode())
        self.grid._move_page(page, index)
        e.acceptProposedAction()


class PageGridWidget(QWidget):
    selection_changed = Signal()
    order_changed = Signal()

    def __init__(self, mode: str = "view", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.select_color = "#dc2626"
        self.select_badge = "x"  # "x" (marked for removal) or "check"
        self.rotation = 0
        self.overlay = None  # callable(painter, rect, page_number, total_pages) or None
        self._sections: list[dict] = []
        self._cells: list[PageCell] = []
        self._titles: list[QLabel] = []
        self._selected: set[int] = set()
        self._order: list[int] = []  # reorder mode: the pages of section 0 in their current order
        self._cell_index = DEFAULT_CELL_INDEX
        self._layout_rows: list[tuple[int, int]] = []  # (section, columns) per section, for the drop indicator

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        bar = QHBoxLayout()
        self._hint = QLabel("")
        self._hint.setObjectName("gridHint")
        bar.addWidget(self._hint, 1)
        self.zoom_out_btn = self._size_button("magnifying-glass-minus", "Smaller pages", -1)
        self.zoom_in_btn = self._size_button("magnifying-glass-plus", "Larger pages", 1)
        bar.addWidget(self.zoom_out_btn)
        bar.addWidget(self.zoom_in_btn)
        outer.addLayout(bar)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("pageScroll")
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._canvas = _Canvas(self)
        self._scroll.setWidget(self._canvas)
        outer.addWidget(self._scroll, 1)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._signals = _RenderSignals(self)
        self._signals.done.connect(self._on_rendered)
        self._token = 0
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(60)
        self._render_timer.timeout.connect(self._render_visible)
        self._scroll.verticalScrollBar().valueChanged.connect(lambda _v: self._render_timer.start())
        self._scroll.viewport().installEventFilter(self)
        self._sync_size_buttons()

    def _size_button(self, icon_name: str, tip: str, step: int) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("toolbarIcon")
        btn.setIcon(icon(icon_name, MUTED_FOREGROUND, 18))
        btn.setToolTip(tip)
        btn.setAccessibleName(tip)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.clicked.connect(lambda _=False: self.set_cell_index(self._cell_index + step))
        return btn

    # ---- content ----

    def set_hint(self, text: str) -> None:
        self._hint.setText(text)

    def clear(self) -> None:
        self._invalidate()
        for cell in self._cells:
            cell.setParent(None)
            cell.deleteLater()
        for title in self._titles:
            if title is not None:
                title.setParent(None)
                title.deleteLater()
        self._cells, self._titles, self._sections = [], [], []
        self._selected.clear()
        self._order = []
        self._canvas.resize(0, 0)

    def set_document(self, path: str | None) -> None:
        """One section holding every page of `path`."""
        self.set_sections([] if path is None else [{"title": None, "path": path, "pages": None}])

    def set_sections(self, sections: list[dict]) -> None:
        """Each section: {"title": str | None, "path": str, "pages": [page numbers] | None (all)}."""
        self.clear()
        for index, section in enumerate(sections):
            try:
                sizes = get_page_sizes(section["path"])
            except PDFError:
                sizes = []
            pages = section.get("pages") or list(range(1, len(sizes) + 1))
            info = {"title": section.get("title"), "path": section["path"], "pages": pages, "sizes": sizes, "total": len(sizes)}
            self._sections.append(info)
            if info["title"]:
                label = QLabel(info["title"], self._canvas)
                label.setObjectName("gridSectionTitle")
                label.show()
                self._titles.append(label)
            else:
                self._titles.append(None)
            for page in pages:
                width_pt, height_pt = sizes[page - 1] if 0 < page <= len(sizes) else (595.0, 842.0)
                cell = PageCell(self, index, page, height_pt / width_pt if width_pt else 1.414)
                cell.show()
                self._cells.append(cell)
        if self._sections:
            self._order = list(self._sections[0]["pages"])
        self._relayout()

    def total_pages(self, section: int) -> int:
        return self._sections[section]["total"] if section < len(self._sections) else 0

    def cells(self) -> list[PageCell]:
        return list(self._cells)

    # ---- selection ----

    def is_selected(self, key: int) -> bool:
        return key in self._selected

    def toggle(self, key: int) -> None:
        self._selected.symmetric_difference_update({key})
        self._cell(key).update()
        self.selection_changed.emit()

    def _cell(self, key: int) -> PageCell:
        return next(c for c in self._cells if c.key == key)

    def selected_pages(self) -> list[int]:
        """Marked pages of the first section, in page order."""
        return sorted(k % _KEY_STRIDE for k in self._selected if k // _KEY_STRIDE == 0)

    def clear_selection(self) -> None:
        if self._selected:
            self._selected.clear()
            for cell in self._cells:
                cell.update()
            self.selection_changed.emit()

    def select_all(self) -> None:
        self._selected = {c.key for c in self._cells if c.section == 0}
        for cell in self._cells:
            cell.update()
        self.selection_changed.emit()

    # ---- live previews ----

    def set_rotation(self, angle: int) -> None:
        angle = int(angle) % 360
        if angle != self.rotation:
            self.rotation = angle
            self._relayout()  # a quarter turn changes the pages' shape, so the rows too
            for cell in self._cells:
                cell.update()

    def set_overlay(self, overlay) -> None:
        self.overlay = overlay
        for cell in self._cells:
            cell.update()

    def refresh(self) -> None:
        """Repaint every cell (an overlay's inputs changed)."""
        for cell in self._cells:
            cell.update()

    # ---- reorder ----

    def order(self) -> list[int]:
        return list(self._order)

    def _start_drag(self, cell: PageCell) -> None:
        if cell.section != 0:
            return
        mime = QMimeData()
        mime.setData("application/x-pdf-page", str(cell.page).encode())
        drag = QDrag(cell)
        drag.setMimeData(mime)
        drag.setPixmap(cell.grab().scaledToWidth(max(60, cell.width() // 2), Qt.SmoothTransformation))
        drag.setHotSpot(QPoint(cell.width() // 4, 20))
        drag.exec(Qt.MoveAction)

    def _cell_rects(self) -> list[QRect]:
        return [c.geometry() for c in self._cells if c.section == 0]

    def _drop_index(self, pos: QPoint) -> int:
        """The slot (0..n) in the order a page dropped at `pos` would take."""
        rects = self._cell_rects()
        if not rects:
            return 0
        for i, rect in enumerate(rects):
            row_band = QRect(rect.left() - GAP // 2, rect.top() - GAP // 2, rect.width() + GAP, rect.height() + GAP)
            if row_band.contains(pos):
                return i if pos.x() < rect.center().x() else i + 1
        # Between rows / beyond the last: the nearest cell decides.
        nearest = min(range(len(rects)), key=lambda i: (rects[i].center() - pos).manhattanLength())
        return nearest if pos.x() < rects[nearest].center().x() else nearest + 1

    def _drop_line_rect(self, index: int) -> QRect | None:
        rects = self._cell_rects()
        if not rects:
            return None
        if index < len(rects):
            r = rects[index]
            return QRect(r.left() - GAP // 2 - 2, r.top(), 4, r.height() - LABEL_HEIGHT)
        r = rects[-1]
        return QRect(r.right() + GAP // 2 - 2, r.top(), 4, r.height() - LABEL_HEIGHT)

    def _move_page(self, page: int, slot: int) -> None:
        if page not in self._order:
            return
        old = self._order.index(page)
        order = [p for p in self._order if p != page]
        slot = slot - 1 if slot > old else slot
        order.insert(max(0, min(slot, len(order))), page)
        if order != self._order:
            self._order = order
            self._relayout()
            self.order_changed.emit()

    # ---- layout ----

    def cell_width(self) -> int:
        return CELL_WIDTHS[self._cell_index]

    def set_cell_index(self, index: int) -> None:
        index = max(0, min(len(CELL_WIDTHS) - 1, index))
        if index != self._cell_index:
            self._cell_index = index
            self._invalidate()
            self._relayout()
            self._sync_size_buttons()

    def _sync_size_buttons(self) -> None:
        self.zoom_out_btn.setEnabled(self._cell_index > 0)
        self.zoom_in_btn.setEnabled(self._cell_index < len(CELL_WIDTHS) - 1)

    def _relayout(self) -> None:
        available = self._scroll.viewport().width()
        if available < 100:
            available = 900  # not laid out yet; corrected by the first resize
        cw = self.cell_width()
        columns = max(1, (available - GAP) // (cw + GAP))
        left = max(GAP, (available - (columns * cw + (columns - 1) * GAP)) // 2)
        y = GAP
        # Cells of section 0 follow the current order (reorder mode); others their own.
        by_section: dict[int, list[PageCell]] = {}
        for cell in self._cells:
            by_section.setdefault(cell.section, []).append(cell)
        if 0 in by_section and self._order:
            position = {p: i for i, p in enumerate(self._order)}
            by_section[0].sort(key=lambda c: position.get(c.page, 10**9))
        for section in range(len(self._sections)):
            title = self._titles[section]
            if title is not None:
                title.setGeometry(left, y, max(50, available - 2 * left), TITLE_HEIGHT - 6)
                y += TITLE_HEIGHT
            cells = by_section.get(section, [])
            if not cells:
                continue
            box_h = int(cw * max(c.aspect for c in cells) if self.rotation % 180 == 0 else cw * max(1 / c.aspect for c in cells))
            box_h = max(60, min(box_h, int(cw * 1.9)))
            cell_h = box_h + LABEL_HEIGHT
            for i, cell in enumerate(cells):
                row, col = divmod(i, columns)
                cell.setGeometry(left + col * (cw + GAP), y + row * (cell_h + GAP), cw, cell_h)
                if cell.rendered_width != cw:
                    cell.release_pixmap()
            rows = (len(cells) + columns - 1) // columns
            y += rows * (cell_h + GAP) + GAP
        self._canvas.resize(available, max(y, 1))
        self._render_timer.start()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._relayout()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._scroll.viewport() and event.type() == QEvent.Resize:
            self._relayout()
        return super().eventFilter(obj, event)

    # ---- thumbnails (background thread, only near the view) ----

    def _invalidate(self) -> None:
        self._token += 1
        self._pool.clear()
        for cell in self._cells:
            cell.requested_width = 0

    def _render_bytes(self, key: int, long_side: int) -> bytes:
        section, page = divmod(key, _KEY_STRIDE)
        return render_page_thumbnail(self._sections[section]["path"], page, max_size=long_side)

    def _render_visible(self) -> None:
        bar = self._scroll.verticalScrollBar()
        view_h = max(600, self._scroll.viewport().height())
        top, bottom = bar.value() - view_h, bar.value() + 2 * view_h
        dpr = self.devicePixelRatioF()
        for cell in self._cells:
            geo = cell.geometry()
            near = geo.bottom() >= top and geo.top() <= bottom
            if near:
                if cell.rendered_width != cell.width() and cell.requested_width != cell.width():
                    cell.requested_width = cell.width()
                    long_side = int(max(cell.width(), cell.box_height()) * dpr) + 20
                    if PageZoomMixin._SYNC_RENDER:
                        self._on_rendered(self._token, cell.key, cell.width(), self._safe_render(cell.key, long_side))
                    else:
                        self._pool.start(_RenderJob(self._signals, self._safe_render, self._token, cell.key, cell.width(), long_side))
            elif cell.has_pixmap() and (geo.bottom() < top - 2 * view_h or geo.top() > bottom + 2 * view_h):
                cell.release_pixmap()

    def _safe_render(self, key: int, long_side: int) -> bytes:
        try:
            return self._render_bytes(key, long_side)
        except Exception:
            return b""

    def _on_rendered(self, token: int, key: int, width: int, data: bytes) -> None:
        if token != self._token or not data:
            return
        cell = next((c for c in self._cells if c.key == key), None)
        if cell is None or cell.width() != width:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            pixmap.setDevicePixelRatio(1.0)
            cell.pixmap = pixmap
            cell.rendered_width = width
            cell.update()

    def shutdown(self) -> None:
        self._token += 1
        self._pool.clear()
        self._pool.waitForDone(3000)

"""Shared page viewing for the tools that show a document's pages: pages sized to
fit the window, centred, zoomable, and drawn lazily.

Two pieces:
- PagePixmapMixin: for a widget that IS a page. It can be sized before it has a
  picture, shows blank white until one is attached, and can give the picture back.
- PageZoomMixin: for the DIALOG that owns a column of such widgets in a scroll area.
"""
from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from app.core.errors import PDFError
from app.core.pdf_ops import render_page_thumbnail
from app.ui.theme import MUTED_FOREGROUND, icon


class _RenderSignals(QObject):
    """Carries a finished picture from the render thread back to the GUI thread."""

    done = Signal(int, int, int, bytes)  # token, page number, width it was drawn for, PNG bytes


class _RenderJob(QRunnable):
    def __init__(self, signals: _RenderSignals, render, token: int, page_number: int, width: int, long_side: int):
        super().__init__()
        self._signals = signals
        self._render = render
        self._args = (token, page_number, width, long_side)

    def run(self) -> None:
        token, page_number, width, long_side = self._args
        try:
            data = self._render(page_number, long_side)
        except Exception:
            data = b""  # an undrawable page stays blank white
        try:
            self._signals.done.emit(token, page_number, width, data)
        except RuntimeError:
            pass  # the dialog was closed while this was running


class PagePixmapMixin:
    """Put BEFORE QWidget in the bases. The widget's own picture attribute is
    named by PIXMAP_ATTR (existing widgets already call it `pixmap` or
    `page_pixmap`)."""

    PIXMAP_ATTR = "pixmap"
    page_number = 0
    rendered_width = 0
    render_requested_width = 0

    def set_page_size(self, size: QSize) -> None:
        self.setFixedSize(size)
        self._page_sized = True
        self.update()

    def attach_pixmap(self, pixmap) -> None:
        setattr(self, self.PIXMAP_ATTR, pixmap)
        self.rendered_width = self.width()
        self.update()

    def release_pixmap(self) -> None:
        setattr(self, self.PIXMAP_ATTR, None)
        self.rendered_width = 0
        self.render_requested_width = 0
        self.update()

    @property
    def has_pixmap(self) -> bool:
        pixmap = getattr(self, self.PIXMAP_ATTR, None)
        return pixmap is not None and not pixmap.isNull()

    def paint_page_background(self, painter: QPainter) -> None:
        """The page picture at the widget's current size, or blank white."""
        pixmap = getattr(self, self.PIXMAP_ATTR, None)
        if pixmap is not None and not pixmap.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(self.rect(), pixmap)
        elif getattr(self, "_page_sized", False):
            painter.fillRect(self.rect(), Qt.white)  # a page laid out but not drawn yet


class PageZoomMixin:
    """Put BEFORE ToolDialog in the bases.

    The dialog must provide `_scroll` (the QScrollArea holding the pages),
    `_container_layout` (a vertical layout, centred) and `_input_path`, keep
    `_page_pt` ({page: (width_pt, height_pt)}) up to date, call
    `_init_page_zoom()` once the scroll area exists, and call `_fit_and_render()`
    after (re)building its pages. By default the pages are `_page_widgets`
    (None entries skipped); override `_zoom_pages()` otherwise.
    """

    _ZOOM_STEPS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)
    _DEFAULT_ZOOM_INDEX = 2
    _MAX_FIT_WIDTH = 900
    # Defaults up front: a dialog builds its zoom controls before it can call
    # _init_page_zoom (which needs the scroll area to exist).
    _zoom_index = 2
    _fit_width = 400
    # Pages are drawn on a background thread. Tests switch this on to draw them
    # straight away instead, so they do not have to wait.
    _SYNC_RENDER = False

    def _init_page_zoom(self) -> None:
        self._zoom_index = self._DEFAULT_ZOOM_INDEX
        self._fit_width = 400
        self._page_pt: dict[int, tuple[float, float]] = {}
        # Draw only the pages near the viewport (a long document at a big zoom
        # would otherwise render every page at once), and re-fit on resize.
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(60)
        self._render_timer.timeout.connect(self._render_pages)
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(120)
        self._refit_timer.timeout.connect(self._refit)
        self._scroll.verticalScrollBar().valueChanged.connect(lambda _v: self._render_timer.start())
        self._scroll.viewport().installEventFilter(self)  # Ctrl+scroll zooms
        # One background thread draws pages (MuPDF is not happy being driven from
        # several threads at once), so scrolling never waits on a page render.
        self._render_pool = QThreadPool(self)
        self._render_pool.setMaxThreadCount(1)
        self._render_signals = _RenderSignals(self)
        self._render_signals.done.connect(self._on_page_rendered)
        self._render_token = 0

    def _make_zoom_row(self) -> QWidget:
        """A small centred [-] 100% [+] control for tools with no toolbar of
        their own, and the zoom keyboard shortcuts."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addStretch(1)

        def icon_button(icon_name: str, name: str, tooltip: str, step: int) -> QPushButton:
            btn = QPushButton()
            btn.setObjectName("toolbarIcon")
            btn.setIcon(icon(icon_name, MUTED_FOREGROUND, 18))
            btn.setToolTip(tooltip)
            btn.setAccessibleName(name)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda _=False: self._set_zoom(self._zoom_index + step))
            return btn

        self.zoom_out_btn = icon_button("magnifying-glass-minus", "Zoom out", "Zoom out (Ctrl+-, or Ctrl+scroll)", -1)
        self.zoom_label_btn = QPushButton("100%")
        self.zoom_label_btn.setObjectName("toolbarIcon")
        self.zoom_label_btn.setMinimumWidth(58)
        self.zoom_label_btn.setToolTip("Reset to 100% (Ctrl+0)")
        self.zoom_label_btn.setAccessibleName("Zoom level")
        self.zoom_label_btn.setFocusPolicy(Qt.NoFocus)
        self.zoom_label_btn.clicked.connect(lambda: self._set_zoom(self._DEFAULT_ZOOM_INDEX))
        self.zoom_in_btn = icon_button("magnifying-glass-plus", "Zoom in", "Zoom in (Ctrl++, or Ctrl+scroll)", 1)
        for btn in (self.zoom_out_btn, self.zoom_label_btn, self.zoom_in_btn):
            layout.addWidget(btn)
        layout.addStretch(1)
        for keys, step in (("Ctrl+=", 1), ("Ctrl++", 1), ("Ctrl+-", -1)):
            QShortcut(QKeySequence(keys), self).activated.connect(lambda s=step: self._set_zoom(self._zoom_index + s))
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(lambda: self._set_zoom(self._DEFAULT_ZOOM_INDEX))
        self._refresh_zoom_controls()
        return row

    # ---- hooks a dialog may override ----

    def _zoom_pages(self) -> list:
        return [w for w in self._page_widgets if w is not None]

    def _page_display_size(self, widget) -> QSize:
        width = max(160, int(round(self._fit_width * self._zoom_factor())))
        w_pt, h_pt = self._page_pt.get(widget.page_number, (0.0, 0.0))
        height = int(round(width * h_pt / w_pt)) if w_pt > 0 and h_pt > 0 else int(width * 1.414)
        return QSize(width, max(1, height))

    def _render_page_bytes(self, page_number: int, long_side: int) -> bytes:
        return render_page_thumbnail(self._input_path, page_number, max_size=long_side)

    def _render_page(self, widget) -> None:
        if self._input_path is None:
            return
        dpr = self.devicePixelRatioF()
        long_side = int(round(max(widget.width(), widget.height()) * dpr))
        if self._SYNC_RENDER:
            try:
                data = self._render_page_bytes(widget.page_number, long_side)
            except PDFError:
                return  # leaves a blank white page; everything else still works
            self._attach_rendered(widget, data)
            return
        if widget.render_requested_width == widget.width():
            return  # already queued (or drawing) at this size
        widget.render_requested_width = widget.width()
        self._render_pool.start(
            _RenderJob(self._render_signals, self._render_page_bytes, self._render_token,
                       widget.page_number, widget.width(), long_side)
        )

    def _attach_rendered(self, widget, data: bytes) -> None:
        pixmap = QPixmap()
        if not data or not pixmap.loadFromData(data):
            return
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        widget.attach_pixmap(pixmap)

    def _on_page_rendered(self, token: int, page_number: int, width: int, data: bytes) -> None:
        if token != self._render_token:
            return  # a different document, or a different zoom, since this was asked for
        for widget in self._zoom_pages():
            if widget.page_number == page_number and widget.width() == width:
                self._attach_rendered(widget, data)
                return

    def _invalidate_renders(self) -> None:
        """Pages are about to change size (or the document changed): anything still
        queued or drawing is for the wrong size, so its result must be ignored."""
        self._render_token += 1
        self._render_pool.clear()
        for widget in self._zoom_pages():
            widget.render_requested_width = 0

    def shutdown(self) -> None:
        """Stop drawing pages; called before the dialog goes away."""
        self._render_token += 1
        self._render_pool.clear()
        self._render_pool.waitForDone(3000)

    # ---- the shared machinery ----

    def _zoom_factor(self) -> float:
        return self._ZOOM_STEPS[self._zoom_index]

    def _compute_fit_width(self) -> int:
        """Page width that fits the window (never absurdly wide or narrow)."""
        available = self._scroll.viewport().width() - 48
        return max(320, min(self._MAX_FIT_WIDTH, available))

    def _layout_pages(self) -> None:
        if self._input_path is None:
            return
        for widget in self._zoom_pages():
            size = self._page_display_size(widget)
            if widget.size() != size:
                widget.set_page_size(size)
            if widget.rendered_width != size.width():
                widget.release_pixmap()  # stale zoom: blank until redrawn
        self._container_layout.activate()

    def _render_pages(self) -> None:
        """Draws the pages near the viewport and frees ones far from it."""
        bar = self._scroll.verticalScrollBar()
        # Never less than a screenful, so a dialog that has not been laid out yet
        # (no real viewport height) still draws its first pages.
        view_height = max(600, self._scroll.viewport().height())
        top = bar.value() - view_height
        bottom = bar.value() + 2 * view_height
        # Page positions worked out from their sizes (they stack in a column),
        # rather than read from the layout, which may not have settled yet.
        y = self._container_layout.contentsMargins().top()
        spacing = self._container_layout.spacing()
        for widget in self._zoom_pages():
            y0, y1 = y, y + widget.height()
            y = y1 + spacing
            if y1 >= top and y0 <= bottom:
                if widget.rendered_width != widget.width():
                    self._render_page(widget)
            elif widget.has_pixmap and (y1 < top - 2 * view_height or y0 > bottom + 2 * view_height):
                widget.release_pixmap()

    def _fit_and_render(self) -> None:
        self._invalidate_renders()
        self._fit_width = self._compute_fit_width()
        self._layout_pages()
        self._render_pages()

    def _refresh_zoom_controls(self) -> None:
        if not hasattr(self, "zoom_label_btn"):
            return
        self.zoom_label_btn.setText(f"{round(self._zoom_factor() * 100)}%")
        self.zoom_out_btn.setEnabled(self._zoom_index > 0)
        self.zoom_in_btn.setEnabled(self._zoom_index < len(self._ZOOM_STEPS) - 1)

    def _before_zoom(self) -> None:
        """Hook: a dialog with open editors commits them before pages resize."""

    def _set_zoom(self, index: int) -> None:
        index = max(0, min(len(self._ZOOM_STEPS) - 1, index))
        if index == self._zoom_index:
            return
        self._before_zoom()
        self._invalidate_renders()
        bar = self._scroll.verticalScrollBar()
        position = bar.value() / bar.maximum() if bar.maximum() else 0.0
        self._zoom_index = index
        self._refresh_zoom_controls()
        self._layout_pages()
        bar.setValue(int(position * bar.maximum()))  # keep roughly the same part of the document in view
        self._render_pages()

    def _refit(self) -> None:
        """The window was resized: re-fit the pages to it."""
        if not self._zoom_pages():
            return
        fit = self._compute_fit_width()
        if abs(fit - self._fit_width) >= 16:
            self._before_zoom()
            self._invalidate_renders()
            self._fit_width = fit
            self._layout_pages()
            self._render_pages()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._refit_timer.start()

    def closeEvent(self, e) -> None:
        self.shutdown()
        super().closeEvent(e)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._scroll.viewport() and event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self._set_zoom(self._zoom_index + (1 if delta > 0 else -1))
            return True
        return super().eventFilter(obj, event)

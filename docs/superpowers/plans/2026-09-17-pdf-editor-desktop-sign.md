# Desktop App: Sign PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Sign PDF to the desktop app — draw or upload a signature, then place, resize, and remove it across any number of pages.

**Architecture:** Two new widgets in `app/ui/widgets.py` — a freehand-drawing pad (`SignaturePadWidget`) and a create/move/resize/remove image-placement surface (`ImagePlacementWidget`) — consumed by a two-phase `SignDialog` that reuses `RedactDialog`'s exact page-switch/accumulate pattern and submits through the already-existing `edit_pdf` core function using plain `image`-type elements.

**Tech Stack:** Python, PySide6, PySide6.QtTest, pytest.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task in this plan ships new, intentional behavior — commits are `feat:` and must **not** carry the trailer.
- Real automated pytest tests using `PySide6.QtTest`'s synthetic mouse events, appended to the existing `tests/test_ui_desktop.py` — not a manual checklist, matching the precedent set by the Crop/Redact plan. That file already sets `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at its top; no task needs to touch that line.
- Output filename must be exactly `<stem>_signed.pdf`.
- `edit_pdf` already raises `PDFError("Add at least one edit before running.")` when `elements` is empty — **no extra dialog-side "place at least one signature" check is needed** (this corrects an assumption in the design spec, made while re-reading `edit_pdf`'s current code before writing this plan — the spec assumed Sign needed its own equivalent of `CropDialog`'s "nothing drawn" check, but `edit_pdf` already covers this generically).

---

### Task 1: `SignaturePadWidget`

**Files:**
- Modify: `app/ui/widgets.py` (add the new class)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: nothing from another task (this is the first task).
- Produces: `SignaturePadWidget(width: int = 400, height: int = 150)` with `.has_drawing() -> bool`, `.clear() -> None`, `.save_png(path: str) -> None`. Task 3's `SignDialog` uses all three directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`. This needs `QImage` added to the existing `from PySide6.QtGui import QPixmap` import line (making it `from PySide6.QtGui import QImage, QPixmap`), and a new import for the widget:
```python
from app.ui.widgets import SignaturePadWidget


def test_signature_pad_starts_blank():
    pad = SignaturePadWidget()
    assert pad.has_drawing() is False


def test_signature_pad_drawing_sets_has_drawing_and_produces_real_pixels(tmp_path):
    pad = SignaturePadWidget()
    QTest.mousePress(pad, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
    QTest.mouseMove(pad, QPoint(100, 100))
    QTest.mouseMove(pad, QPoint(200, 50))
    QTest.mouseRelease(pad, Qt.LeftButton, Qt.NoModifier, QPoint(200, 50))
    assert pad.has_drawing() is True

    png_path = str(tmp_path / "sig.png")
    pad.save_png(png_path)
    saved = QImage(png_path)
    assert (saved.width(), saved.height()) == (400, 150)

    # A pixel on the drawn stroke's path is dark; a corner nowhere near any
    # stroke is untouched white - confirmed empirically against this exact
    # drag before this test was written (a real drawn pixel was found by
    # scanning the whole image; corner (390, 5) was picked as clearly
    # outside the (20,20)-(100,100)-(200,50) stroke path).
    found_dark_pixel = any(
        saved.pixelColor(x, y).red() < 100
        for x in range(0, 400, 2)
        for y in range(0, 150, 2)
    )
    assert found_dark_pixel
    corner = saved.pixelColor(390, 5)
    assert corner.red() > 240 and corner.green() > 240 and corner.blue() > 240


def test_signature_pad_clear_resets_has_drawing():
    pad = SignaturePadWidget()
    QTest.mousePress(pad, Qt.LeftButton, Qt.NoModifier, QPoint(20, 20))
    QTest.mouseRelease(pad, Qt.LeftButton, Qt.NoModifier, QPoint(100, 100))
    assert pad.has_drawing() is True
    pad.clear()
    assert pad.has_drawing() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k signature_pad -v`
Expected: FAIL — `SignaturePadWidget` doesn't exist yet.

- [ ] **Step 3: Implement `SignaturePadWidget`**

Add to `app/ui/widgets.py` (add `QImage` to the existing `from PySide6.QtGui import QColor, QPainter, QPen` import line, and `Qt` to the existing `from PySide6.QtCore import QPoint, QRect` import line):
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k signature_pad -v`
Expected: PASS (3 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as before plus 3.

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets.py tests/test_ui_desktop.py
git commit -m "feat: add a freehand signature-drawing widget to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 2: `ImagePlacementWidget`

**Files:**
- Modify: `app/ui/widgets.py` (add the new class)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: nothing from Task 1 (independent of it — this widget doesn't know or care where the signature image came from, only that it has one).
- Produces: `ImagePlacementWidget()` with `.set_page_pixmap(QPixmap)`, `.set_signature_pixmap(QPixmap)`, `.set_placements(list[dict])`, `.placements` (list of `{"x","y","width","height"}` fraction dicts, no page tag). Task 3's `SignDialog` uses all of these directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
from app.ui.widgets import ImagePlacementWidget


def _make_placement_widget():
    widget = ImagePlacementWidget()
    page_pixmap = QPixmap(424, 600)
    page_pixmap.fill(Qt.white)
    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    widget.set_page_pixmap(page_pixmap)
    widget.set_signature_pixmap(sig_pixmap)
    return widget


def test_empty_space_click_creates_a_placement_with_default_sizing():
    widget = _make_placement_widget()
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.5), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert len(widget.placements) == 1
    p = widget.placements[0]
    # Verified empirically before this test was written: a 200x80 signature
    # (aspect 0.4) at the default width fraction 0.25 gives height 0.1
    # (0.25 * 0.4), centered on the click point (0.5, 0.3) and unclamped
    # since it's well away from every edge.
    assert p == {"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.1}


def test_marker_and_handle_rects_do_not_overlap_for_a_default_sized_placement():
    widget = _make_placement_widget()
    p = {"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.1}
    marker = widget._marker_rect(p)
    handle = widget._handle_rect(p)
    assert not marker.intersects(handle)


def test_clicking_a_placements_body_moves_it():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.375, "y": 0.25, "width": 0.25, "height": 0.1}])
    w, h = widget.width(), widget.height()
    rect = widget._placement_rect_px(widget.placements[0])
    body = QPoint(rect.left() + rect.width() // 2, rect.top() + rect.height() // 2)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 20, body.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 20, body.y() + 10))
    p = widget.placements[0]
    # Verified empirically: moving by (20, 10) pixels on this exact 424x600
    # widget shifts the fraction position by (20/424, 10/600), unclamped.
    assert p["x"] == pytest.approx(0.4221698113207547)
    assert p["y"] == pytest.approx(0.26666666666666666)
    assert p["width"] == pytest.approx(0.25)  # unchanged by a move
    assert p["height"] == pytest.approx(0.1)


def test_clicking_a_placements_handle_resizes_it_aspect_locked():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.4221698113207547, "y": 0.26666666666666666, "width": 0.25, "height": 0.1}])
    p = widget.placements[0]
    handle = widget._handle_rect(p)
    hx, hy = handle.center().x(), handle.center().y()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx, hy))
    QTest.mouseMove(widget, QPoint(hx + 30, hy + 30))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx + 30, hy + 30))
    resized = widget.placements[0]
    # Verified empirically: dragging the handle +30px horizontally widens
    # the box by 30/424 of the page width, and height follows the locked
    # aspect ratio (0.1/0.25 = 0.4) - not the vertical drag distance at all.
    assert resized["width"] == pytest.approx(0.32075471698113206)
    assert resized["height"] == pytest.approx(0.12830188679245283)


def test_clicking_a_placements_marker_removes_it():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.4221698113207547, "y": 0.26666666666666666, "width": 0.3207547169811321, "height": 0.12830188679245286}])
    marker = widget._marker_rect(widget.placements[0])
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert widget.placements == []


def test_resize_past_the_page_edge_clamps_to_the_available_space():
    widget = _make_placement_widget()
    widget.set_placements([{"x": 0.6, "y": 0.6, "width": 0.25, "height": 0.1}])
    p = widget.placements[0]
    handle = widget._handle_rect(p)
    hx, hy = handle.center().x(), handle.center().y()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx, hy))
    QTest.mouseMove(widget, QPoint(hx + 500, hy + 500))  # a drag far past any edge
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(hx + 500, hy + 500))
    resized = widget.placements[0]
    # Verified empirically: at x=0.6, the widthCap (1 - x = 0.4) binds before
    # the raw dragged-width would, so width clamps to exactly 0.4 and height
    # follows the same 0.1/0.25=0.4 aspect ratio (0.4 * 0.4 = 0.16) - not
    # some other value influenced by the vertical drag distance.
    assert resized["width"] == pytest.approx(0.4)
    assert resized["height"] == pytest.approx(0.16)
    assert resized["x"] + resized["width"] <= 1.0 + 1e-9
    assert resized["y"] + resized["height"] <= 1.0 + 1e-9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "placement or marker_and_handle" -v`
Expected: FAIL — `ImagePlacementWidget` doesn't exist yet.

- [ ] **Step 3: Implement `ImagePlacementWidget`**

Add to `app/ui/widgets.py`:
```python
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

    def _marker_rect(self, p: dict) -> QRect:
        rect = self._placement_rect_px(p)
        return QRect(rect.right() - _MARKER_SIZE, rect.top(), _MARKER_SIZE, _MARKER_SIZE)

    def _handle_rect(self, p: dict) -> QRect:
        rect = self._placement_rect_px(p)
        return QRect(rect.right() - _HANDLE_SIZE, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE)

    def mousePressEvent(self, e) -> None:
        pos = e.position().toPoint()
        for i, p in enumerate(self.placements):
            if self._marker_rect(p).contains(pos):
                del self.placements[i]
                self.update()
                return
        for i, p in enumerate(self.placements):
            if self._handle_rect(p).contains(pos):
                point = self._point_from_pos(pos)
                self._drag = {"mode": "resize", "index": i, "start": point, "start_placement": dict(p)}
                return
        for i, p in enumerate(self.placements):
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
            handle = self._handle_rect(p)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(40, 100, 220))
            painter.drawRect(handle)
```
`_MARKER_SIZE` is already defined at module level (from the Crop/Redact
plan's `RectangleOverlayWidget`) — reuse it, don't redefine it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (all of Task 1's 3 plus this task's 6 — 9 new tests total so
far in this plan, on top of the 9 already in the file from Crop/Redact).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 1 plus 6.

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets.py tests/test_ui_desktop.py
git commit -m "feat: add a create/move/resize/remove image-placement widget to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 3: `SignDialog`

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (add the new class)
- Modify: `app/main.py` (import line, registration line)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `SignaturePadWidget` (Task 1) and `ImagePlacementWidget` (Task 2), both unchanged.
- Produces: nothing consumed by any other task (this is the last task in the plan).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_desktop.py`:
```python
def test_sign_dialog_places_a_signature_and_exports_it(tmp_path):
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842).insert_text((72, 72), "Original page text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)  # bypasses the draw/upload UI, sets signature_path + natural size directly
    dlg.on_files_changed([str(input_path)])

    w, h = dlg.overlay.width(), dlg.overlay.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert len(dlg.overlay.placements) == 1

    params = dlg.gather_params()
    assert params["signature_path"] == sig_path
    assert len(params["placements"]) == 1
    assert params["placements"][0]["page"] == 1

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    page = result[0]
    images = page.get_images()
    assert len(images) == 1
    result.close()


def test_sign_dialog_raises_when_no_signature_placed(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Some text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "signature.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = SignDialog()
    dlg.use_signature_file(sig_path)
    dlg.on_files_changed([str(input_path)])
    params = dlg.gather_params()
    assert params["placements"] == []
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "at least one" in str(exc)
```
`use_signature_file` (Step 3 below) is a small, dedicated entry point
`SignDialog` provides specifically so a test can set the acquired-signature
state directly, without driving the "Draw new"/"Upload new" buttons through
`QFileDialog` (which can't be synthesized headlessly) — the real UI's
"Upload new" button calls this exact same method after `QFileDialog.getOpenFileName`
returns a path, so this isn't test-only scaffolding grafted on top, it's
the natural shared entry point both the UI and this test go through.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_desktop.py -k sign_dialog -v`
Expected: FAIL — `SignDialog` doesn't exist yet.

- [ ] **Step 3: Implement `SignDialog`**

Add to `app/ui/dialogs/edit_dialogs.py`'s imports (merge into the existing
lines — check the current file first, since Crop/Redact already added
several of these):
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QLineEdit, QSlider, QSpinBox, QPushButton, QFileDialog, QMessageBox
from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf, redact_pdf, render_page_thumbnail, get_page_count, edit_pdf
from app.ui.widgets import RectangleOverlayWidget, box_to_insets, insets_to_box, SignaturePadWidget, ImagePlacementWidget
```
(`Path`, `Qt`, `QPixmap`, and `PDFError` are already imported by the current file — no changes needed to those lines.)
Also add `import os` as a new line at the very top of the file, before the existing `from pathlib import Path` line — it isn't there yet and `_save_drawn_signature` (Step 3 below) needs `os.close(fd)`.

Add this class at the end of the file, after `RedactDialog`:
```python
class SignDialog(ToolDialog):
    title = "Sign PDF"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)

        self.source_panel = QWidget()
        source_layout = QVBoxLayout(self.source_panel)
        draw_row = QHBoxLayout()
        draw_btn = QPushButton("Draw new")
        draw_btn.clicked.connect(self._toggle_draw_pad)
        draw_row.addWidget(draw_btn)
        upload_btn = QPushButton("Upload new")
        upload_btn.clicked.connect(self._upload_signature)
        draw_row.addWidget(upload_btn)
        source_layout.addLayout(draw_row)

        self.pad_panel = QWidget()
        pad_layout = QVBoxLayout(self.pad_panel)
        self.pad = SignaturePadWidget()
        pad_layout.addWidget(self.pad)
        pad_button_row = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.pad.clear)
        pad_button_row.addWidget(clear_btn)
        save_btn = QPushButton("Save signature")
        save_btn.clicked.connect(self._save_drawn_signature)
        pad_button_row.addWidget(save_btn)
        pad_layout.addLayout(pad_button_row)
        self.pad_panel.setVisible(False)
        source_layout.addWidget(self.pad_panel)
        layout.addWidget(self.source_panel)

        self.placement_panel = QWidget()
        placement_layout = QVBoxLayout(self.placement_panel)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Page:"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._load_current_page)
        page_row.addWidget(self.page_spin)
        placement_layout.addLayout(page_row)
        instruction = QLabel("Click to place your signature; drag to move it, its corner handle to resize, or click the × to remove it:")
        instruction.setWordWrap(True)
        placement_layout.addWidget(instruction)
        self.overlay = ImagePlacementWidget()
        placement_layout.addWidget(self.overlay)
        different_btn = QPushButton("Use a different signature")
        different_btn.clicked.connect(self._use_different_signature)
        placement_layout.addWidget(different_btn)
        self.placement_panel.setVisible(False)
        layout.addWidget(self.placement_panel)

        self.signature_path: str | None = None
        self._all_placements: list[dict] = []
        self._current_page: int | None = None
        self._input_path: str | None = None

    def _toggle_draw_pad(self) -> None:
        self.pad_panel.setVisible(not self.pad_panel.isVisible())

    def _save_drawn_signature(self) -> None:
        if not self.pad.has_drawing():
            QMessageBox.warning(self, "Nothing drawn", "Draw a signature first.")
            return
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        self.pad.save_png(path)
        self.use_signature_file(path)

    def _upload_signature(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select signature image", "", "Image files (*.png *.jpg *.jpeg)")
        if path:
            self.use_signature_file(path)

    def use_signature_file(self, path: str) -> None:
        """Adopts `path` as the current signature source and switches to the
        placement phase - the single entry point both 'Draw new'/'Upload
        new' and tests use."""
        self.signature_path = path
        pixmap = QPixmap(path)
        self.overlay.set_signature_pixmap(pixmap)
        self.source_panel.setVisible(False)
        self.placement_panel.setVisible(True)
        self._load_current_page()

    def _use_different_signature(self) -> None:
        self.signature_path = None
        self._all_placements = []
        self._current_page = None
        self.pad.clear()
        self.pad_panel.setVisible(False)
        self.placement_panel.setVisible(False)
        self.source_panel.setVisible(True)

    def on_files_changed(self, paths: list[str]) -> None:
        self._all_placements = []
        self._current_page = None
        self._input_path = paths[0] if paths else None
        if self._input_path is None:
            return
        try:
            count = get_page_count(self._input_path)
        except PDFError:
            return
        self.page_spin.setMaximum(count)
        self.page_spin.setValue(1)
        if self.signature_path is not None:
            self._load_current_page()

    def _flush_current_page(self) -> None:
        if self._current_page is None:
            return
        self._all_placements = [p for p in self._all_placements if p["page"] != self._current_page]
        self._all_placements.extend(
            {"page": self._current_page, **p} for p in self.overlay.placements
        )

    def _load_current_page(self) -> None:
        if self._input_path is None or self.signature_path is None:
            return
        self._flush_current_page()
        page_num = self.page_spin.value()
        self._current_page = page_num
        try:
            thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=450)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_page_pixmap(pixmap)
        page_placements = [
            {"x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"]}
            for p in self._all_placements if p["page"] == page_num
        ]
        self.overlay.set_placements(page_placements)

    def gather_params(self) -> dict:
        self._flush_current_page()
        return {"signature_path": self.signature_path, "placements": list(self._all_placements)}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        signature_path = params["signature_path"]
        elements = [
            {
                "type": "image", "page": p["page"], "file_id": signature_path,
                "x": p["x"], "y": p["y"], "width": p["width"], "height": p["height"],
            }
            for p in params["placements"]
        ]
        image_paths = {signature_path: signature_path}
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_signed.pdf"))
        edit_pdf(input_path, out_path, elements, image_paths)
        return [out_path]
```
Note `run_operation` deliberately does NOT check `if not params["placements"]:`
itself — `edit_pdf` already raises `PDFError("Add at least one edit before
running.")` for an empty `elements` list (confirmed in this plan's Global
Constraints), so `test_sign_dialog_raises_when_no_signature_placed`'s
expected error message is `edit_pdf`'s own, not a new one this dialog adds.

- [ ] **Step 4: Register `SignDialog` in `app/main.py`**

Change the import line (currently ending `..., CropDialog, RedactDialog`):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog, RedactDialog, SignDialog
```
Add this line directly after `window.add_tool("Edit", "Redact PDF", RedactDialog)`:
```python
    window.add_tool("Edit", "Sign PDF", SignDialog)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (all prior tests in the file plus this task's 2 — the full
file should now have 9 [Crop/Redact] + 3 [Task 1] + 6 [Task 2] + 2 [Task 3]
= 20 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 2 plus 2.

- [ ] **Step 6: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/main.py tests/test_ui_desktop.py
git commit -m "feat: add a Sign PDF dialog to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

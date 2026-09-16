# Desktop App: Crop PDF and Redact PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Crop PDF and Redact PDF to the desktop app, both needing an interactive drag-a-rectangle-over-a-page preview that `ToolDialog`'s existing passive thumbnail strip can't provide.

**Architecture:** `ToolDialog` gains one new override hook so a dialog can replace its default thumbnail strip with something else. A new, shared `RectangleOverlayWidget` (single-box mode for Crop, multi-box-with-removable-markers mode for Redact) implements the actual drag/click mechanics, converting pixel positions to page fractions exactly like the web app's `CropSelector.jsx`/`RedactSelector.jsx`. Both interactions are driven and verified in real automated pytest tests using `PySide6.QtTest`'s synthetic mouse events — confirmed working against an offscreen widget before this plan was written.

**Tech Stack:** Python, PySide6, PySide6.QtTest, pytest.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Both tasks in this plan ship new, intentional behavior — commits are `feat:` and must **not** carry the trailer.
- Both tools' output filenames must exactly match the web app's own: `<stem>_cropped.pdf`, `<stem>_redacted.pdf`.
- Redact shows one page at a time (a page-number spinner), not a continuous scroll of every page. Removing a redaction box works by clicking its × marker directly on the drawn box, not a side list.
- Unlike prior desktop-dialog plans this session, this one adds REAL pytest test files (`tests/test_ui_desktop.py`) — the drag/click mechanics are genuinely new, interactive logic worth locking in with regression tests, unlike the earlier simple dialogs which were thin wrappers around already-tested `app/core` functions. Every test in this plan sets `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at the top of the file, before importing anything from `PySide6`, so the file works whether or not that variable was set externally, and safely becomes part of the ordinary `pytest -q` full-suite run (confirmed this doesn't affect any other test — `QT_QPA_PLATFORM` is read only by Qt's own platform-plugin loader).

---

### Task 1: `RectangleOverlayWidget` + the `build_preview` hook + `CropDialog`

**Files:**
- Modify: `app/ui/dialogs/base.py` (`ToolDialog.__init__`, currently lines 32-78; add `dialog_size` class attribute)
- Create: `app/ui/widgets.py`
- Modify: `app/ui/dialogs/edit_dialogs.py` (add `CropDialog`)
- Modify: `app/main.py` (import line 8, registration lines 20-22)
- Test: `tests/test_ui_desktop.py` (new file)

**Interfaces:**
- Consumes: nothing from another task (this is the first task).
- Produces: `RectangleOverlayWidget(multi: bool = False)` (`app/ui/widgets.py`) with `.set_pixmap(QPixmap)`, `.set_boxes(list[dict])`, `.boxes` (list of `{"x0","y0","x1","y1"}` fraction dicts), `.single_box() -> dict | None`; module-level `box_to_insets(box) -> dict` and `insets_to_box(insets) -> dict`. `ToolDialog.build_preview(container)` override hook. Task 2's `RedactDialog` uses all of these directly.

- [ ] **Step 1: Extract the thumbnail-strip code into the new `build_preview` hook**

In `app/ui/dialogs/base.py`, add a `dialog_size` class attribute next to the existing ones (currently lines 28-30):
```python
    title = "Tool"
    file_filter = "PDF files (*.pdf)"
    allow_multiple_files = False
    dialog_size = (480, 360)
```
Change `self.resize(480, 360)` (currently line 35) to:
```python
        self.resize(*self.dialog_size)
```
Replace the inline thumbnail-strip construction in `__init__` (currently lines 49-56):
```python
        self.thumbnail_strip = QScrollArea()
        self.thumbnail_strip.setWidgetResizable(True)
        self.thumbnail_strip.setFixedHeight(130)
        self.thumbnail_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumbnail_container = QWidget()
        self._thumbnail_layout = QHBoxLayout(self._thumbnail_container)
        self.thumbnail_strip.setWidget(self._thumbnail_container)
        layout.addWidget(self.thumbnail_strip)
```
with:
```python
        self.preview_widget = QWidget()
        self.build_preview(self.preview_widget)
        layout.addWidget(self.preview_widget)
```
Add the new `build_preview` method right above `build_options` (currently line 80), containing exactly the code just removed, now as the default implementation:
```python
    def build_preview(self, container: QWidget) -> None:
        """Override in subclasses to replace the default thumbnail-strip preview
        with something else (e.g. an interactive rectangle-selection widget for
        Crop/Redact). Default: the existing horizontal scrolling thumbnail strip."""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        self.thumbnail_strip = QScrollArea()
        self.thumbnail_strip.setWidgetResizable(True)
        self.thumbnail_strip.setFixedHeight(130)
        self.thumbnail_strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._thumbnail_container = QWidget()
        self._thumbnail_layout = QHBoxLayout(self._thumbnail_container)
        self.thumbnail_strip.setWidget(self._thumbnail_container)
        layout.addWidget(self.thumbnail_strip)
```
Guard `_refresh_thumbnails` (currently lines 123-146) so it's a no-op for a
dialog that overrode `build_preview` and never created `_thumbnail_layout`:
add this as the very first line inside the method:
```python
    def _refresh_thumbnails(self) -> None:
        if not hasattr(self, "_thumbnail_layout"):
            return
        while self._thumbnail_layout.count():
            ...  # rest of the method unchanged
```

- [ ] **Step 2: Write the failing widget tests**

Create `tests/test_ui_desktop.py`:
```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.core.pdf_ops import crop_pdf, render_page_thumbnail
from app.ui.widgets import RectangleOverlayWidget, box_to_insets, insets_to_box

_app = QApplication.instance() or QApplication([])


def test_single_mode_drag_creates_one_box():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert widget.single_box() == {"x0": 0.1, "y0": 0.1, "x1": 0.75, "y1": 0.8}


def test_single_mode_second_drag_replaces_the_box():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(0, 0))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(40, 40))
    assert len(widget.boxes) == 1
    assert widget.single_box() == {"x0": 0.0, "y0": 0.0, "x1": 0.2, "y1": 0.4}


def test_drag_below_min_fraction_is_ignored():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(21, 11))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(21, 11))
    assert widget.boxes == []


def test_multi_mode_two_boxes_then_remove_one_via_its_marker():
    widget = RectangleOverlayWidget(multi=True)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(10, 60))
    QTest.mouseMove(widget, QPoint(60, 90))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(60, 90))
    assert len(widget.boxes) == 2

    first_box = widget.boxes[0]
    marker = widget._marker_rect(first_box)
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)

    assert len(widget.boxes) == 1
    assert widget.boxes[0] == {"x0": 0.05, "y0": 0.6, "x1": 0.3, "y1": 0.9}


def test_box_to_insets_and_back_round_trip():
    box = {"x0": 0.1, "y0": 0.2, "x1": 0.7, "y1": 0.8}
    insets = box_to_insets(box)
    assert insets == {"top": 0.2, "left": 0.1, "right": 0.3, "bottom": 0.2}
    assert insets_to_box(insets) == box


def test_crop_dialog_offscreen_end_to_end(tmp_path):
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "REMOVE THIS")
    page.insert_text((72, 700), "KEEP THIS")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(input_path)])
    w, h = dlg.overlay.width(), dlg.overlay.height()
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
    QTest.mouseMove(dlg.overlay, QPoint(int(w * 0.6), int(h * 0.15)))
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    params = dlg.gather_params()
    assert params["box"] is not None
    output_paths = dlg.run_operation([str(input_path)], params)

    result = fitz.open(output_paths[0])
    text = result[0].get_text()
    result.close()
    # This drag keeps only a thin strip near the TOP of the page (y-fraction
    # 0.05 to 0.15) - "REMOVE THIS" sits there (inserted at y=72 on an 842pt
    # page) and survives the crop; "KEEP THIS" (inserted at y=700, near the
    # bottom) is cropped away entirely along with the rest of the page below
    # the kept strip. Verified empirically against this exact fixture before
    # this plan was written - the fixture's own naming ("REMOVE THIS") refers
    # to the Redact tests' convention (Task 2), not this crop test's outcome.
    assert "REMOVE THIS" in text
    assert "KEEP THIS" not in text


def test_crop_dialog_raises_when_no_box_drawn(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Some text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(input_path)])
    params = dlg.gather_params()
    assert params["box"] is None
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "crop area" in str(exc)


def test_compress_dialog_still_builds_its_thumbnail_strip():
    from app.ui.dialogs.optimize_dialogs import CompressDialog

    dlg = CompressDialog()
    assert hasattr(dlg, "thumbnail_strip")
    assert hasattr(dlg, "_thumbnail_layout")
    assert dlg.quality_slider.value() == 60
```
- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` for `app.ui.widgets` and for `CropDialog` (neither exists yet), and `AttributeError` on `ToolDialog` instances for `build_preview`-related state.

- [ ] **Step 4: Implement `RectangleOverlayWidget`**

Create `app/ui/widgets.py`:
```python
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
```
The exact pixel arithmetic used for the X marker's two lines is fiddly and
**not** covered by any test (painting isn't observable through `QTest`'s
synthetic events, only behavior is) — if it looks visually off once someone
actually looks at a real window, it's safe to simplify (e.g. draw a plain
filled circle with no X glyph) without affecting anything this plan's tests
check.

- [ ] **Step 5: Add `CropDialog`**

In `app/ui/dialogs/edit_dialogs.py`, add to the import line (currently line 4):
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QLabel, QLineEdit, QSlider
```
add `QLabel` is already there; no change needed to that import line itself.
Add a new import line for the widget module and `crop_pdf`:
```python
from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf
from app.core.errors import PDFError
from app.ui.widgets import RectangleOverlayWidget, box_to_insets
```
(merge `crop_pdf` into the existing `app.core.pdf_ops` import line rather than adding a second one for the same module). Add this class at the end of the file:
```python
class CropDialog(ToolDialog):
    title = "Crop PDF"
    dialog_size = (650, 750)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Drag to select the area to KEEP (page 1's layout applies to every page):"))
        self.overlay = RectangleOverlayWidget(multi=False)
        layout.addWidget(self.overlay)

    def on_files_changed(self, paths: list[str]) -> None:
        if not paths:
            return
        from app.core.pdf_ops import render_page_thumbnail
        from PySide6.QtGui import QPixmap
        try:
            thumb_bytes = render_page_thumbnail(paths[0], 1, max_size=600)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_pixmap(pixmap)

    def gather_params(self) -> dict:
        return {"box": self.overlay.single_box()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        box = params["box"]
        if box is None:
            raise PDFError("Drag to select a crop area first.")
        insets = box_to_insets(box)
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_cropped.pdf"))
        crop_pdf(input_path, out_path, **insets)
        return [out_path]
```
(`render_page_thumbnail`/`QPixmap` are imported locally inside `on_files_changed`
rather than at module scope purely to keep this diff's top-of-file import
block minimal — the implementer may hoist them to the top of the file
alongside the other imports instead if that reads more naturally; either
placement is fine, this is a style choice, not a functional requirement.)

- [ ] **Step 6: Register `CropDialog` in `app/main.py`**

Change the import line (currently line 8):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog
```
to:
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog
```
Add this line directly after `window.add_tool("Edit", "Add page numbers", AddPageNumbersDialog)` (currently line 22):
```python
    window.add_tool("Edit", "Crop PDF", CropDialog)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (9 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as before plus 9 (some pre-existing, unrelated
`tests/test_ocr.py` flakiness has occasionally been observed on this machine
in past sessions — if you see failures ONLY there, re-run that file alone
once to confirm; it's a known, pre-existing, unrelated issue, not something
to fix here).

- [ ] **Step 8: Commit**

```bash
git add app/ui/dialogs/base.py app/ui/widgets.py app/ui/dialogs/edit_dialogs.py app/main.py tests/test_ui_desktop.py
git commit -m "feat: add a shared rectangle-selection widget and a Crop PDF dialog to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 2: `RedactDialog`

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (add `RedactDialog`)
- Modify: `app/main.py` (import line, registration line)
- Test: `tests/test_ui_desktop.py` (append to Task 1's file)

**Interfaces:**
- Consumes: `RectangleOverlayWidget(multi=True)`, `.set_boxes`/`.boxes`, `box_to_insets`/`insets_to_box` from Task 1's `app/ui/widgets.py`, unchanged.
- Produces: nothing consumed by any other task (this is the last task in the plan).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_desktop.py`:
```python
def test_redact_dialog_page_switch_accumulates_and_restores_boxes(tmp_path):
    from app.ui.dialogs.edit_dialogs import RedactDialog

    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 72), "PAGE ONE SECRET")
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 72), "PAGE TWO SECRET")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = RedactDialog()
    dlg.on_files_changed([str(input_path)])
    assert dlg.page_spin.maximum() == 2

    w, h = dlg.overlay.width(), dlg.overlay.height()

    def draw_box():
        QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
        QTest.mouseMove(dlg.overlay, QPoint(int(w * 0.6), int(h * 0.15)))
        QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    # Page 1: draw a box.
    draw_box()
    assert len(dlg.overlay.boxes) == 1

    # Switch to page 2: starts empty, draw a box there too.
    dlg.page_spin.setValue(2)
    assert dlg.overlay.boxes == []
    draw_box()
    assert len(dlg.overlay.boxes) == 1

    # Switch back to page 1: its earlier box must still be there.
    dlg.page_spin.setValue(1)
    assert len(dlg.overlay.boxes) == 1

    # Remove page 1's box via its marker.
    marker = dlg.overlay._marker_rect(dlg.overlay.boxes[0])
    click = marker.center()
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert dlg.overlay.boxes == []

    # gather_params must flush whatever page is CURRENTLY displayed (page 1,
    # now empty) and report only page 2's surviving box.
    params = dlg.gather_params()
    assert params["redactions"] == [{"page": 2, "top": 0.05, "left": pytest.approx(0.09905660377358491), "right": pytest.approx(0.40094339622641506), "bottom": 0.85}]

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    text_p1 = result[0].get_text()
    text_p2 = result[1].get_text()
    result.close()
    assert "PAGE ONE SECRET" in text_p1  # page 1's box was removed
    assert "PAGE TWO SECRET" not in text_p2  # page 2's box was kept
```
Add `import pytest` to the top of `tests/test_ui_desktop.py` if Task 1
didn't already need it (check the current top of the file — it's needed
here for `pytest.approx`).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_desktop.py -k redact_dialog -v`
Expected: FAIL — `ImportError`, `RedactDialog` doesn't exist yet.

- [ ] **Step 3: Implement `RedactDialog`**

Add to `app/ui/dialogs/edit_dialogs.py`'s imports (merge into the existing lines):
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QLineEdit, QSlider, QSpinBox
from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf, redact_pdf, render_page_thumbnail, get_page_count
from app.ui.widgets import RectangleOverlayWidget, box_to_insets, insets_to_box
```
Add this class at the end of the file, after `CropDialog`:
```python
class RedactDialog(ToolDialog):
    title = "Redact PDF"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        page_row = QHBoxLayout()
        page_row.addWidget(QLabel("Page:"))
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._load_current_page)
        page_row.addWidget(self.page_spin)
        layout.addLayout(page_row)
        layout.addWidget(QLabel("Drag to mark an area to redact; click the × on a box to remove it:"))
        self.overlay = RectangleOverlayWidget(multi=True)
        layout.addWidget(self.overlay)
        self._all_redactions: list[dict] = []
        self._current_page: int | None = None
        self._input_path: str | None = None

    def on_files_changed(self, paths: list[str]) -> None:
        self._all_redactions = []
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
        self._load_current_page()

    def _flush_current_page(self) -> None:
        if self._current_page is None:
            return
        self._all_redactions = [r for r in self._all_redactions if r["page"] != self._current_page]
        self._all_redactions.extend(
            {"page": self._current_page, **box_to_insets(b)} for b in self.overlay.boxes
        )

    def _load_current_page(self) -> None:
        if self._input_path is None:
            return
        self._flush_current_page()
        page_num = self.page_spin.value()
        self._current_page = page_num
        try:
            thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=600)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_pixmap(pixmap)
        page_boxes = [insets_to_box(r) for r in self._all_redactions if r["page"] == page_num]
        self.overlay.set_boxes(page_boxes)

    def gather_params(self) -> dict:
        self._flush_current_page()
        return {"redactions": list(self._all_redactions)}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_redacted.pdf"))
        redact_pdf(input_path, out_path, params["redactions"])
        return [out_path]
```
Add `from PySide6.QtGui import QPixmap` to the file's imports if not already
present from Task 1's `CropDialog` work (check first — if Task 1's
implementer hoisted it to module scope per that task's optional note, it's
already there and this is a no-op).
`redact_pdf` already raises `PDFError("Select at least one area to redact.")`
for an empty list — no extra dialog-side check needed, matching `crop_pdf`'s
different situation in `CropDialog` (which DOES need one, since `crop_pdf`'s
signature has no way to express "nothing selected").

- [ ] **Step 4: Register `RedactDialog` in `app/main.py`**

Change the import line (now, after Task 1, reading):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog
```
to:
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog, RedactDialog
```
Add this line directly after `window.add_tool("Edit", "Crop PDF", CropDialog)`:
```python
    window.add_tool("Edit", "Redact PDF", RedactDialog)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (10 tests — Task 1's 9 plus this task's 1).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 1 plus 1.

- [ ] **Step 6: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/main.py tests/test_ui_desktop.py
git commit -m "feat: add a Redact PDF dialog to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

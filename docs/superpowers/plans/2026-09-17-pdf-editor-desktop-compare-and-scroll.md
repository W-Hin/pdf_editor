# Desktop App: Compare PDF + Continuous-Scroll Retrofit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Compare PDF dialog (two-file, page-by-page text + visual diff) to the desktop app, and retrofit Crop/Redact/Sign from one-page-at-a-time navigation to continuous scroll of all pages.

**Architecture:** Two small, independent widget-layer additions (`DiffPreviewWidget`, a read-only diff-box display; an `interactive` flag + `box_changed` `Signal` on the existing `RectangleOverlayWidget`) land first, followed by three independent dialog retrofits (Crop, Redact, Sign) that consume them, followed by the new `CompareDialog` last.

**Tech Stack:** Python, PySide6, PySide6.QtTest, pytest, PyMuPDF (fitz), numpy (already a `compare_pdf.py` dependency, unchanged).

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task in this plan is `feat:` or `refactor:` — none carry the trailer.
- Real automated pytest tests using `PySide6.QtTest`'s synthetic mouse events, appended to/modified in the existing `tests/test_ui_desktop.py` — not a manual checklist, not a second test file.
- Compare has no core-level "exactly 2 files" validation to lean on (unlike every prior dialog's "let core validate emptiness" pattern) — `CompareDialog.run_operation` needs its own `PDFError("Select exactly 2 files to compare.")`.
- `CompareDialog` produces no output file: `run_operation` returns `([], "Compared N page(s).")`. `ToolDialog`'s "Show in folder" button cannot be hidden from a subclass (it's created in `__init__` AFTER `build_preview`/`build_options` run) — it stays visible but harmlessly no-ops, since `_open_output_folder` already guards on `self._output_paths` being non-empty.
- Text diffs for every page are computed eagerly (cheap: pure string diffing). Visual diffs (`render_page_image` ×2 + `diff_page_visual`) are computed lazily, only for the page currently shown by the spinner.
- Crop's fundamental model is unchanged: one shared rectangle applies to every page. Only its *display* becomes multi-page (a read-only mirror per non-interactive page).
- Tasks 4 and 5 **delete** their dialog's existing page-switch test (`test_redact_dialog_page_switch_accumulates_and_restores_boxes`, `test_sign_dialog_page_switch_accumulates_and_restores_placements`) and replace it with a new test matching the new architecture — the old test's assertions (`dlg.page_spin`, a single `dlg.overlay`) no longer apply once the retrofit lands. Task 5 additionally **modifies** two other existing tests that reference the old single `dlg.overlay` (see Task 5's Step 1).

---

### Task 1: `DiffPreviewWidget`

**Files:**
- Modify: `app/ui/widgets.py` (add the new class)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: nothing from another task.
- Produces: `DiffPreviewWidget()` with `.set_pixmap(pixmap) -> None`, `.set_boxes(boxes: list[dict]) -> None` (each `{"x0","y0","x1","y1"}` fraction dict, same shape `RectangleOverlayWidget` uses), `.pixmap`, `.boxes`. Task 6's `CompareDialog` uses all of these.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`. Add `DiffPreviewWidget` to the existing `from app.ui.widgets import ...` line:
```python
def test_diff_preview_widget_paints_pixmap_and_boxes():
    widget = DiffPreviewWidget()
    widget.set_pixmap(QPixmap(200, 100))
    widget.set_boxes([{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}])
    assert widget.pixmap.size() == QPixmap(200, 100).size()
    assert widget.boxes == [{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}]


def test_diff_preview_widget_ignores_all_mouse_input():
    widget = DiffPreviewWidget()
    widget.set_pixmap(QPixmap(200, 100))
    widget.set_boxes([{"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5}])
    before_boxes = list(widget.boxes)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert widget.boxes == before_boxes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k diff_preview_widget -v`
Expected: FAIL — `DiffPreviewWidget` doesn't exist yet.

- [ ] **Step 3: Implement `DiffPreviewWidget`**

Add to `app/ui/widgets.py`, after `FormFieldsWidget` at the end of the file:
```python
class DiffPreviewWidget(QWidget):
    """A read-only page-preview QPixmap with highlight boxes drawn on top -
    used by CompareDialog to show computed visual-diff regions. Unlike
    RectangleOverlayWidget, these boxes are Compare's own computed output,
    never the user's own draggable/removable annotations, so this widget
    has NO mouse event handling at all - reusing RectangleOverlayWidget's
    box-drawing code here would be actively wrong, since a click could
    accidentally "remove" a diff finding that was never a real annotation
    to remove."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap = None
        self.boxes: list[dict] = []

    def set_pixmap(self, pixmap) -> None:
        self.pixmap = pixmap
        self.setFixedSize(pixmap.size())
        self.update()

    def set_boxes(self, boxes: list[dict]) -> None:
        self.boxes = list(boxes)
        self.update()

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.pixmap is not None:
            painter.drawPixmap(0, 0, self.pixmap)
        for box in self.boxes:
            x0_px, y0_px = box["x0"] * self.width(), box["y0"] * self.height()
            x1_px, y1_px = box["x1"] * self.width(), box["y1"] * self.height()
            rect = QRect(int(x0_px), int(y0_px), int(x1_px - x0_px), int(y1_px - y0_px))
            painter.setPen(QPen(QColor(220, 40, 40), 2))
            painter.setBrush(QColor(220, 40, 40, 60))
            painter.drawRect(rect)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k diff_preview_widget -v`
Expected: PASS (2 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as before plus 2.

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets.py tests/test_ui_desktop.py
git commit -m "feat: add a read-only diff-box preview widget"
```

No trailer — `feat:`, not `fix:`.

---

### Task 2: `RectangleOverlayWidget` additions (`interactive` flag + `box_changed` signal)

**Files:**
- Modify: `app/ui/widgets.py` (`RectangleOverlayWidget`)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: nothing from another task.
- Produces: `RectangleOverlayWidget(multi: bool = False, interactive: bool = True)` (the new `interactive` parameter, default preserves every existing caller's behavior unchanged) and a `box_changed` `Signal()` emitted at the end of a successful drag (one that clears the existing min-drag-fraction threshold). Task 3's `CropDialog` uses both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def test_box_changed_fires_exactly_once_on_a_successful_drag():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    calls = []
    widget.box_changed.connect(lambda: calls.append(1))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert len(calls) == 1


def test_box_changed_does_not_fire_on_a_too_small_drag():
    widget = RectangleOverlayWidget(multi=False)
    widget.set_pixmap(QPixmap(200, 100))
    calls = []
    widget.box_changed.connect(lambda: calls.append(1))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(21, 11))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(21, 11))
    assert calls == []


def test_interactive_false_blocks_dragging_from_creating_a_box():
    widget = RectangleOverlayWidget(multi=False, interactive=False)
    widget.set_pixmap(QPixmap(200, 100))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, QPoint(20, 10))
    QTest.mouseMove(widget, QPoint(150, 80))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(150, 80))
    assert widget.boxes == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "box_changed or interactive_false" -v`
Expected: FAIL — `RectangleOverlayWidget` has no `interactive` parameter or `box_changed` signal yet.

- [ ] **Step 3: Implement the additions**

Add `Signal` to the existing `from PySide6.QtCore import QPoint, QRect, Qt` line in `app/ui/widgets.py` (making it `from PySide6.QtCore import QPoint, QRect, Qt, Signal`). Modify `RectangleOverlayWidget`:
```python
class RectangleOverlayWidget(QWidget):
    """Displays a page-preview QPixmap with drag-to-draw rectangle(s) on top,
    in page-fraction (0-1) coordinates - mirrors CropSelector.jsx's (multi=False)
    or RedactSelector.jsx's (multi=True) exact interaction model.

    multi=False: at most one box, replaced outright by each new drag.
    multi=True: any number of boxes; each gets a small removable marker at its
    top-right corner - clicking one removes that box instead of starting a drag.
    interactive=False: mouse events are entirely ignored (used for CropDialog's
    read-only per-page mirrors, which only ever display a box set externally
    via set_boxes - never the user's own drag).
    """

    box_changed = Signal()

    def __init__(self, multi: bool = False, interactive: bool = True, parent=None):
        super().__init__(parent)
        self.multi = multi
        self.interactive = interactive
        self.pixmap = None
        self.boxes: list[dict] = []
        self._drag_start: tuple[float, float] | None = None
        self._drag_current: tuple[float, float] | None = None
```
Add an early return to the top of all three mouse handlers:
```python
    def mousePressEvent(self, e) -> None:
        if not self.interactive:
            return
        pos = e.position().toPoint()
        ...  # unchanged below
```
```python
    def mouseMoveEvent(self, e) -> None:
        if not self.interactive:
            return
        if self._drag_start is None:
        ...  # unchanged below
```
```python
    def mouseReleaseEvent(self, e) -> None:
        if not self.interactive:
            return
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
        self.box_changed.emit()
```
(`mousePressEvent`'s and `mouseMoveEvent`'s own bodies are otherwise unchanged from the current file — only the two-line `if not self.interactive: return` guard is new at the top of each. `mouseReleaseEvent` additionally gains the `self.box_changed.emit()` call at its very end, after the existing `self.update()`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "box_changed or interactive_false" -v`
Expected: PASS (3 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 1 plus 3 — including every pre-existing `RectangleOverlayWidget` test (`test_single_mode_drag_creates_one_box`, etc.), which must still pass unmodified since `interactive` defaults to `True`.

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets.py tests/test_ui_desktop.py
git commit -m "feat: add an interactive flag and a box_changed signal to RectangleOverlayWidget"
```

No trailer — `feat:`, not `fix:`.

---

### Task 3: `CropDialog` retrofit (continuous-scroll mirrors)

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (`CropDialog`)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `RectangleOverlayWidget`'s `interactive` flag and `box_changed` signal (Task 2).
- Produces: nothing consumed by another task. `self.overlay` (the single interactive page-1 widget) is unchanged in name/role — `CropDialog`'s existing tests (`test_crop_dialog_offscreen_end_to_end`, `test_crop_dialog_raises_when_no_box_drawn`) keep passing unmodified.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_desktop.py`:
```python
def test_crop_dialog_drag_propagates_the_box_to_every_read_only_mirror(tmp_path):
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    for i in range(3):
        doc.new_page(width=595, height=842).insert_text((72, 72), f"PAGE {i + 1}")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(input_path)])
    assert len(dlg._mirrors) == 2  # pages 2 and 3

    w, h = dlg.overlay.width(), dlg.overlay.height()
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
    QTest.mouseMove(dlg.overlay, QPoint(int(w * 0.6), int(h * 0.15)))
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    box = dlg.overlay.single_box()
    assert box is not None
    for mirror in dlg._mirrors:
        assert mirror.single_box() == box
        # Mirrors must ignore direct interaction too.
        QTest.mousePress(mirror, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        QTest.mouseRelease(mirror, Qt.LeftButton, Qt.NoModifier, QPoint(5, 5))
        assert mirror.single_box() == box  # unchanged by the click


def test_crop_dialog_rebuilds_mirrors_on_file_change(tmp_path):
    from app.ui.dialogs.edit_dialogs import CropDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    single_page_path = tmp_path / "single.pdf"
    doc.save(str(single_page_path))
    doc.close()

    doc2 = fitz.open()
    for _ in range(3):
        doc2.new_page(width=595, height=842)
    multi_page_path = tmp_path / "multi.pdf"
    doc2.save(str(multi_page_path))
    doc2.close()

    dlg = CropDialog()
    dlg.on_files_changed([str(multi_page_path)])
    assert len(dlg._mirrors) == 2

    dlg.on_files_changed([str(single_page_path)])
    assert dlg._mirrors == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k crop_dialog -v`
Expected: the 2 new tests FAIL (`dlg._mirrors` doesn't exist yet); the 2 pre-existing `CropDialog` tests still PASS.

- [ ] **Step 3: Implement the retrofit**

Add `QScrollArea` to the existing `from PySide6.QtWidgets import ...` line in `app/ui/dialogs/edit_dialogs.py`. Replace `CropDialog` entirely with:
```python
class CropDialog(ToolDialog):
    title = "Crop PDF"
    dialog_size = (650, 750)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        instruction = QLabel(
            "Drag to select the area to KEEP on page 1 (applies to every page - "
            "other pages below show a live preview of the same selection):"
        )
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.overlay = RectangleOverlayWidget(multi=False)
        self.overlay.box_changed.connect(self._propagate_box_to_mirrors)
        layout.addWidget(self.overlay)

        self._mirror_scroll = QScrollArea()
        self._mirror_scroll.setWidgetResizable(True)
        self._mirror_container = QWidget()
        self._mirror_layout = QVBoxLayout(self._mirror_container)
        self._mirror_scroll.setWidget(self._mirror_container)
        layout.addWidget(self._mirror_scroll)
        self._mirrors: list[RectangleOverlayWidget] = []

    def _propagate_box_to_mirrors(self) -> None:
        box = self.overlay.single_box()
        for mirror in self._mirrors:
            mirror.set_boxes([box] if box else [])

    def on_files_changed(self, paths: list[str]) -> None:
        self.overlay.set_boxes([])
        while self._mirror_layout.count():
            item = self._mirror_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._mirrors = []
        if not paths:
            return
        try:
            count = get_page_count(paths[0])
            thumb_bytes = render_page_thumbnail(paths[0], 1, max_size=450)
        except PDFError:
            return
        pixmap = QPixmap()
        pixmap.loadFromData(thumb_bytes)
        self.overlay.set_pixmap(pixmap)
        for page_num in range(2, count + 1):
            try:
                mirror_thumb = render_page_thumbnail(paths[0], page_num, max_size=450)
            except PDFError:
                continue
            mirror_pixmap = QPixmap()
            mirror_pixmap.loadFromData(mirror_thumb)
            mirror = RectangleOverlayWidget(multi=False, interactive=False)
            mirror.set_pixmap(mirror_pixmap)
            self._mirror_layout.addWidget(mirror)
            self._mirrors.append(mirror)

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
(`gather_params`/`run_operation` are byte-for-byte identical to the current file — only `build_preview`/`on_files_changed` change, and a new `_propagate_box_to_mirrors` method is added.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k crop_dialog -v`
Expected: PASS (all 4 — the 2 new plus the 2 pre-existing, unmodified).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 2 plus 2.

- [ ] **Step 5: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py tests/test_ui_desktop.py
git commit -m "refactor: show CropDialog's shared crop selection mirrored across every page"
```

No trailer — `refactor:`, not `fix:`.

---

### Task 4: `RedactDialog` retrofit (continuous scroll, N independent widgets)

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (`RedactDialog`)
- Test: `tests/test_ui_desktop.py` (modify — delete one test, add one)

**Interfaces:**
- Consumes: `RectangleOverlayWidget` unchanged (default `interactive=True`, no Task 2 dependency beyond the constructor still accepting `multi=True` as before).
- Produces: `self._page_widgets: list[RectangleOverlayWidget]`, one per page, each independently holding that page's own `.boxes`. Nothing consumed by another task.

- [ ] **Step 1: Delete the stale test, write the replacement**

In `tests/test_ui_desktop.py`, **delete** `test_redact_dialog_page_switch_accumulates_and_restores_boxes` in full (it asserts against `dlg.page_spin` and a single `dlg.overlay`, both gone after this retrofit). Add this replacement in its place:
```python
def test_redact_dialog_each_page_holds_its_own_boxes_independently(tmp_path):
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
    assert len(dlg._page_widgets) == 2

    def draw_box(overlay):
        w, h = overlay.width(), overlay.height()
        QTest.mousePress(overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.1), int(h * 0.05)))
        QTest.mouseMove(overlay, QPoint(int(w * 0.6), int(h * 0.15)))
        QTest.mouseRelease(overlay, Qt.LeftButton, Qt.NoModifier, QPoint(int(w * 0.6), int(h * 0.15)))

    draw_box(dlg._page_widgets[1])  # page 2 only

    params = dlg.gather_params()
    # Same drag, same page dimensions as the deleted test - the exact expected
    # fraction values were already empirically verified there and reused here.
    assert params["redactions"] == [{
        "page": 2,
        "top": pytest.approx(0.04888888888888889),
        "left": pytest.approx(0.09748427672955975),
        "right": pytest.approx(0.4025157232704403),
        "bottom": pytest.approx(0.8511111111111112),
    }]

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    text_p1 = result[0].get_text()
    text_p2 = result[1].get_text()
    result.close()
    assert "PAGE ONE SECRET" in text_p1  # untouched
    assert "PAGE TWO SECRET" not in text_p2  # redacted

    # Removing page 2's box via its own widget's marker works independently
    # of every other page's widget.
    page2_widget = dlg._page_widgets[1]
    marker = page2_widget._marker_rect(page2_widget.boxes[0])
    click = marker.center()
    QTest.mousePress(page2_widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page2_widget, Qt.LeftButton, Qt.NoModifier, click)
    assert page2_widget.boxes == []
    assert dlg.gather_params()["redactions"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k redact_dialog -v`
Expected: FAIL — `dlg._page_widgets` doesn't exist yet (the old test is gone, so there's nothing else to check here).

- [ ] **Step 3: Implement the retrofit**

Replace `RedactDialog` entirely with:
```python
class RedactDialog(ToolDialog):
    title = "Redact PDF"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        instruction = QLabel("Drag to mark an area to redact; click the × on a box to remove it:")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)
        self._page_widgets: list[RectangleOverlayWidget] = []

    def on_files_changed(self, paths: list[str]) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets = []
        if not paths:
            return
        try:
            count = get_page_count(paths[0])
        except PDFError:
            return
        for page_num in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(paths[0], page_num, max_size=450)
            except PDFError:
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            overlay = RectangleOverlayWidget(multi=True)
            overlay.set_pixmap(pixmap)
            self._container_layout.addWidget(overlay)
            self._page_widgets.append(overlay)

    def gather_params(self) -> dict:
        redactions = []
        for page_num, overlay in enumerate(self._page_widgets, start=1):
            redactions.extend({"page": page_num, **box_to_insets(b)} for b in overlay.boxes)
        return {"redactions": redactions}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_redacted.pdf"))
        redact_pdf(input_path, out_path, params["redactions"])
        return [out_path]
```
(`run_operation` is byte-for-byte identical to the current file. `page_spin`, `_all_redactions`, `_current_page`, `_input_path`, `_flush_current_page`, `_load_current_page` are all removed — there's nothing left to flush, since each page's widget permanently holds its own boxes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k redact_dialog -v`
Expected: PASS (1 test).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 3 plus 1 minus 1 (one deleted, one added — net zero change in count, but confirm no leftover reference to the deleted test's name anywhere).

- [ ] **Step 5: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py tests/test_ui_desktop.py
git commit -m "refactor: show RedactDialog's pages in a continuous scroll, each holding its own boxes"
```

No trailer — `refactor:`, not `fix:`.

---

### Task 5: `SignDialog` retrofit (continuous scroll, N independent widgets)

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (`SignDialog`)
- Test: `tests/test_ui_desktop.py` (modify — delete one test, add one, update two others)

**Interfaces:**
- Consumes: `ImagePlacementWidget` unchanged, no dependency on Tasks 1-4.
- Produces: `self._page_widgets: list[ImagePlacementWidget]`, one per page, each independently holding that page's own `.placements`. Nothing consumed by another task.

- [ ] **Step 1: Update the test file**

In `tests/test_ui_desktop.py`, make three changes:

**(a) Delete** `test_sign_dialog_page_switch_accumulates_and_restores_placements` in full (it asserts against `dlg.page_spin` and a single `dlg.overlay`, both gone). Add this replacement in its place:
```python
def test_sign_dialog_each_page_holds_its_own_placements_independently(tmp_path):
    from app.ui.dialogs.edit_dialogs import SignDialog

    doc = fitz.open()
    for _ in range(3):
        doc.new_page(width=595, height=842)
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
    assert len(dlg._page_widgets) == 3

    def place(widget):
        w, h = widget.width(), widget.height()
        click = QPoint(int(w * 0.6), int(h * 0.7))
        QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
        QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)

    place(dlg._page_widgets[0])  # page 1
    place(dlg._page_widgets[2])  # page 3
    assert len(dlg._page_widgets[0].placements) == 1
    assert len(dlg._page_widgets[1].placements) == 0
    assert len(dlg._page_widgets[2].placements) == 1

    params = dlg.gather_params()
    assert sorted(p["page"] for p in params["placements"]) == [1, 3]

    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    images_p1 = result[0].get_images()
    images_p2 = result[1].get_images()
    images_p3 = result[2].get_images()
    result.close()
    assert len(images_p1) == 1
    assert len(images_p2) == 0
    assert len(images_p3) == 1
```

**(b)** In `test_sign_dialog_places_a_signature_and_exports_it`, replace:
```python
    w, h = dlg.overlay.width(), dlg.overlay.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert len(dlg.overlay.placements) == 1
```
with:
```python
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    assert len(page1.placements) == 1
```
(the rest of that test is unchanged — it already reads `params["placements"]`/`params["signature_path"]` from `gather_params()`, not from `dlg.overlay` directly).

**(c)** In `test_sign_dialog_use_different_signature_clears_the_overlays_placements`, replace:
```python
    w, h = dlg.overlay.width(), dlg.overlay.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(dlg.overlay, Qt.LeftButton, Qt.NoModifier, click)
    assert len(dlg.overlay.placements) == 1

    # Switching to a different signature must also clear the overlay's
    # displayed placements, not just the dialog's own bookkeeping - the
    # widget would otherwise keep rendering stale boxes from the old
    # signature.
    dlg._use_different_signature()
    assert dlg.overlay.placements == []
```
with:
```python
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.6), int(h * 0.7))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    assert len(page1.placements) == 1

    # Switching to a different signature must discard every per-page widget
    # entirely, not just clear their placements - there's no valid page
    # widget to show until a new signature + file combination exists again.
    dlg._use_different_signature()
    assert dlg._page_widgets == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k sign_dialog -v`
Expected: FAIL — `dlg._page_widgets` doesn't exist yet.

- [ ] **Step 3: Implement the retrofit**

Replace `SignDialog` entirely with:
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
        instruction = QLabel("Click to place your signature; drag to move it, its corner handle to resize, or click the × to remove it:")
        instruction.setWordWrap(True)
        placement_layout.addWidget(instruction)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        placement_layout.addWidget(self._scroll)
        different_btn = QPushButton("Use a different signature")
        different_btn.clicked.connect(self._use_different_signature)
        placement_layout.addWidget(different_btn)
        self.placement_panel.setVisible(False)
        layout.addWidget(self.placement_panel)

        self.signature_path: str | None = None
        self._input_path: str | None = None
        self._page_widgets: list[ImagePlacementWidget] = []

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
        self.source_panel.setVisible(False)
        self.placement_panel.setVisible(True)
        self._rebuild_page_widgets()

    def _use_different_signature(self) -> None:
        self.signature_path = None
        self.pad.clear()
        self.pad_panel.setVisible(False)
        self.placement_panel.setVisible(False)
        self.source_panel.setVisible(True)
        self._clear_page_widgets()

    def on_files_changed(self, paths: list[str]) -> None:
        self._input_path = paths[0] if paths else None
        self._rebuild_page_widgets()

    def _clear_page_widgets(self) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets = []

    def _rebuild_page_widgets(self) -> None:
        self._clear_page_widgets()
        if self._input_path is None or self.signature_path is None:
            return
        try:
            count = get_page_count(self._input_path)
        except PDFError:
            return
        sig_pixmap = QPixmap(self.signature_path)
        for page_num in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=450)
            except PDFError:
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            widget = ImagePlacementWidget()
            widget.set_page_pixmap(pixmap)
            widget.set_signature_pixmap(sig_pixmap)
            self._container_layout.addWidget(widget)
            self._page_widgets.append(widget)

    def gather_params(self) -> dict:
        placements = []
        for page_num, widget in enumerate(self._page_widgets, start=1):
            placements.extend({"page": page_num, **p} for p in widget.placements)
        return {"signature_path": self.signature_path, "placements": placements}

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
(`run_operation` is byte-for-byte identical to the current file. `page_spin`, `_all_placements`, `_current_page`, `_flush_current_page`, `_load_current_page` are removed, replaced by `_page_widgets`/`_rebuild_page_widgets`/`_clear_page_widgets`. Both `use_signature_file` and `on_files_changed` call `_rebuild_page_widgets`, which guards on both `_input_path` and `signature_path` being set — the same dual-trigger shape the old `_load_current_page` had, just without a page spinner to also react to.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k sign_dialog -v`
Expected: PASS (4 tests: the 1 new, plus the 3 modified-in-place).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 4 (one test deleted and replaced net zero, two others modified in place with no count change).

- [ ] **Step 5: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py tests/test_ui_desktop.py
git commit -m "refactor: show SignDialog's pages in a continuous scroll, each holding its own placements"
```

No trailer — `refactor:`, not `fix:`.

---

### Task 6: `CompareDialog`

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (add the new class)
- Modify: `app/main.py` (import line, registration line)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `DiffPreviewWidget` (Task 1), unchanged.
- Produces: nothing consumed by another task (this is the last task in the plan).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def test_compare_dialog_eager_text_diff_and_lazy_visual_diff(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Hello World")
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Second page A")
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Third page only in A")
    path_a = tmp_path / "compare_a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Hello World CHANGED")
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Second page A")
    path_b = tmp_path / "compare_b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    assert dlg.page_spin.maximum() == 3

    # Text diffs for ALL pages are computed eagerly, before the spinner ever
    # moves past page 1 - confirmed by checking page 3's (never-visited via
    # the spinner) already-computed state.
    assert dlg._pages[0]["has_counterpart"] is True
    assert any(op["op"] in ("delete", "insert") for op in dlg._pages[0]["text_diff"])
    assert dlg._pages[1]["has_counterpart"] is True
    assert all(op["op"] == "equal" for op in dlg._pages[1]["text_diff"])
    assert dlg._pages[2]["has_counterpart"] is False  # page 3 only exists in A

    # on_files_changed shows page 1 immediately (matching every other
    # dialog's "show page 1 right after file load" convention) - its own
    # text genuinely differs between A and B, so its visual diff has at
    # least one box.
    assert dlg.visual_a.pixmap is not None
    assert len(dlg.visual_a.boxes) >= 1

    # The visual diff for any OTHER page is only ever computed when the
    # spinner actually reaches it - moving to page 2 (identical text in both
    # documents) must produce zero diff boxes, proving this specific call
    # (not some pre-computed value) is what populated the widgets.
    dlg.page_spin.setValue(2)
    assert dlg.visual_a.pixmap is not None
    assert dlg.visual_a.boxes == []


def test_compare_dialog_run_operation_requires_exactly_two_files(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import CompareDialog

    dlg = CompareDialog()
    for file_count in (0, 1, 3):
        try:
            dlg.run_operation([], {"file_count": file_count})
            assert False, f"expected PDFError for file_count={file_count}"
        except PDFError as exc:
            assert "exactly 2" in str(exc)


def test_compare_dialog_run_operation_returns_no_output_files(tmp_path):
    from app.ui.dialogs.edit_dialogs import CompareDialog

    doc_a = fitz.open()
    doc_a.new_page(width=595, height=842).insert_text((72, 72), "Same text")
    path_a = tmp_path / "a.pdf"
    doc_a.save(str(path_a))
    doc_a.close()

    doc_b = fitz.open()
    doc_b.new_page(width=595, height=842).insert_text((72, 72), "Same text")
    path_b = tmp_path / "b.pdf"
    doc_b.save(str(path_b))
    doc_b.close()

    dlg = CompareDialog()
    dlg.on_files_changed([str(path_a), str(path_b)])
    params = dlg.gather_params()
    assert params == {"file_count": 2}
    output_paths, message = dlg.run_operation([str(path_a), str(path_b)], params)
    assert output_paths == []
    assert "1 page" in message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k compare_dialog -v`
Expected: FAIL — `CompareDialog` doesn't exist yet.

- [ ] **Step 3: Implement `CompareDialog`**

Add `QTextEdit` to the existing `from PySide6.QtWidgets import ...` line in `app/ui/dialogs/edit_dialogs.py`. Add `DiffPreviewWidget` to the existing `from app.ui.widgets import ...` line. Add a new import line: `from app.core.compare_pdf import extract_page_texts, diff_page_text, render_page_image, diff_page_visual`. Add this class at the end of the file, after `SignDialog` (before or after `FillFormDialog` — position doesn't matter, append after the last class):
```python
class CompareDialog(ToolDialog):
    title = "Compare PDF"
    dialog_size = (900, 780)
    allow_multiple_files = True

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

        self.status_label_compare = QLabel(
            "Add exactly 2 files to compare (the first is treated as the original, the second as the changed version)."
        )
        self.status_label_compare.setWordWrap(True)
        layout.addWidget(self.status_label_compare)

        self.text_diff_view = QTextEdit()
        self.text_diff_view.setReadOnly(True)
        self.text_diff_view.setFixedHeight(150)
        layout.addWidget(self.text_diff_view)

        visual_row = QHBoxLayout()
        self.visual_a = DiffPreviewWidget()
        self.visual_b = DiffPreviewWidget()
        visual_row.addWidget(self.visual_a)
        visual_row.addWidget(self.visual_b)
        layout.addLayout(visual_row)

        self._path_a: str | None = None
        self._path_b: str | None = None
        self._pages: list[dict] = []
        self._page_count_a = 0
        self._page_count_b = 0

    def on_files_changed(self, paths: list[str]) -> None:
        self._pages = []
        self._path_a = None
        self._path_b = None
        self.text_diff_view.clear()
        if len(paths) != 2:
            self.status_label_compare.setText(
                "Add exactly 2 files to compare (the first is treated as the original, the second as the changed version)."
            )
            return
        try:
            texts_a = extract_page_texts(paths[0])
            texts_b = extract_page_texts(paths[1])
        except PDFError:
            return
        self._path_a, self._path_b = paths[0], paths[1]
        self._page_count_a, self._page_count_b = len(texts_a), len(texts_b)
        total_pages = max(self._page_count_a, self._page_count_b)
        for i in range(total_pages):
            has_a = i < self._page_count_a
            has_b = i < self._page_count_b
            if has_a and has_b:
                self._pages.append({"text_diff": diff_page_text(texts_a[i], texts_b[i]), "has_counterpart": True})
            else:
                self._pages.append({"text_diff": [], "has_counterpart": False})
        self.status_label_compare.setText(f"Comparing {total_pages} page(s).")
        self.page_spin.setMaximum(total_pages)
        self.page_spin.setValue(1)
        self._load_current_page()

    def _render_text_diff(self, entries: list[dict]) -> str:
        color_by_op = {"insert": "#c8f7c5", "delete": "#f7c5c5", "equal": "transparent"}
        lines = []
        for entry in entries:
            color = color_by_op.get(entry["op"], "transparent")
            text = entry["text"] or " "
            lines.append(f'<div style="background-color: {color};">{text}</div>')
        return "".join(lines)

    def _load_current_page(self) -> None:
        if self._path_a is None or self._path_b is None or not self._pages:
            return
        page_num = self.page_spin.value()
        page = self._pages[page_num - 1]
        if not page["has_counterpart"]:
            if page_num <= self._page_count_a and page_num > self._page_count_b:
                self.text_diff_view.setHtml("<i>Page removed (only in the first document)</i>")
            else:
                self.text_diff_view.setHtml("<i>Page added (only in the second document)</i>")
            return
        self.text_diff_view.setHtml(self._render_text_diff(page["text_diff"]))
        image_a = render_page_image(self._path_a, page_num, 1800)
        image_b = render_page_image(self._path_b, page_num, 1800)
        pixmap_a, pixmap_b = QPixmap(), QPixmap()
        pixmap_a.loadFromData(image_a)
        pixmap_b.loadFromData(image_b)
        boxes = diff_page_visual(self._path_a, self._path_b, page_num, 1800)
        self.visual_a.set_pixmap(pixmap_a)
        self.visual_a.set_boxes(boxes)
        self.visual_b.set_pixmap(pixmap_b)
        self.visual_b.set_boxes(boxes)

    def gather_params(self) -> dict:
        return {"file_count": len(self.selected_files())}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        if params["file_count"] != 2:
            raise PDFError("Select exactly 2 files to compare.")
        return ([], f"Compared {len(self._pages)} page(s).")
```

- [ ] **Step 4: Register `CompareDialog` in `app/main.py`**

Change the import line (currently ending `..., SignDialog`, and separately `..., FillFormDialog`):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog, RedactDialog, SignDialog, FillFormDialog, CompareDialog
```
Add this line directly after `window.add_tool("Edit", "PDF Forms", FillFormDialog)`:
```python
    window.add_tool("Edit", "Compare PDF", CompareDialog)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (all tests in the file, including this task's 3 new ones).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 5 plus 3.

- [ ] **Step 6: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/main.py tests/test_ui_desktop.py
git commit -m "feat: add a Compare PDF dialog to the desktop app"
```

No trailer — `feat:`, not `fix:`.

# Desktop App: Edit PDF, Phase 6B (Vector Elements) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three new Edit PDF element types to the desktop app — `shape` (rectangle/ellipse/line/arrow), `stroke` (freehand draw), and `highlight` — reusing Phase 6A's `EditElementsModel`/`EditPageWidget`/`EditPdfDialog` foundation with no new architecture.

**Architecture:** Each new type gets its own `elif` branch woven into `EditPageWidget`'s existing type-dispatched methods (`_element_rect_px`, `_resize_handles`, `mouseMoveEvent`'s move/resize dispatch, `paintEvent`) and `EditElementsModel`'s existing per-type methods (`_shift_for_paste`, `nudge`). Shape/highlight/stroke creation is drag-based (unlike 6A's single-click new_text/image), so this plan also adds one new piece of genuinely new machinery: a shared `EditPageWidget._create_drag` field plus a `_finish_create_drag()` dispatcher, built once in Task 1 and extended by Tasks 2-3 with one `elif` branch each. `app/core/pdf_ops.py` needs zero changes — `_apply_shape`/`_apply_stroke`/`_apply_highlight` and their validators already exist, are already tested, and were confirmed end-to-end during this plan's own verification (a real `edit_pdf()` call with real shape/stroke/highlight elements produced real pixel differences against a blank control page).

**Tech Stack:** PySide6 (`QPainter`, `QPainterPath`, `QPolygon`, `QTest`), pytest.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task in this plan ships new behavior — commits are `feat:` and must **not** carry the trailer.
- Real automated pytest tests using `PySide6.QtTest`'s synthetic mouse/keyboard events, appended to the existing `tests/test_ui_desktop.py` — not a manual checklist, not a second test file.
- `_MIN_DRAG_FRACTION = 0.02` is `app/ui/widgets.py`'s existing minimum-drag threshold for `RectangleOverlayWidget`'s own drag-to-create (Crop/Redact). This plan duplicates the same value as a new local constant in `app/ui/edit_canvas.py`, matching this codebase's established convention (`EditPageWidget._corner_size()` already duplicates `ImagePlacementWidget._corner_size()`'s formula rather than sharing a base class) — confirmed via `web/frontend/src/components/EditPdfCanvas.jsx:244` that the web app uses the identical `0.02` value for the identical purpose across draw/shapes/highlight, so this is a genuine cross-app constant, not a coincidence.
- **The spec's claim that "keyboard nudge needs no type-specific changes at all" is factually wrong and must not be followed.** `EditElementsModel.nudge()` (`app/ui/edit_canvas.py:171-183`) only mutates `new_text`/`image` elements today; for any other type it still calls `self.commit()` (pushing a wasted undo step) and then silently does nothing. Confirmed by reading the current code before writing this plan. Tasks 1-3 each add nudge's real per-type branch — see each task's own Step 3.
- Width presets: `{"thin": 1, "medium": 3, "thick": 6}`, matching `web/frontend/src/components/EditPdfCanvas.jsx`'s own `STROKE_WIDTHS`. `EditPageWidget.width_preset` stores the string key (`"thin"`/`"medium"`/`"thick"`); the numeric point-width is looked up from a new `_WIDTH_PRESETS` module constant only at the moment an element is actually created (`_finish_create_drag`) — the stored element's own `"width"` field is always the resolved number, never the string.
- `shape.filled` is forced to `False` at creation time whenever `shape_type` is `"line"` or `"arrow"`, regardless of the toolbar's filled-checkbox state — confirmed via `web/frontend/src/components/EditPdfCanvas.jsx:740` (`filled: shapeType === "rectangle" || shapeType === "ellipse" ? shapeFilled : false`), not just the spec's prose ("filled only applies to rectangle/ellipse").
- Stroke's jitter-discard rule (confirmed against `web/frontend/src/components/EditPdfCanvas.jsx:677-687`, resolving an ambiguity in the spec's own wording): a captured stroke is discarded only if **both** axes' extent (`max(coord) - min(coord)` across every captured point) are below `_MIN_DRAG_FRACTION` — i.e. it is kept if **either** axis clears the threshold. Also discarded outright if fewer than 2 points were captured at all.
- Shape creation's axis-threshold rule (confirmed against `EditPdfCanvas.jsx:717-726`): `rectangle`/`ellipse` require **both** axes to clear `_MIN_DRAG_FRACTION` (a perfectly horizontal or vertical drag produces an unusable zero-dimension box, which `_validate_shape` would reject at Run time with a confusing error). `line`/`arrow` require only **one** axis to clear it (a perfectly horizontal or vertical line/arrow is a valid, intentional shape).
- Highlight creation requires **both** axes to clear `_MIN_DRAG_FRACTION`, using the sorted (min/max) corners — confirmed against `EditPdfCanvas.jsx:760-770`.
- **New, plan-discovered gap the spec never mentions:** a horizontal or vertical `shape` (a `line`/`arrow` with `y0==y1` or `x0==x1`) has a zero-height or zero-width bounding box. `QRect.contains()` can never match a real click on a zero-dimension rect, so without a fix, a thin shape would be permanently unselectable/unmovable once created (only its marker and resize handle, which have their own fixed-size rects, would remain clickable). Task 1 fixes this by inflating the body-hit-test rect for `shape` elements only, by `max(6, el["width"])` pixels on each side, in `mousePressEvent`'s existing body hit-test loop. Task 2 extends the same inflation to `stroke` (a freehand scribble can be equally thin on one axis).
- Shape's resize handle always drags the raw `x1`,`y1` fields directly (never "whichever corner is visually bottom-right") and always leaves `x0`,`y0` untouched — including when the shape was originally drawn "backwards" (`x0 > x1` and/or `y0 > y1`), matching the spec's explicit "not 'nearest corner' logic" instruction. Verified empirically: a shape created with `x0=0.6,y0=0.6,x1=0.3,y1=0.3` (drawn from bottom-right to top-left) still renders its resize handle at the bounding box's bottom-right pixel position (matching every other element type's handle-placement convention) and dragging it still only ever changes `x1,y1`.
- Highlight's resize handle is drawn at the bounding box's bottom-right pixel position (matching the established convention) and dragging it recomputes only `right`/`bottom`; `top`/`left` never change. Verified empirically including the correct sign of the shift math for a **move** gesture (as opposed to a resize): moving the whole highlight right/down must *increase* `left`/`top` and *decrease* `right`/`bottom` — a sign error here was caught and fixed during this plan's own verification.
- `EditElementsModel.update()`/`.nudge()` mutate element dicts **in place**. Any test that captures a "before" snapshot for comparison must copy it (`dict(el)`) first — this is a 6A-established gotcha, restated here because Tasks 1-3's new tests will hit it again.
- No changes needed to `app/core/pdf_ops.py` — `edit_pdf`, `_apply_shape`/`_validate_shape` (`pdf_ops.py:705`/`564`), `_apply_stroke`/`_validate_stroke` (`pdf_ops.py:667`/`555`), `_apply_highlight`/`_validate_highlight` (`pdf_ops.py:728`/`577`), and `_SHAPE_TYPES` (`pdf_ops.py:537`) are already fully implemented and unchanged — confirmed by reading the current file and by a real end-to-end `edit_pdf()` call during this plan's verification.
- `shape` field shape: `{page, shape, x0, y0, x1, y1, color, width, filled}`, `shape` ∈ `{rectangle, ellipse, line, arrow}`, raw (never normalized) corner points. `stroke` field shape: `{page, points: [{x, y}, ...], color, width}`. `highlight` field shape: `{page, top, left, right, bottom, color}` (inset convention, reusing `app/ui/widgets.py`'s `box_to_insets`/`insets_to_box`).
- `EditPdfDialog.gather_params()`/`run_operation()` (`app/ui/dialogs/edit_dialogs.py`) need **zero changes** for this plan — both are already fully generic over element type (`gather_params` strips only `"id"`; `image_paths` construction already filters on `el["type"] == "image"` and simply won't match the three new types). Confirmed by reading the current code; do not touch these methods in Task 4.

---

### Task 1: `shape` element type

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditElementsModel`/`EditPageWidget` exactly as they exist after Phase 6A (unchanged public surface: `model.add/update/remove/select/commit/undo/redo/copy/cut/paste/reorder/nudge`, `widget.create_mode`, `widget._drag`, `widget._apply_drag`).
- Produces (for Tasks 2-4): a new module constant `_MIN_DRAG_FRACTION = 0.02`; a new module constant `_WIDTH_PRESETS = {"thin": 1, "medium": 3, "thick": 6}`; four new `EditPageWidget` instance attributes set in `__init__` — `self.shape_type = "rectangle"`, `self.color = "#ff0000"`, `self.width_preset = "medium"`, `self.filled = False`; a new `self._create_drag: dict | None = None` field (shape while active: `{"start": (x, y), "current": (x, y), "points": [(x, y), ...]}`); a new `_finish_create_drag(self) -> str | None` method that Tasks 2-3 each add one `elif self.create_mode == "...":` branch to; a new `_paint_create_preview(self, painter)` method that Tasks 2-3 each add one `elif` branch to.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py` (the file already imports `EditElementsModel`, `EditPageWidget`, `QPoint`, `Qt`, `QPixmap`, `QTest`, `pytest` at module level — no new imports needed for this task):

```python
def _shape_element(page=1, shape="rectangle", x0=0.2, y0=0.2, x1=0.5, y1=0.4, color="#ff0000", width=3, filled=False):
    return {"page": page, "type": "shape", "shape": shape, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "color": color, "width": width, "filled": filled}


def test_edit_model_shape_paste_offset_shifts_both_corners_and_clamps_near_edge():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.2, y0=0.2, x1=0.4, y1=0.3))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["x0"] == pytest.approx(0.23)
    assert pasted["x1"] == pytest.approx(0.43)
    assert pasted["y0"] == pytest.approx(0.23)
    assert pasted["y1"] == pytest.approx(0.33)

    el_id2 = model.add(_shape_element(x0=0.9, y0=0.2, x1=0.99, y1=0.3))
    model.select(el_id2)
    model.copy()
    pasted_id2 = model.paste()
    pasted2 = next(e for e in model.elements if e["id"] == pasted_id2)
    # room_x = 1 - max(0.9, 0.99) = 0.01, clamped to 0.01 (not the full 0.03 offset)
    assert pasted2["x1"] == pytest.approx(1.0)
    assert pasted2["x0"] == pytest.approx(0.91)


def test_edit_model_shape_nudge_shifts_both_corners_and_clamps_at_the_page_edge():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.9, y0=0.3, x1=0.98, y1=0.4))
    model.nudge(el_id, 0.5, 0.0)  # far past the right edge
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x1"] == pytest.approx(1.0)
    assert el["x0"] == pytest.approx(0.92)  # bbox width (0.08) preserved
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x0"] == pytest.approx(0.9) and reverted["x1"] == pytest.approx(0.98)


def test_edit_model_shape_nudge_clamps_correctly_even_when_drawn_backwards():
    model = EditElementsModel()
    # x0 > x1: the shape was drawn from bottom-right to top-left.
    el_id = model.add(_shape_element(x0=0.98, y0=0.3, x1=0.9, y1=0.4))
    model.nudge(el_id, 0.5, 0.0)
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x0"] == pytest.approx(1.0)  # x0 is the bbox max here, still clamps correctly
    assert el["x1"] == pytest.approx(0.92)


def test_edit_page_widget_dragging_creates_a_rectangle_shape():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "rectangle"
    widget.color = "#0000ff"
    widget.width_preset = "thick"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.5), int(h * 0.4))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "shape" and el["shape"] == "rectangle"
    assert el["x0"] == pytest.approx(0.2) and el["y0"] == pytest.approx(0.2)
    assert el["x1"] == pytest.approx(0.5) and el["y1"] == pytest.approx(0.4)
    assert el["color"] == "#0000ff" and el["width"] == 6 and el["filled"] is False


def test_edit_page_widget_below_threshold_rectangle_drag_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "rectangle"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.205), int(h * 0.205))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_arrow_only_needs_one_axis_to_clear_the_threshold():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "arrow"
    w, h = widget.width(), widget.height()
    # a horizontal drag: dx is large, dy is a sub-threshold sliver
    start = QPoint(int(w * 0.1), int(h * 0.5))
    end = QPoint(int(w * 0.4), int(h * 0.5005))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    assert model.elements[0]["shape"] == "arrow"


def test_edit_page_widget_arrow_with_both_axes_below_threshold_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "arrow"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.5), int(h * 0.5))
    end = QPoint(int(w * 0.501), int(h * 0.501))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_line_or_arrow_shape_forces_filled_false_at_creation():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "shape"
    widget.shape_type = "line"
    widget.filled = True  # toolbar checkbox happens to be checked
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.1), int(h * 0.1))
    end = QPoint(int(w * 0.4), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements[0]["filled"] is False


def test_edit_page_widget_shape_resize_handle_always_drags_x1_y1_even_when_drawn_backwards():
    model = EditElementsModel()
    el_id = model.add(_shape_element(x0=0.6, y0=0.6, x1=0.3, y1=0.3))  # drawn backwards
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    el = next(e for e in model.elements if e["id"] == el_id)
    handle = widget._resize_handles(el)["corner"]
    center = handle.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(widget, QPoint(center.x() + 20, center.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(center.x() + 20, center.y() + 10))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x0"] == 0.6 and el["y0"] == 0.6  # untouched
    assert el["x1"] == pytest.approx(0.3 + 20 / w)
    assert el["y1"] == pytest.approx(0.3 + 10 / h)
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x1"] == 0.3 and reverted["y1"] == 0.3  # undo restores the pre-resize corner


def test_edit_page_widget_shape_move_shifts_all_four_coordinates():
    model = EditElementsModel()
    el_id = model.add(_shape_element(shape="line", x0=0.3, y0=0.3, x1=0.5, y1=0.3))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    # A horizontal line's bbox has zero height - click must still hit its
    # (margin-inflated) body, not fall through to empty-space handling.
    body = QPoint(int(w * 0.4), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 10, body.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 10, body.y() + 10))
    el = next(e for e in model.elements if e["id"] == el_id)
    dx, dy = 10 / w, 10 / h
    assert el["x0"] == pytest.approx(0.3 + dx) and el["x1"] == pytest.approx(0.5 + dx)
    assert el["y0"] == pytest.approx(0.3 + dy) and el["y1"] == pytest.approx(0.3 + dy)
    assert model.selected_id == el_id


def test_edit_page_widget_clicking_a_shapes_marker_removes_it():
    model = EditElementsModel()
    el_id = model.add(_shape_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    marker = widget._marker_rect(el)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "shape" -v`
Expected: FAIL — `EditPageWidget` doesn't create/move/resize/paint `shape` elements yet, `EditElementsModel` doesn't paste/nudge them yet.

- [ ] **Step 3: Implement `shape` support**

Add these two module-level constants right after the existing ones near the top of `app/ui/edit_canvas.py` (after `_MIN_TEXT_HEIGHT_FRACTION = 0.03`):
```python
_MIN_DRAG_FRACTION = 0.02
_WIDTH_PRESETS = {"thin": 1, "medium": 3, "thick": 6}
```

Add `import math` and `QPolygon` to the file's imports (top of file):
```python
import math
import uuid

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QTextEdit, QWidget
```

In `EditElementsModel._shift_for_paste` (`app/ui/edit_canvas.py:106-121`), add a `shape` branch:
```python
    def _shift_for_paste(self, el: dict) -> dict:
        """Per-type paste-offset math, mirroring the web app's own shift()
        helper: translate the WHOLE element by the same delta on each axis
        (never clamp each coordinate independently - that would distort a
        near-edge element), clamped to [0, _PASTE_OFFSET] per axis. Phase
        6B/6C add their own type branches here later; nothing below needs
        revisiting when they do."""
        shifted = dict(el)
        if el["type"] in ("new_text", "image"):
            room_x = 1 - (el["x"] + el["width"])
            room_y = 1 - (el["y"] + el["height"])
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["x"] = el["x"] + dx
            shifted["y"] = el["y"] + dy
        elif el["type"] == "shape":
            room_x = 1 - max(el["x0"], el["x1"])
            room_y = 1 - max(el["y0"], el["y1"])
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["x0"] = el["x0"] + dx
            shifted["x1"] = el["x1"] + dx
            shifted["y0"] = el["y0"] + dy
            shifted["y1"] = el["y1"] + dy
        return shifted
```

In `EditElementsModel.nudge` (`app/ui/edit_canvas.py:171-183`), add a `shape` branch (this is the fix for the Global Constraints' documented spec error):
```python
    def nudge(self, element_id: str, dx: float, dy: float) -> None:
        """A discrete, deliberate action (one keypress = one small move) -
        unlike a mouse drag's many intermediate positions, each nudge call
        commits its own undo step, matching add/remove's own
        commit-before-mutate pattern."""
        self.commit()
        for el in self.elements:
            if el["id"] == element_id:
                if el["type"] in ("new_text", "image"):
                    el["x"] = min(max(el["x"] + dx, 0), 1 - el["width"])
                    el["y"] = min(max(el["y"] + dy, 0), 1 - el["height"])
                elif el["type"] == "shape":
                    x_min, x_max = min(el["x0"], el["x1"]), max(el["x0"], el["x1"])
                    y_min, y_max = min(el["y0"], el["y1"]), max(el["y0"], el["y1"])
                    clamped_dx = min(max(dx, -x_min), 1 - x_max)
                    clamped_dy = min(max(dy, -y_min), 1 - y_max)
                    el["x0"] += clamped_dx
                    el["x1"] += clamped_dx
                    el["y0"] += clamped_dy
                    el["y1"] += clamped_dy
                break
        self._notify()
```

In `EditPageWidget.__init__` (`app/ui/edit_canvas.py:198-209`), add the new style attributes and the create-drag field:
```python
    def __init__(self, model, page_number: int, parent=None, on_image_click=None):
        super().__init__(parent)
        self.model = model
        self.page_number = page_number
        self.page_pixmap = None
        self.create_mode = "new_text"
        self.on_image_click = on_image_click
        self.image_cache: dict = {}
        self.shape_type = "rectangle"
        self.color = "#ff0000"
        self.width_preset = "medium"
        self.filled = False
        self._drag: dict | None = None
        self._create_drag: dict | None = None
        self._text_editor: QTextEdit | None = None
        self._editing_element_id: str | None = None
        self.model.on_change.append(self.update)
```

Replace `_element_rect_px` (`app/ui/edit_canvas.py:226-231`) with a type-dispatching version — `new_text`/`image` keep their exact existing formula, `shape` is new:
```python
    def _element_rect_px(self, el: dict) -> QRect:
        t = el["type"]
        if t == "shape":
            x0, x1 = sorted((el["x0"], el["x1"]))
            y0, y1 = sorted((el["y0"], el["y1"]))
        else:
            x0, y0 = el["x"], el["y"]
            x1, y1 = el["x"] + el["width"], el["y"] + el["height"]
        px0, py0 = x0 * self.width(), y0 * self.height()
        px1, py1 = x1 * self.width(), y1 * self.height()
        return QRect(int(px0), int(py0), int(px1 - px0), int(py1 - py0))
```

In `_resize_handles` (`app/ui/edit_canvas.py:250-270`), add a `shape` branch:
```python
    def _resize_handles(self, el: dict) -> dict:
        """One handle for new_text (free resize, bottom-right) and for
        shape (drags x1,y1 directly - see mouseMoveEvent). Three for
        image: a corner (aspect-locked uniform scale, matching
        ImagePlacementWidget's existing formula exactly), plus independent
        width-only and height-only handles (mid-right / mid-bottom edges)
        that deliberately allow aspect distortion, matching the web app's
        own three-handle image behavior (_apply_image's own
        keep_proportion=False trusts whatever box the editor produced)."""
        rect = self._element_rect_px(el)
        size = self._corner_size(rect)
        if el["type"] in ("new_text", "shape"):
            return {"corner": QRect(rect.right() - size, rect.bottom() - size, size, size)}
        if el["type"] == "image":
            mid_x = rect.left() + rect.width() // 2
            mid_y = rect.top() + rect.height() // 2
            return {
                "corner": QRect(rect.right() - size, rect.bottom() - size, size, size),
                "width": QRect(rect.right() - size, mid_y - size // 2, size, size),
                "height": QRect(mid_x - size // 2, rect.bottom() - size, size, size),
            }
        return {}
```

Replace `mousePressEvent` (`app/ui/edit_canvas.py:279-317`) — adds the margin-inflated body hit-test for `shape` and the empty-space dispatch into `_create_drag`:
```python
    def mousePressEvent(self, e) -> None:
        # THE commit path for an open text draft in the real running app:
        # clicking anywhere else on the page finishes whatever is being
        # typed, before any hit-testing runs (so the click itself then
        # acts on the post-commit element list). Without this, a typed
        # draft is silently discarded and _text_editor never returns to
        # None - which would also leave EditPdfDialog._any_text_editor_open
        # stuck True, disabling every shortcut for the rest of the session.
        if self._text_editor is not None:
            self._commit_text_editor()
        pos = e.position().toPoint()
        elements = self._elements()
        for i in reversed(range(len(elements))):
            el = elements[i]
            if self._marker_rect(el).contains(pos):
                self.model.remove(el["id"])
                return
        for i in reversed(range(len(elements))):
            el = elements[i]
            for handle_name, rect in self._resize_handles(el).items():
                if rect.contains(pos):
                    point = self._point_from_pos(pos)
                    self.model.select(el["id"])
                    self._drag = {"mode": f"resize-{handle_name}", "id": el["id"], "start": point, "start_element": dict(el), "committed": False}
                    return
        for i in reversed(range(len(elements))):
            el = elements[i]
            hit_rect = self._element_rect_px(el)
            if el["type"] == "shape":
                # A horizontal/vertical line or arrow has a zero-height or
                # zero-width bounding box, which QRect.contains() can never
                # match for a real (integer-rounded) click point - inflate
                # the hit target so thin shapes stay selectable/movable.
                margin = max(6, el["width"])
                hit_rect = hit_rect.adjusted(-margin, -margin, margin, margin)
            if hit_rect.contains(pos):
                point = self._point_from_pos(pos)
                self.model.select(el["id"])
                self._drag = {"mode": "move", "id": el["id"], "start": point, "start_element": dict(el), "committed": False}
                return
        point = self._point_from_pos(pos)
        if point is None:
            return
        if self.create_mode == "new_text":
            self._open_text_editor_for_new(point)
        elif self.create_mode == "image" and self.on_image_click is not None:
            self.on_image_click(point)
        elif self.create_mode in ("shape", "stroke", "highlight"):
            self._create_drag = {"start": point, "current": point, "points": [point]}
```

Replace `mouseMoveEvent` (`app/ui/edit_canvas.py:365-394`) — adds the `_create_drag` live-update branch at the top, plus `shape`'s move/resize-corner branches:
```python
    def mouseMoveEvent(self, e) -> None:
        if self._create_drag is not None:
            point = self._point_from_pos(e.position().toPoint())
            if point is not None:
                self._create_drag["current"] = point
                self._create_drag["points"].append(point)
                self.update()
            return
        if self._drag is None:
            return
        point = self._point_from_pos(e.position().toPoint())
        if point is None:
            return
        dx = point[0] - self._drag["start"][0]
        dy = point[1] - self._drag["start"][1]
        sp = self._drag["start_element"]
        if self._drag["mode"] == "move":
            if sp["type"] == "shape":
                self._apply_drag(x0=sp["x0"] + dx, y0=sp["y0"] + dy, x1=sp["x1"] + dx, y1=sp["y1"] + dy)
            else:
                x = min(max(sp["x"] + dx, 0), 1 - sp["width"])
                y = min(max(sp["y"] + dy, 0), 1 - sp["height"])
                self._apply_drag(x=x, y=y)
        elif self._drag["mode"] == "resize-corner":
            if sp["type"] == "shape":
                new_x1 = min(max(sp["x1"] + dx, 0), 1)
                new_y1 = min(max(sp["y1"] + dy, 0), 1)
                self._apply_drag(x1=new_x1, y1=new_y1)
            elif sp["type"] == "image":
                aspect = sp["height"] / sp["width"]
                width_cap = min(1 - sp["x"], (1 - sp["y"]) / aspect)
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, width_cap))
                height = width * aspect
                self._apply_drag(width=width, height=height)
            else:
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
                height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
                self._apply_drag(width=width, height=height)
        elif self._drag["mode"] == "resize-width":
            width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
            self._apply_drag(width=width)
        elif self._drag["mode"] == "resize-height":
            height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
            self._apply_drag(height=height)
```

Replace `mouseReleaseEvent` (`app/ui/edit_canvas.py:396-402`):
```python
    def mouseReleaseEvent(self, e) -> None:
        if self._create_drag is not None:
            drag = self._create_drag
            self._create_drag = None
            self._finish_create_drag(drag)
            self.update()
            return
        # Deliberately commits NOTHING: _apply_drag already pushed this
        # gesture's single undo step, pre-mutation, the moment the gesture
        # first changed anything - and a gesture that changed nothing (the
        # plain click-to-select mousePressEvent also arms a drag for) must
        # not push one at all.
        self._drag = None
```

Add the new `_finish_create_drag` method (place it right after `mouseReleaseEvent`) — Tasks 2-3 each add one `elif` branch here:
```python
    def _finish_create_drag(self, drag: dict) -> str | None:
        """Dispatches a completed drag-to-create gesture by self.create_mode
        into the appropriate new element, or discards it if it didn't clear
        that type's own minimum-size/extent gate. Task 1 (shape) is the
        only branch that exists yet; Tasks 2 (stroke) and 3 (highlight)
        each add their own elif branch here - see this plan's Global
        Constraints for each type's exact threshold rule, confirmed against
        the web app's own EditPdfCanvas.jsx."""
        x0, y0 = drag["start"]
        x1, y1 = drag["current"]
        if self.create_mode == "shape":
            if self.shape_type in ("rectangle", "ellipse"):
                ok = abs(x1 - x0) >= _MIN_DRAG_FRACTION and abs(y1 - y0) >= _MIN_DRAG_FRACTION
            else:
                ok = abs(x1 - x0) >= _MIN_DRAG_FRACTION or abs(y1 - y0) >= _MIN_DRAG_FRACTION
            if not ok:
                return None
            filled = self.filled if self.shape_type in ("rectangle", "ellipse") else False
            return self.model.add({
                "page": self.page_number, "type": "shape", "shape": self.shape_type,
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "color": self.color, "width": _WIDTH_PRESETS[self.width_preset], "filled": filled,
            })
        return None
```

Add the new `_paint_create_preview` method (place it right after `_finish_create_drag`) — Tasks 2-3 each add one `elif` branch here:
```python
    def _paint_create_preview(self, painter: QPainter) -> None:
        """Renders the in-progress drag-to-create gesture directly from
        local widget state - deliberately never touches the model, so
        there is nothing to undo/commit if the drag is abandoned (e.g.
        released below the minimum threshold)."""
        if self._create_drag is None:
            return
        if self.create_mode == "shape":
            filled = self.filled if self.shape_type in ("rectangle", "ellipse") else False
            preview = {
                "type": "shape", "shape": self.shape_type,
                "x0": self._create_drag["start"][0], "y0": self._create_drag["start"][1],
                "x1": self._create_drag["current"][0], "y1": self._create_drag["current"][1],
                "color": self.color, "width": _WIDTH_PRESETS[self.width_preset], "filled": filled,
            }
            self._paint_shape(painter, preview)
```

Add the new `_paint_shape` and `_draw_arrow_head` methods (place them right after `_paint_image`):
```python
    def _paint_shape(self, painter: QPainter, el: dict) -> None:
        x0_px, y0_px = el["x0"] * self.width(), el["y0"] * self.height()
        x1_px, y1_px = el["x1"] * self.width(), el["y1"] * self.height()
        color = QColor(el["color"])
        painter.setPen(QPen(color, el["width"]))
        if el["shape"] in ("rectangle", "ellipse"):
            rect = QRect(int(min(x0_px, x1_px)), int(min(y0_px, y1_px)), int(abs(x1_px - x0_px)), int(abs(y1_px - y0_px)))
            painter.setBrush(color if el["filled"] else Qt.NoBrush)
            if el["shape"] == "rectangle":
                painter.drawRect(rect)
            else:
                painter.drawEllipse(rect)
        elif el["shape"] == "line":
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(int(x0_px), int(y0_px), int(x1_px), int(y1_px))
        else:  # arrow
            painter.setBrush(color)
            self._draw_arrow_head(painter, x0_px, y0_px, x1_px, y1_px, el["width"])

    def _draw_arrow_head(self, painter: QPainter, x0: float, y0: float, x1: float, y1: float, width: float) -> None:
        """Client-side port of _apply_shape's _draw_arrow (pdf_ops.py:693)
        for the on-screen preview only - the actual PDF export still goes
        through the unchanged, existing _apply_shape/_draw_arrow, so this
        only needs to look reasonably like an arrow, not byte-for-byte
        match the export's geometry."""
        painter.drawLine(int(x0), int(y0), int(x1), int(y1))
        angle = math.atan2(y1 - y0, x1 - x0)
        head_len = max(8, width * 3)
        head_angle = math.radians(25)
        h1x = x1 - head_len * math.cos(angle - head_angle)
        h1y = y1 - head_len * math.sin(angle - head_angle)
        h2x = x1 - head_len * math.cos(angle + head_angle)
        h2y = y1 - head_len * math.sin(angle + head_angle)
        painter.drawPolygon(QPolygon([
            QPoint(int(x1), int(y1)), QPoint(int(h1x), int(h1y)), QPoint(int(h2x), int(h2y)),
        ]))
```

Update `paintEvent` (`app/ui/edit_canvas.py:466-475`) to dispatch to `_paint_shape` and to call `_paint_create_preview` at the end:
```python
    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.page_pixmap is not None:
            painter.drawPixmap(0, 0, self.page_pixmap)
        for el in self._elements():
            if el["type"] == "new_text":
                self._paint_new_text(painter, el)
            elif el["type"] == "image":
                self._paint_image(painter, el)
            elif el["type"] == "shape":
                self._paint_shape(painter, el)
            self._paint_chrome(painter, el)
        self._paint_create_preview(painter)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "shape" -v`
Expected: PASS (all new tests from Step 1).

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (every pre-existing test in the file still passes — confirms this task's changes to shared dispatch methods didn't regress `new_text`/`image`).

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add shape element support to the Edit PDF page widget"
```

No trailer — `feat:`, not `fix:`.

---

### Task 2: `stroke` element type

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: everything Task 1 produced — `_MIN_DRAG_FRACTION`, `_WIDTH_PRESETS`, `EditPageWidget._create_drag`/`_finish_create_drag`/`_paint_create_preview`/`shape_type`/`color`/`width_preset`/`filled` attributes, `_element_rect_px`'s type-dispatch pattern.
- Produces: nothing new consumed by Task 3 (highlight is independent of stroke) or Task 4 beyond what Task 1 already produced.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def _stroke_element(page=1, points=None, color="#00aa00", width=3):
    return {"page": page, "type": "stroke", "points": points or [{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.2}], "color": color, "width": width}


def test_edit_model_stroke_paste_offset_shifts_every_point_and_clamps_near_edge():
    model = EditElementsModel()
    el_id = model.add(_stroke_element(points=[{"x": 0.1, "y": 0.1}, {"x": 0.3, "y": 0.2}]))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["points"][0]["x"] == pytest.approx(0.13)
    assert pasted["points"][1]["y"] == pytest.approx(0.23)

    el_id2 = model.add(_stroke_element(points=[{"x": 0.9, "y": 0.1}, {"x": 0.99, "y": 0.2}]))
    model.select(el_id2)
    model.copy()
    pasted_id2 = model.paste()
    pasted2 = next(e for e in model.elements if e["id"] == pasted_id2)
    # room_x = 1 - max(0.9, 0.99) = 0.01, clamped to 0.01
    assert pasted2["points"][1]["x"] == pytest.approx(1.0)
    assert pasted2["points"][0]["x"] == pytest.approx(0.91)


def test_edit_model_stroke_nudge_shifts_every_point_and_clamps_at_the_page_edge():
    model = EditElementsModel()
    el_id = model.add(_stroke_element(points=[{"x": 0.9, "y": 0.3}, {"x": 0.98, "y": 0.4}]))
    model.nudge(el_id, 0.5, 0.0)
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["points"][1]["x"] == pytest.approx(1.0)
    assert el["points"][0]["x"] == pytest.approx(0.92)
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["points"][0]["x"] == pytest.approx(0.9)


def test_edit_page_widget_freehand_drag_captures_every_move_as_a_point():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    widget.color = "#123456"
    widget.width_preset = "thin"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.1), int(h * 0.1))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, QPoint(int(w * 0.15), int(h * 0.15)))
    QTest.mouseMove(widget, QPoint(int(w * 0.2), int(h * 0.2)))
    end = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "stroke" and len(el["points"]) == 4  # start + 2 moves + end
    assert el["color"] == "#123456" and el["width"] == 1


def test_edit_page_widget_stroke_click_with_one_axis_of_jitter_is_kept():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    w, h = widget.width(), widget.height()
    # dx clears the threshold; dy is a sub-pixel sliver - kept per the
    # web's own "discard only if BOTH axes are below threshold" rule.
    start = QPoint(int(w * 0.1), int(h * 0.5))
    end = QPoint(int(w * 0.3), int(h * 0.5005))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1


def test_edit_page_widget_stroke_with_both_axes_of_jitter_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.5), int(h * 0.5))
    end = QPoint(int(w * 0.501), int(h * 0.501))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_stroke_single_point_click_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "stroke"
    click = QPoint(40, 60)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert model.elements == []


def test_edit_page_widget_stroke_has_no_resize_handle():
    model = EditElementsModel()
    el_id = model.add(_stroke_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert widget._resize_handles(el) == {}


def test_edit_page_widget_moving_a_stroke_shifts_every_point():
    model = EditElementsModel()
    el_id = model.add(_stroke_element(points=[{"x": 0.2, "y": 0.2}, {"x": 0.25, "y": 0.25}, {"x": 0.3, "y": 0.2}]))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    body = QPoint(int(w * 0.25), int(h * 0.22))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 8, body.y() + 4))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 8, body.y() + 4))
    el = next(e for e in model.elements if e["id"] == el_id)
    dx, dy = 8 / w, 4 / h
    assert el["points"][0]["x"] == pytest.approx(0.2 + dx)
    assert el["points"][2]["y"] == pytest.approx(0.2 + dy)


def test_edit_page_widget_clicking_a_strokes_marker_removes_it():
    model = EditElementsModel()
    el_id = model.add(_stroke_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    marker = widget._marker_rect(el)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "stroke" -v`
Expected: FAIL — `EditPageWidget` doesn't create/move/paint `stroke` elements yet, `EditElementsModel` doesn't paste/nudge them yet.

- [ ] **Step 3: Implement `stroke` support**

Add `QPainterPath` to `edit_canvas.py`'s existing `from PySide6.QtGui import ...` line (the one Task 1 already extended with `QPolygon`):
```python
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygon
```

In `EditElementsModel._shift_for_paste`, add a `stroke` branch (append after the `shape` branch Task 1 added):
```python
        elif el["type"] == "stroke":
            xs = [p["x"] for p in el["points"]]
            ys = [p["y"] for p in el["points"]]
            room_x = 1 - max(xs)
            room_y = 1 - max(ys)
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["points"] = [{"x": p["x"] + dx, "y": p["y"] + dy} for p in el["points"]]
        return shifted
```
(Insert this new `elif` block into the existing `if`/`elif` chain, directly after the `shape` branch Task 1 added and before the method's trailing `return shifted` line, which stays exactly where it already is.)

In `EditElementsModel.nudge`, add a `stroke` branch (append after the `shape` branch Task 1 added, before `break`):
```python
                elif el["type"] == "stroke":
                    xs = [p["x"] for p in el["points"]]
                    ys = [p["y"] for p in el["points"]]
                    x_min, x_max = min(xs), max(xs)
                    y_min, y_max = min(ys), max(ys)
                    clamped_dx = min(max(dx, -x_min), 1 - x_max)
                    clamped_dy = min(max(dy, -y_min), 1 - y_max)
                    el["points"] = [{"x": p["x"] + clamped_dx, "y": p["y"] + clamped_dy} for p in el["points"]]
                break
```

In `_element_rect_px`, add a `stroke` branch to the `if t == "shape":`/`else:` dispatch — change it to:
```python
    def _element_rect_px(self, el: dict) -> QRect:
        t = el["type"]
        if t == "shape":
            x0, x1 = sorted((el["x0"], el["x1"]))
            y0, y1 = sorted((el["y0"], el["y1"]))
        elif t == "stroke":
            xs = [p["x"] for p in el["points"]]
            ys = [p["y"] for p in el["points"]]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        else:
            x0, y0 = el["x"], el["y"]
            x1, y1 = el["x"] + el["width"], el["y"] + el["height"]
        px0, py0 = x0 * self.width(), y0 * self.height()
        px1, py1 = x1 * self.width(), y1 * self.height()
        return QRect(int(px0), int(py0), int(px1 - px0), int(py1 - py0))
```

In `mousePressEvent`'s body hit-test loop, extend the margin-inflation condition Task 1 added from `shape`-only to also cover `stroke` (a near-collinear freehand scribble has the identical thin-bbox problem):
```python
            if el["type"] in ("shape", "stroke"):
```
(This is the one-line change to the existing `if el["type"] == "shape":` check inside the body hit-test loop.)

`_resize_handles` needs **no change** for `stroke` — it already falls through to `return {}` for any type it doesn't explicitly recognize, which is exactly the desired "no resize handle" behavior.

In `mouseMoveEvent`'s `"move"` branch, add a `stroke` case:
```python
        if self._drag["mode"] == "move":
            if sp["type"] == "shape":
                self._apply_drag(x0=sp["x0"] + dx, y0=sp["y0"] + dy, x1=sp["x1"] + dx, y1=sp["y1"] + dy)
            elif sp["type"] == "stroke":
                self._apply_drag(points=[{"x": p["x"] + dx, "y": p["y"] + dy} for p in sp["points"]])
            else:
                x = min(max(sp["x"] + dx, 0), 1 - sp["width"])
                y = min(max(sp["y"] + dy, 0), 1 - sp["height"])
                self._apply_drag(x=x, y=y)
```
(No changes needed to the `"resize-corner"`/`"resize-width"`/`"resize-height"` branches — `stroke` never arms a resize drag, since `_resize_handles` returns `{}` for it.)

In `_finish_create_drag`, add a `stroke` branch:
```python
        elif self.create_mode == "stroke":
            pts = drag["points"]
            if len(pts) < 2:
                return None
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if (max(xs) - min(xs)) < _MIN_DRAG_FRACTION and (max(ys) - min(ys)) < _MIN_DRAG_FRACTION:
                return None
            return self.model.add({
                "page": self.page_number, "type": "stroke",
                "points": [{"x": x, "y": y} for x, y in pts],
                "color": self.color, "width": _WIDTH_PRESETS[self.width_preset],
            })
        return None
```
(Insert this between the existing `shape` branch and the trailing `return None`.)

Add the new `_paint_stroke` method (place it right after `_paint_shape`):
```python
    def _paint_stroke(self, painter: QPainter, el: dict) -> None:
        points = el["points"]
        if not points:
            return
        path = QPainterPath()
        first = points[0]
        path.moveTo(first["x"] * self.width(), first["y"] * self.height())
        for p in points[1:]:
            path.lineTo(p["x"] * self.width(), p["y"] * self.height())
        painter.setPen(QPen(QColor(el["color"]), el["width"]))
        painter.drawPath(path)
```

In `_paint_create_preview`, add a `stroke` branch:
```python
        elif self.create_mode == "stroke":
            preview = {"points": [{"x": x, "y": y} for x, y in self._create_drag["points"]], "color": self.color, "width": _WIDTH_PRESETS[self.width_preset]}
            self._paint_stroke(painter, preview)
```

In `paintEvent`, add a `stroke` dispatch:
```python
            elif el["type"] == "stroke":
                self._paint_stroke(painter, el)
```
(Insert this as a new `elif` branch alongside the existing `new_text`/`image`/`shape` branches.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "stroke" -v`
Expected: PASS.

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (every pre-existing test, including Task 1's `shape` tests, still passes).

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add stroke (freehand draw) element support to the Edit PDF page widget"
```

No trailer — `feat:`, not `fix:`.

---

### Task 3: `highlight` element type

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: everything Task 1 produced, same as Task 2. Independent of Task 2's `stroke` work.
- Produces: nothing new consumed by Task 4 beyond what Task 1 already produced.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`. This task needs `box_to_insets`/`insets_to_box` for building expected values — the file already imports them from `app.ui.widgets` at module level (established by an earlier plan, confirm before writing tests that the existing `from app.ui.widgets import ... box_to_insets, insets_to_box` import line is present; it is, per this file's line ~12):
```python
def _highlight_element(page=1, top=0.2, left=0.2, right=0.5, bottom=0.5, color="#ffff00"):
    return {"page": page, "type": "highlight", "top": top, "left": left, "right": right, "bottom": bottom, "color": color}


def test_edit_model_highlight_paste_offset_uses_insets_directly_as_room():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.2, left=0.2, right=0.5, bottom=0.5))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["left"] == pytest.approx(0.23) and pasted["right"] == pytest.approx(0.47)
    assert pasted["top"] == pytest.approx(0.23) and pasted["bottom"] == pytest.approx(0.47)

    el_id2 = model.add(_highlight_element(top=0.2, left=0.2, right=0.01, bottom=0.5))
    model.select(el_id2)
    model.copy()
    pasted_id2 = model.paste()
    pasted2 = next(e for e in model.elements if e["id"] == pasted_id2)
    # right=0.01 IS the room (no separate max-corner calc needed for this type) - clamps to itself
    assert pasted2["right"] == pytest.approx(0.0)
    assert pasted2["left"] == pytest.approx(0.21)


def test_edit_model_highlight_nudge_shifts_left_top_and_shrinks_right_bottom():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.2, left=0.2, right=0.01, bottom=0.5))
    model.nudge(el_id, 0.5, 0.0)  # far past the right edge
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["right"] == pytest.approx(0.0)
    assert el["left"] == pytest.approx(0.21)
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["right"] == pytest.approx(0.01) and reverted["left"] == pytest.approx(0.2)


def test_edit_page_widget_dragging_creates_a_highlight_with_sorted_insets():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "highlight"
    widget.color = "#ff00ff"
    w, h = widget.width(), widget.height()
    # drag from bottom-right to top-left - insets must still sort correctly
    start = QPoint(int(w * 0.6), int(h * 0.5))
    end = QPoint(int(w * 0.3), int(h * 0.2))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "highlight" and el["color"] == "#ff00ff"
    assert el["left"] == pytest.approx(0.3) and el["top"] == pytest.approx(0.2)
    assert el["right"] == pytest.approx(1 - 0.6) and el["bottom"] == pytest.approx(1 - 0.5)


def test_edit_page_widget_below_threshold_highlight_drag_creates_nothing():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "highlight"
    w, h = widget.width(), widget.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.205), int(h * 0.4))  # dx below threshold even though dy clears it
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(widget, end)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, end)
    assert model.elements == []


def test_edit_page_widget_highlight_resize_only_changes_right_and_bottom():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.2, left=0.2, right=0.5, bottom=0.5))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    handle = widget._resize_handles(el)["corner"]
    center = handle.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(widget, QPoint(center.x() + 15, center.y() + 15))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(center.x() + 15, center.y() + 15))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["top"] == 0.2 and el["left"] == 0.2  # untouched
    assert el["right"] < 0.5 and el["bottom"] < 0.5  # box grew -> insets shrank
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["right"] == 0.5 and reverted["bottom"] == 0.5


def test_edit_page_widget_moving_a_highlight_shifts_left_top_up_and_right_bottom_down():
    model = EditElementsModel()
    el_id = model.add(_highlight_element(top=0.3, left=0.3, right=0.4, bottom=0.4))
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    body = QPoint(int(w * 0.35), int(h * 0.35))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 12, body.y() + 6))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 12, body.y() + 6))
    el = next(e for e in model.elements if e["id"] == el_id)
    dx, dy = 12 / w, 6 / h
    # Moving right/down must INCREASE left/top and DECREASE right/bottom -
    # a sign error here was caught during this plan's own verification.
    assert el["left"] == pytest.approx(0.3 + dx) and el["top"] == pytest.approx(0.3 + dy)
    assert el["right"] == pytest.approx(0.4 - dx) and el["bottom"] == pytest.approx(0.4 - dy)


def test_edit_page_widget_clicking_a_highlights_marker_removes_it():
    model = EditElementsModel()
    el_id = model.add(_highlight_element())
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = next(e for e in model.elements if e["id"] == el_id)
    marker = widget._marker_rect(el)
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "highlight" -v`
Expected: FAIL — `EditPageWidget` doesn't create/move/resize/paint `highlight` elements yet, `EditElementsModel` doesn't paste/nudge them yet.

- [ ] **Step 3: Implement `highlight` support**

Add the import this task needs, at the top of `app/ui/edit_canvas.py`, alongside the existing local imports:
```python
from app.ui.widgets import box_to_insets, insets_to_box
```

In `EditElementsModel._shift_for_paste`, add a `highlight` branch (append after the `stroke` branch Task 2 added):
```python
        elif el["type"] == "highlight":
            # The stored right/bottom insets ARE the remaining-room
            # quantity directly - unlike every other type, no separate
            # max-corner calculation is needed here at all.
            dx = min(max(el["right"], 0), _PASTE_OFFSET)
            dy = min(max(el["bottom"], 0), _PASTE_OFFSET)
            shifted["left"] = el["left"] + dx
            shifted["right"] = el["right"] - dx
            shifted["top"] = el["top"] + dy
            shifted["bottom"] = el["bottom"] - dy
        return shifted
```

In `EditElementsModel.nudge`, add a `highlight` branch (append after the `stroke` branch Task 2 added, before `break`):
```python
                elif el["type"] == "highlight":
                    clamped_dx = min(max(dx, -el["left"]), el["right"])
                    clamped_dy = min(max(dy, -el["top"]), el["bottom"])
                    el["left"] += clamped_dx
                    el["right"] -= clamped_dx
                    el["top"] += clamped_dy
                    el["bottom"] -= clamped_dy
                break
```

In `_element_rect_px`, add a `highlight` branch:
```python
    def _element_rect_px(self, el: dict) -> QRect:
        t = el["type"]
        if t == "shape":
            x0, x1 = sorted((el["x0"], el["x1"]))
            y0, y1 = sorted((el["y0"], el["y1"]))
        elif t == "stroke":
            xs = [p["x"] for p in el["points"]]
            ys = [p["y"] for p in el["points"]]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        elif t == "highlight":
            box = insets_to_box({"top": el["top"], "left": el["left"], "right": el["right"], "bottom": el["bottom"]})
            x0, y0, x1, y1 = box["x0"], box["y0"], box["x1"], box["y1"]
        else:
            x0, y0 = el["x"], el["y"]
            x1, y1 = el["x"] + el["width"], el["y"] + el["height"]
        px0, py0 = x0 * self.width(), y0 * self.height()
        px1, py1 = x1 * self.width(), y1 * self.height()
        return QRect(int(px0), int(py0), int(px1 - px0), int(py1 - py0))
```

In `_resize_handles`, extend the `new_text`/`shape` tuple to include `highlight` (its resize handle is drawn identically — bottom-right corner of the bbox):
```python
        if el["type"] in ("new_text", "shape", "highlight"):
            return {"corner": QRect(rect.right() - size, rect.bottom() - size, size, size)}
```

In `mouseMoveEvent`'s `"move"` branch, add a `highlight` case:
```python
        if self._drag["mode"] == "move":
            if sp["type"] == "shape":
                self._apply_drag(x0=sp["x0"] + dx, y0=sp["y0"] + dy, x1=sp["x1"] + dx, y1=sp["y1"] + dy)
            elif sp["type"] == "stroke":
                self._apply_drag(points=[{"x": p["x"] + dx, "y": p["y"] + dy} for p in sp["points"]])
            elif sp["type"] == "highlight":
                self._apply_drag(top=sp["top"] + dy, left=sp["left"] + dx, right=sp["right"] - dx, bottom=sp["bottom"] - dy)
            else:
                x = min(max(sp["x"] + dx, 0), 1 - sp["width"])
                y = min(max(sp["y"] + dy, 0), 1 - sp["height"])
                self._apply_drag(x=x, y=y)
```

In `mouseMoveEvent`'s `"resize-corner"` branch, add a `highlight` case:
```python
        elif self._drag["mode"] == "resize-corner":
            if sp["type"] == "shape":
                new_x1 = min(max(sp["x1"] + dx, 0), 1)
                new_y1 = min(max(sp["y1"] + dy, 0), 1)
                self._apply_drag(x1=new_x1, y1=new_y1)
            elif sp["type"] == "highlight":
                box = insets_to_box({"top": sp["top"], "left": sp["left"], "right": sp["right"], "bottom": sp["bottom"]})
                new_x1 = min(max(box["x1"] + dx, box["x0"] + _MIN_DRAG_FRACTION), 1)
                new_y1 = min(max(box["y1"] + dy, box["y0"] + _MIN_DRAG_FRACTION), 1)
                self._apply_drag(right=1 - new_x1, bottom=1 - new_y1)
            elif sp["type"] == "image":
                aspect = sp["height"] / sp["width"]
                width_cap = min(1 - sp["x"], (1 - sp["y"]) / aspect)
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, width_cap))
                height = width * aspect
                self._apply_drag(width=width, height=height)
            else:
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
                height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
                self._apply_drag(width=width, height=height)
```

In `_finish_create_drag`, add a `highlight` branch:
```python
        elif self.create_mode == "highlight":
            sx0, sx1 = sorted((x0, x1))
            sy0, sy1 = sorted((y0, y1))
            if (sx1 - sx0) < _MIN_DRAG_FRACTION or (sy1 - sy0) < _MIN_DRAG_FRACTION:
                return None
            insets = box_to_insets({"x0": sx0, "y0": sy0, "x1": sx1, "y1": sy1})
            return self.model.add({"page": self.page_number, "type": "highlight", "color": self.color, **insets})
```
(Insert this between the `stroke` branch Task 2 added and the trailing `return None`.)

Add the new `_paint_highlight` method (place it right after `_paint_stroke`):
```python
    def _paint_highlight(self, painter: QPainter, el: dict) -> None:
        box = insets_to_box({"top": el["top"], "left": el["left"], "right": el["right"], "bottom": el["bottom"]})
        rect = QRect(
            int(box["x0"] * self.width()), int(box["y0"] * self.height()),
            int((box["x1"] - box["x0"]) * self.width()), int((box["y1"] - box["y0"]) * self.height()),
        )
        color = QColor(el["color"])
        color.setAlphaF(0.4)
        painter.setPen(Qt.NoPen)
        painter.fillRect(rect, color)
```

In `_paint_create_preview`, add a `highlight` branch:
```python
        elif self.create_mode == "highlight":
            sx0, sx1 = sorted((self._create_drag["start"][0], self._create_drag["current"][0]))
            sy0, sy1 = sorted((self._create_drag["start"][1], self._create_drag["current"][1]))
            insets = box_to_insets({"x0": sx0, "y0": sy0, "x1": sx1, "y1": sy1})
            preview = {"color": self.color, **insets}
            self._paint_highlight(painter, preview)
```

In `paintEvent`, add a `highlight` dispatch:
```python
            elif el["type"] == "highlight":
                self._paint_highlight(painter, el)
```
(Insert this as a new `elif` branch alongside the existing `new_text`/`image`/`shape`/`stroke` branches. Order matters here only for paint layering within a single element - `_paint_highlight` should run BEFORE `_paint_chrome` for the same element, same as every other type, which the existing loop structure already guarantees.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "highlight" -v`
Expected: PASS.

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (every pre-existing test, including Tasks 1-2's tests, still passes).

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add highlight element support to the Edit PDF page widget"
```

No trailer — `feat:`, not `fix:`.

---

### Task 4: `EditPdfDialog` toolbar (5-way mode selector + style wiring)

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditPageWidget.create_mode`/`shape_type`/`color`/`width_preset`/`filled` (Tasks 1-3), `EditElementsModel` unchanged.
- Produces: nothing consumed by another task — this is the last task in this plan.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def test_edit_pdf_dialog_shape_mode_places_a_shape_and_exports_it(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]

    dlg._set_create_mode("shape")
    dlg._set_shape_type("ellipse")
    dlg._set_color("#00ff00")
    dlg._set_width_preset("thick")
    dlg._set_filled(True)
    assert page1.create_mode == "shape"
    assert page1.shape_type == "ellipse"
    assert page1.color == "#00ff00"
    assert page1.width_preset == "thick"
    assert page1.filled is True

    w, h = page1.width(), page1.height()
    start = QPoint(int(w * 0.2), int(h * 0.2))
    end = QPoint(int(w * 0.5), int(h * 0.4))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(page1, end)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end)
    assert len(dlg.model.elements) == 1
    assert dlg.model.elements[0]["shape"] == "ellipse" and dlg.model.elements[0]["width"] == 6

    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    result_pix = result[0].get_pixmap()
    result.close()
    control = fitz.open(str(input_path))
    control_pix = control[0].get_pixmap()
    control.close()
    assert result_pix.samples != control_pix.samples


def test_edit_pdf_dialog_draw_and_highlight_modes_place_and_export_both(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    w, h = page1.width(), page1.height()

    dlg._set_create_mode("draw")
    start = QPoint(int(w * 0.1), int(h * 0.1))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(page1, QPoint(int(w * 0.2), int(h * 0.2)))
    end = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mouseMove(page1, end)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end)

    dlg._set_create_mode("highlight")
    start2 = QPoint(int(w * 0.5), int(h * 0.5))
    end2 = QPoint(int(w * 0.7), int(h * 0.6))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, start2)
    QTest.mouseMove(page1, end2)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, end2)

    assert len(dlg.model.elements) == 2
    types = {el["type"] for el in dlg.model.elements}
    assert types == {"stroke", "highlight"}

    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    result_pix = result[0].get_pixmap()
    result.close()
    control = fitz.open(str(input_path))
    control_pix = control[0].get_pixmap()
    control.close()
    assert result_pix.samples != control_pix.samples


def test_edit_pdf_dialog_new_pages_inherit_the_current_shape_style(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path_a = tmp_path / "input_a.pdf"
    doc.save(str(input_path_a))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path_a)])
    dlg._set_create_mode("shape")
    dlg._set_shape_type("line")
    dlg._set_color("#abcdef")
    dlg._set_width_preset("thin")

    doc2 = fitz.open()
    doc2.new_page(width=595, height=842)
    doc2.new_page(width=595, height=842)
    input_path_b = tmp_path / "input_b.pdf"
    doc2.save(str(input_path_b))
    doc2.close()

    dlg.on_files_changed([str(input_path_b)])
    for widget in dlg._page_widgets:
        assert widget.create_mode == "shape"
        assert widget.shape_type == "line"
        assert widget.color == "#abcdef"
        assert widget.width_preset == "thin"


def test_edit_pdf_dialog_mode_buttons_are_mutually_exclusive_across_all_five(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    dlg._set_create_mode("highlight")
    assert dlg.highlight_btn.isChecked() is True
    assert dlg.new_text_btn.isChecked() is False
    assert dlg.image_btn.isChecked() is False
    assert dlg.draw_btn.isChecked() is False
    assert dlg.shapes_btn.isChecked() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "edit_pdf_dialog_shape or edit_pdf_dialog_draw or edit_pdf_dialog_new_pages or edit_pdf_dialog_mode_buttons" -v`
Expected: FAIL — `_set_shape_type`/`_set_color`/`_set_width_preset`/`_set_filled`/`draw_btn`/`shapes_btn`/`highlight_btn` don't exist yet, and `_set_create_mode` doesn't accept `"draw"`/`"shape"`/`"highlight"` yet.

- [ ] **Step 3: Implement the toolbar**

Replace the existing `mode_row` block in `build_preview` (`app/ui/dialogs/edit_dialogs.py`, the block currently containing `self.new_text_btn`/`self.image_btn`) with the 5-way version, plus the three new option rows right after it:
```python
        mode_row = QHBoxLayout()
        self.new_text_btn = QPushButton("New Text")
        self.new_text_btn.setCheckable(True)
        self.new_text_btn.setChecked(True)
        self.new_text_btn.clicked.connect(lambda: self._set_create_mode("new_text"))
        mode_row.addWidget(self.new_text_btn)
        self.image_btn = QPushButton("Insert Image")
        self.image_btn.setCheckable(True)
        self.image_btn.clicked.connect(lambda: self._set_create_mode("image"))
        mode_row.addWidget(self.image_btn)
        self.draw_btn = QPushButton("Draw")
        self.draw_btn.setCheckable(True)
        self.draw_btn.clicked.connect(lambda: self._set_create_mode("draw"))
        mode_row.addWidget(self.draw_btn)
        self.shapes_btn = QPushButton("Shapes")
        self.shapes_btn.setCheckable(True)
        self.shapes_btn.clicked.connect(lambda: self._set_create_mode("shape"))
        mode_row.addWidget(self.shapes_btn)
        self.highlight_btn = QPushButton("Highlight")
        self.highlight_btn.setCheckable(True)
        self.highlight_btn.clicked.connect(lambda: self._set_create_mode("highlight"))
        mode_row.addWidget(self.highlight_btn)
        layout.addLayout(mode_row)

        _PALETTE = ["#000000", "#ff0000", "#0000ff", "#00aa00", "#ffff00"]

        def _make_swatch_row(on_pick):
            row = QHBoxLayout()
            for hex_color in _PALETTE:
                btn = QPushButton()
                btn.setFixedSize(20, 20)
                btn.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #888;")
                btn.clicked.connect(lambda _, c=hex_color: on_pick(c))
                row.addWidget(btn)
            return row

        self._draw_options = QWidget()
        draw_row = QHBoxLayout(self._draw_options)
        draw_row.addLayout(_make_swatch_row(self._set_color))
        self.draw_width_combo = QComboBox()
        self.draw_width_combo.addItems(["thin", "medium", "thick"])
        self.draw_width_combo.setCurrentText("medium")
        self.draw_width_combo.currentTextChanged.connect(self._set_width_preset)
        draw_row.addWidget(self.draw_width_combo)
        layout.addWidget(self._draw_options)

        self._shapes_options = QWidget()
        shapes_row = QHBoxLayout(self._shapes_options)
        self.shape_type_combo = QComboBox()
        self.shape_type_combo.addItems(["rectangle", "ellipse", "line", "arrow"])
        self.shape_type_combo.currentTextChanged.connect(self._set_shape_type)
        shapes_row.addWidget(self.shape_type_combo)
        shapes_row.addLayout(_make_swatch_row(self._set_color))
        self.shape_width_combo = QComboBox()
        self.shape_width_combo.addItems(["thin", "medium", "thick"])
        self.shape_width_combo.setCurrentText("medium")
        self.shape_width_combo.currentTextChanged.connect(self._set_width_preset)
        shapes_row.addWidget(self.shape_width_combo)
        self.filled_checkbox = QCheckBox("Filled")
        self.filled_checkbox.toggled.connect(self._set_filled)
        shapes_row.addWidget(self.filled_checkbox)
        layout.addWidget(self._shapes_options)

        self._highlight_options = QWidget()
        highlight_row = QHBoxLayout(self._highlight_options)
        highlight_row.addLayout(_make_swatch_row(self._set_color))
        layout.addWidget(self._highlight_options)

        self._draw_options.setVisible(False)
        self._shapes_options.setVisible(False)
        self._highlight_options.setVisible(False)
```

Add `QComboBox` and `QCheckBox` to `edit_dialogs.py`'s existing `PySide6.QtWidgets` import line if not already present (check first).

Replace `_set_create_mode` (`app/ui/dialogs/edit_dialogs.py:644-649`) with the 5-way version:
```python
    def _set_create_mode(self, mode: str) -> None:
        self._create_mode = mode
        self.new_text_btn.setChecked(mode == "new_text")
        self.image_btn.setChecked(mode == "image")
        self.draw_btn.setChecked(mode == "draw")
        self.shapes_btn.setChecked(mode == "shape")
        self.highlight_btn.setChecked(mode == "highlight")
        self._draw_options.setVisible(mode == "draw")
        self._shapes_options.setVisible(mode == "shape")
        self._highlight_options.setVisible(mode == "highlight")
        # "draw" is this toolbar's label for the stroke tool - EditPageWidget's
        # own create_mode value is "stroke" (matching the element type name),
        # not "draw".
        widget_mode = "stroke" if mode == "draw" else mode
        for widget in self._page_widgets:
            widget.create_mode = widget_mode
```

Add the four new style-state fields to `build_preview`, right after the existing `self._create_mode = "new_text"` line:
```python
        self._create_mode = "new_text"
        self._shape_type = "rectangle"
        self._color = "#ff0000"
        self._width_preset = "medium"
        self._filled = False
```

Add the four new setter methods, right after `_set_create_mode`:
```python
    def _set_shape_type(self, shape_type: str) -> None:
        self._shape_type = shape_type
        for widget in self._page_widgets:
            widget.shape_type = shape_type

    def _set_color(self, color: str) -> None:
        self._color = color
        for widget in self._page_widgets:
            widget.color = color

    def _set_width_preset(self, preset: str) -> None:
        self._width_preset = preset
        for widget in self._page_widgets:
            widget.width_preset = preset

    def _set_filled(self, filled: bool) -> None:
        self._filled = filled
        for widget in self._page_widgets:
            widget.filled = filled
```

In `on_files_changed`, extend the per-new-widget setup block (right after the existing `widget.create_mode = self._create_mode` line) so newly built page widgets inherit the current shape style too:
```python
            widget.create_mode = "stroke" if self._create_mode == "draw" else self._create_mode
            widget.shape_type = self._shape_type
            widget.color = self._color
            widget.width_preset = self._width_preset
            widget.filled = self._filled
```
(This replaces the single existing `widget.create_mode = self._create_mode` line — note the same `"draw"` → `"stroke"` translation `_set_create_mode` uses, since a freshly loaded file must match whichever tool is currently active exactly the same way an already-open file does when the toolbar changes mode.)

No changes needed to `gather_params`/`run_operation` — both are already fully generic over element type (see this plan's Global Constraints).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "edit_pdf_dialog" -v`
Expected: PASS (all `EditPdfDialog` tests, old and new).

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (the whole file, all tasks in this plan plus everything from Phase 6A).

- [ ] **Step 5: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py tests/test_ui_desktop.py
git commit -m "feat: add a 5-way toolbar (shapes, freehand draw, highlight) to the Edit PDF dialog"
```

No trailer — `feat:`, not `fix:`.

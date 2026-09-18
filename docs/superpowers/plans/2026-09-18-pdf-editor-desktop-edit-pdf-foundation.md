# Desktop App: Edit PDF Foundation (Phase 6A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Edit PDF dialog to the desktop app supporting two element types (`new_text`, `image`) on a continuous-scroll multi-page canvas, with full undo/redo, clipboard, keyboard nudge, and z-order reordering — the shared foundation later phases (6B: shapes/draw/highlight, 6C: in-place text-run editing) build on without revisiting this architecture.

**Architecture:** A new `EditElementsModel` (plain Python, no Qt) owns the state that must span every page — the flat element list, selection, undo/redo stacks, and clipboard slot — since (unlike Redact/Sign's fully independent per-page widgets) Edit PDF genuinely needs ONE selection/undo-stack/clipboard across the whole document. A new `EditPageWidget` (one instance per page, stacked in a `QScrollArea`) is a thin view: it renders its own page's filtered elements via `QPainter`, dispatching by `element["type"]`, and translates mouse events into calls on the shared model. `EditPdfDialog` owns the model, builds the per-page widgets, and wires undo/redo/copy/cut/paste/nudge/delete as dialog-level keyboard shortcuts (since "whichever element is selected" is a model-wide concept, not tied to any one page widget's focus).

**Tech Stack:** Python, PySide6, PySide6.QtTest, pytest, PyMuPDF (fitz).

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task in this plan ships new behavior — commits are `feat:` and must **not** carry the trailer.
- Real automated pytest tests using `PySide6.QtTest`'s synthetic mouse/keyboard events, appended to the existing `tests/test_ui_desktop.py` — not a manual checklist, not a second test file.
- `EditElementsModel.update()`/`.nudge()` mutate element dicts **in place**. Any test that captures a "before" snapshot for comparison must copy it (`dict(el)`) first — confirmed empirically while writing this plan: comparing a live reference against itself after a mutating call always spuriously passes/fails depending on the assertion, since both names point at the same mutated dict.
- `QShortcut` does **not** fire under `QT_QPA_PLATFORM=offscreen` (confirmed empirically — it needs real window activation/focus tracking a headless test never establishes, even after an explicit `.show()`), and `QTextEdit.hasFocus()` is similarly unreliable offscreen even after `.show()`/`.setFocus()`. Task 4's tests therefore call `_handle_shortcut(...)`/`keyPressEvent(...)` directly rather than through the real `QShortcut` objects, and the "is a text editor open" check is based on `_text_editor is not None`, never `.hasFocus()`. `QTest.keyClick(widget, key)` — direct event delivery to a specific widget's `keyPressEvent`, not the window-wide shortcut-activation system `QShortcut` relies on — **does** work correctly offscreen (confirmed empirically) and is what the arrow-key nudge tests use.
- No changes needed to `app/core/pdf_ops.py` — `edit_pdf`, `_apply_new_text`/`_validate_new_text` (`pdf_ops.py:816`/`776`), and `_apply_image`/`_validate_image_element` (`pdf_ops.py:743`/`587`) are already fully implemented and unchanged from Sign PDF's use of the same `edit_pdf`/`_apply_image` pair.
- `new_text` field shape: `{page, x, y, width, height, text, family, bold, italic, underline, size, color, align}` — `family` ∈ `{helvetica, times, courier}`, `align` ∈ `{left, center, right}`, `color` a `"#rrggbb"` hex string, `size` a positive number. `image` field shape: `{page, file_id, x, y, width, height}` — `file_id` is simply the image's own local file path (no upload/storage server on the desktop app, matching Sign PDF's own convention).
- Output filename must be exactly `<stem>_edited.pdf`.

---

### Task 1: `EditElementsModel`

**Files:**
- Create: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: nothing from another task (this is the first task).
- Produces: `EditElementsModel()` with `.elements: list[dict]`, `.selected_id: str | None`, `.on_change: list[Callable[[], None]]`, and methods `.add(element) -> str`, `.update(id, **changes) -> None`, `.remove(id) -> None`, `.select(id_or_None) -> None`, `.elements_for_page(page) -> list[dict]`, `.commit() -> None`, `.undo() -> None`, `.redo() -> None`, `.copy() -> None`, `.cut() -> None`, `.paste() -> str | None`, `.reorder(id, direction) -> None`, `.nudge(id, dx, dy) -> None`. Tasks 2-4 all depend on this exact interface.

- [ ] **Step 1: Write the failing tests**

Create `app/ui/edit_canvas.py` with just this stub so the test file's import doesn't fail at collection time (Step 3 fills in the real implementation):
```python
class EditElementsModel:
    pass
```
Append to `tests/test_ui_desktop.py`. Add a new import line: `from app.ui.edit_canvas import EditElementsModel`.
```python
def _new_text_element(page, x=0.1, y=0.1, width=0.2, height=0.1, text="Hello"):
    return {
        "page": page, "type": "new_text", "x": x, "y": y, "width": width, "height": height,
        "text": text, "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#1f2937", "align": "left",
    }


def test_edit_model_add_and_elements_for_page():
    model = EditElementsModel()
    id1 = model.add(_new_text_element(page=1))
    id2 = model.add({"page": 2, "type": "image", "x": 0.2, "y": 0.2, "width": 0.25, "height": 0.1, "file_id": "sig.png"})
    assert len(model.elements) == 2
    assert [e["id"] for e in model.elements_for_page(1)] == [id1]
    assert [e["id"] for e in model.elements_for_page(2)] == [id2]


def test_edit_model_undo_redo_are_whole_array_snapshots():
    model = EditElementsModel()
    id1 = model.add(_new_text_element(page=1))
    model.add(_new_text_element(page=1, text="Second"))
    assert len(model.elements) == 2
    model.remove(id1)
    assert len(model.elements) == 1
    model.undo()
    assert len(model.elements) == 2
    model.redo()
    assert len(model.elements) == 1


def test_edit_model_nudge_shifts_position_clamps_and_commits_an_undo_step():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.95, y=0.1, width=0.1, height=0.1))
    model.nudge(el_id, 0.5, 0.0)  # far past the right edge
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(1 - el["width"])  # clamped, not overshot
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert reverted["x"] == pytest.approx(0.95)  # nudge is its own undo step


def test_edit_model_reorder_forward_skips_a_different_page_neighbor():
    model = EditElementsModel()
    a = model.add(_new_text_element(page=1, text="a"))
    b_other_page = model.add(_new_text_element(page=2, text="b"))
    c = model.add(_new_text_element(page=1, text="c"))
    # array order is [a(page1), b(page2), c(page1)] - forward on 'a' must swap
    # with 'c' (the nearest SAME-page neighbor), skipping over 'b' (page 2).
    assert [e["id"] for e in model.elements] == [a, b_other_page, c]
    model.reorder(a, "forward")
    assert [e["id"] for e in model.elements] == [c, b_other_page, a]


def test_edit_model_reorder_front_and_back():
    model = EditElementsModel()
    a = model.add(_new_text_element(page=1, text="a"))
    b_other_page = model.add(_new_text_element(page=2, text="b"))
    c = model.add(_new_text_element(page=1, text="c"))
    d = model.add(_new_text_element(page=1, text="d"))
    # order: [a(1), b(2), c(1), d(1)]
    model.reorder(a, "front")  # 'a' becomes last among page-1 elements
    assert [e["id"] for e in model.elements] == [b_other_page, c, d, a]
    model.reorder(d, "back")  # 'd' becomes first among page-1 elements
    assert [e["id"] for e in model.elements] == [d, b_other_page, c, a]


def test_edit_model_copy_paste_shifts_by_the_paste_offset():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.3, y=0.3, width=0.1, height=0.05))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    assert pasted["x"] == pytest.approx(0.33)
    assert pasted["y"] == pytest.approx(0.33)
    assert pasted_id != el_id


def test_edit_model_paste_offset_clamps_near_the_page_edge():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1, x=0.98, y=0.1, width=0.02, height=0.05))
    model.select(el_id)
    model.copy()
    pasted_id = model.paste()
    pasted = next(e for e in model.elements if e["id"] == pasted_id)
    # room_x = 1 - (0.98 + 0.02) = 0, so the x-shift clamps to 0.
    assert pasted["x"] == pytest.approx(0.98)


def test_edit_model_cut_removes_the_source_element():
    model = EditElementsModel()
    el_id = model.add(_new_text_element(page=1))
    model.select(el_id)
    model.cut()
    assert model.elements == []
    assert model.selected_id is None
    pasted_id = model.paste()
    assert pasted_id is not None
    assert len(model.elements) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k edit_model -v`
Expected: FAIL — the stub `EditElementsModel` has none of the required methods yet.

- [ ] **Step 3: Implement `EditElementsModel`**

Replace the stub in `app/ui/edit_canvas.py` with:
```python
import uuid

_PASTE_OFFSET = 0.03


class EditElementsModel:
    """Owns the state that must be shared ACROSS every page of an Edit PDF
    session - unlike RedactDialog/SignDialog's fully independent per-page
    widgets, Edit PDF needs one selection, one undo/redo stack, and one
    clipboard slot spanning the whole document, matching the web app's own
    single flat `elements` array (never bucketed per page internally - each
    element dict carries its own "page" field). EditPageWidget instances
    (Task 2) are thin views onto this shared model, one per page.
    """

    def __init__(self):
        self.elements: list[dict] = []
        self.selected_id: str | None = None
        self._undo_stack: list[list[dict]] = []
        self._redo_stack: list[list[dict]] = []
        self._clipboard: dict | None = None
        self.on_change: list = []

    def _snapshot(self) -> list[dict]:
        return [dict(e) for e in self.elements]

    def _notify(self) -> None:
        for callback in self.on_change:
            callback()

    def commit(self) -> None:
        """Pushes the CURRENT state onto the undo stack and clears redo -
        call once per discrete action (an add, a delete, a completed
        drag/resize gesture, a paste), never per intermediate mouse-move
        during a drag."""
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def add(self, element: dict) -> str:
        self.commit()
        new_id = str(uuid.uuid4())
        el = dict(element)
        el["id"] = new_id
        self.elements.append(el)
        self.selected_id = new_id
        self._notify()
        return new_id

    def update(self, element_id: str, **changes) -> None:
        """Live in-place mutation with NO commit - used for drag/resize
        feedback while a gesture is in progress. The caller commits once,
        separately, at gesture-end."""
        for el in self.elements:
            if el["id"] == element_id:
                el.update(changes)
                break
        self._notify()

    def remove(self, element_id: str) -> None:
        self.commit()
        self.elements = [e for e in self.elements if e["id"] != element_id]
        if self.selected_id == element_id:
            self.selected_id = None
        self._notify()

    def select(self, element_id: str | None) -> None:
        self.selected_id = element_id
        self._notify()

    def elements_for_page(self, page: int) -> list[dict]:
        return [e for e in self.elements if e["page"] == page]

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self.elements = self._undo_stack.pop()
        self._notify()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self.elements = self._redo_stack.pop()
        self._notify()

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
        return shifted

    def copy(self) -> None:
        if self.selected_id is None:
            return
        for el in self.elements:
            if el["id"] == self.selected_id:
                clip = dict(el)
                clip.pop("id", None)
                self._clipboard = clip
                return

    def cut(self) -> None:
        self.copy()
        if self.selected_id is not None:
            self.remove(self.selected_id)

    def paste(self) -> str | None:
        if self._clipboard is None:
            return None
        return self.add(self._shift_for_paste(self._clipboard))

    def reorder(self, element_id: str, direction: str) -> None:
        """direction in {"front","back","forward","backward"}. "forward"/
        "backward" swap with the nearest SAME-PAGE neighbor in that array
        direction, skipping over any other page's elements sitting between
        them - so this is never a silent no-op just because another
        page's element happens to sit adjacent in the flat array.
        "front"/"back" move the element to be the last/first among its own
        page's elements."""
        self.commit()
        idx = next(i for i, e in enumerate(self.elements) if e["id"] == element_id)
        page = self.elements[idx]["page"]
        if direction in ("forward", "backward"):
            step = 1 if direction == "forward" else -1
            j = idx + step
            while 0 <= j < len(self.elements) and self.elements[j]["page"] != page:
                j += step
            if 0 <= j < len(self.elements):
                self.elements[idx], self.elements[j] = self.elements[j], self.elements[idx]
        elif direction == "front":
            el = self.elements.pop(idx)
            insert_at = max([i for i, e in enumerate(self.elements) if e["page"] == page], default=-1) + 1
            self.elements.insert(insert_at, el)
        elif direction == "back":
            el = self.elements.pop(idx)
            insert_at = min([i for i, e in enumerate(self.elements) if e["page"] == page], default=0)
            self.elements.insert(insert_at, el)
        self._notify()

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
                break
        self._notify()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k edit_model -v`
Expected: PASS (8 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as before plus 8.

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add the shared cross-page element model for Edit PDF"
```

No trailer — `feat:`, not `fix:`.

---

### Task 2: `EditPageWidget` — `new_text` support

**Files:**
- Modify: `app/ui/edit_canvas.py` (add the new class)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditElementsModel` (Task 1), unchanged.
- Produces: `EditPageWidget(model, page_number)` with `.set_page_pixmap(pixmap) -> None`, `.create_mode: str` (`"new_text"` or `"image"`, set externally by the dialog). Task 3 extends this same class with `image` support; Task 4 consumes the finished class.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`. Add `EditPageWidget` to the `edit_canvas` import line, and add `QTextEdit` to the file's existing `from PySide6.QtWidgets import ...` line if it's not already there (check first — `FillFormDialog`'s tests may have already added it for a different reason; if it's already imported, don't add a duplicate).
```python
def test_edit_page_widget_empty_click_in_new_text_mode_opens_a_text_editor():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert widget._text_editor is not None
    assert widget._text_editor.isVisible()


def test_edit_page_widget_typing_and_committing_a_new_text_creates_an_element():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(widget._text_editor, "Hello World")
    widget._commit_text_editor()
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "new_text"
    assert el["text"] == "Hello World"
    assert el["page"] == 1


def test_edit_page_widget_blank_text_draft_is_discarded_not_committed():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(widget._text_editor, "   ")  # whitespace only
    widget._commit_text_editor()
    assert model.elements == []


def test_edit_page_widget_moving_a_new_text_element():
    model = EditElementsModel()
    el_id = model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    body = QPoint(int(w * 0.35), int(h * 0.32))  # inside the element's body
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 20, body.y() + 10))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 20, body.y() + 10))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(0.3 + 20 / w)
    assert el["y"] == pytest.approx(0.3 + 10 / h)
    assert model.selected_id == el_id


def test_edit_page_widget_resizing_a_new_text_element():
    model = EditElementsModel()
    el_id = model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    w, h = widget.width(), widget.height()
    el = model.elements[0]
    rect = widget._element_rect_px(el)
    handle_center = widget._resize_handles(el)["corner"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = model.elements[0]
    assert resized["width"] == pytest.approx(0.2 + 40 / w)
    assert resized["height"] == pytest.approx(0.1 + 40 / h)


def test_edit_page_widget_marker_click_deletes_a_new_text_element():
    model = EditElementsModel()
    el_id = model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    marker = widget._marker_rect(el)
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert model.elements == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k edit_page_widget -v`
Expected: FAIL — `EditPageWidget` doesn't exist yet.

- [ ] **Step 3: Implement `EditPageWidget` with `new_text` support**

Add these imports to the top of `app/ui/edit_canvas.py`:
```python
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QTextEdit, QWidget
```
Add these module-level constants (alongside `_PASTE_OFFSET`):
```python
_MARKER_SIZE = 14
_HANDLE_SIZE = 14
_MIN_TEXT_WIDTH_FRACTION = 0.05
_MIN_TEXT_HEIGHT_FRACTION = 0.03
```
Add this class at the end of the file:
```python
class EditPageWidget(QWidget):
    """One page's view onto a shared EditElementsModel - renders that
    page's own filtered elements via QPainter, dispatching by
    element["type"], and translates mouse events into calls on the shared
    model. Hit-test order (topmost-first, matching ImagePlacementWidget's
    proven convention): marker (delete) -> handle(s) (resize) -> body
    (move) -> empty space, which creates a new element of whichever type
    `self.create_mode` currently names. Existing elements of ANY type
    remain selectable/movable/resizable/deletable regardless of which
    creation mode is active - the mode only gates what an empty-space
    click does."""

    def __init__(self, model, page_number: int, parent=None):
        super().__init__(parent)
        self.model = model
        self.page_number = page_number
        self.page_pixmap = None
        self.create_mode = "new_text"
        self._drag: dict | None = None
        self._text_editor: QTextEdit | None = None
        self._editing_element_id: str | None = None
        self.model.on_change.append(self.update)

    def set_page_pixmap(self, pixmap) -> None:
        self.page_pixmap = pixmap
        self.setFixedSize(pixmap.size())
        self.update()

    def _elements(self) -> list[dict]:
        return self.model.elements_for_page(self.page_number)

    def _point_from_pos(self, pos) -> tuple[float, float] | None:
        if self.width() == 0 or self.height() == 0:
            return None
        x = min(max(pos.x() / self.width(), 0), 1)
        y = min(max(pos.y() / self.height(), 0), 1)
        return (x, y)

    def _element_rect_px(self, el: dict) -> QRect:
        x0 = el["x"] * self.width()
        y0 = el["y"] * self.height()
        x1 = (el["x"] + el["width"]) * self.width()
        y1 = (el["y"] + el["height"]) * self.height()
        return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def _marker_rect(self, el: dict) -> QRect:
        rect = self._element_rect_px(el)
        return QRect(rect.right() - _MARKER_SIZE, rect.top(), _MARKER_SIZE, _MARKER_SIZE)

    def _resize_handles(self, el: dict) -> dict:
        """One handle for new_text (free resize, bottom-right). Task 3
        adds a 3-handle set for "image" here."""
        rect = self._element_rect_px(el)
        if el["type"] == "new_text":
            return {"corner": QRect(rect.right() - _HANDLE_SIZE, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE)}
        return {}

    def _qfont_for(self, el: dict) -> QFont:
        font = QFont(el["family"], el["size"])
        font.setBold(el["bold"])
        font.setItalic(el["italic"])
        font.setUnderline(el["underline"])
        return font

    def mousePressEvent(self, e) -> None:
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
                    self._drag = {"mode": f"resize-{handle_name}", "id": el["id"], "start": point, "start_element": dict(el)}
                    return
        for i in reversed(range(len(elements))):
            el = elements[i]
            if self._element_rect_px(el).contains(pos):
                point = self._point_from_pos(pos)
                self.model.select(el["id"])
                self._drag = {"mode": "move", "id": el["id"], "start": point, "start_element": dict(el)}
                return
        point = self._point_from_pos(pos)
        if point is None:
            return
        if self.create_mode == "new_text":
            self._open_text_editor_for_new(point)

    def mouseDoubleClickEvent(self, e) -> None:
        pos = e.position().toPoint()
        for el in reversed(self._elements()):
            if el["type"] == "new_text" and self._element_rect_px(el).contains(pos):
                self._drag = None
                self._open_text_editor_for_existing(el)
                return

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        point = self._point_from_pos(e.position().toPoint())
        if point is None:
            return
        dx = point[0] - self._drag["start"][0]
        dy = point[1] - self._drag["start"][1]
        sp = self._drag["start_element"]
        if self._drag["mode"] == "move":
            x = min(max(sp["x"] + dx, 0), 1 - sp["width"])
            y = min(max(sp["y"] + dy, 0), 1 - sp["height"])
            self.model.update(self._drag["id"], x=x, y=y)
        elif self._drag["mode"] == "resize-corner":
            width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
            height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
            self.model.update(self._drag["id"], width=width, height=height)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is not None:
            self.model.commit()
            self._drag = None

    def _open_text_editor_for_new(self, point: tuple[float, float]) -> None:
        width, height = 0.25, 0.08
        x = min(max(point[0] - width / 2, 0), 1 - width)
        y = min(max(point[1] - height / 2, 0), 1 - height)
        self._editing_element_id = None
        self._show_text_editor(x, y, width, height, "", {
            "family": "helvetica", "bold": False, "italic": False,
            "underline": False, "size": 14, "color": "#1f2937", "align": "left",
        })

    def _open_text_editor_for_existing(self, el: dict) -> None:
        self._editing_element_id = el["id"]
        self._show_text_editor(el["x"], el["y"], el["width"], el["height"], el["text"], el)

    def _show_text_editor(self, x: float, y: float, width: float, height: float, text: str, style: dict) -> None:
        if self._text_editor is not None:
            self._text_editor.deleteLater()
        editor = QTextEdit(self)
        editor.setPlainText(text)
        editor.setFont(self._qfont_for({**style, "text": text}))
        rect = self._element_rect_px({"x": x, "y": y, "width": width, "height": height})
        editor.setGeometry(rect)
        editor.show()
        editor.setFocus()
        self._text_editor = editor
        self._pending_style = dict(style)
        self._pending_box = {"x": x, "y": y, "width": width, "height": height}

    def _commit_text_editor(self) -> None:
        if self._text_editor is None:
            return
        text = self._text_editor.toPlainText()
        editor = self._text_editor
        self._text_editor = None
        editor.deleteLater()
        if not text.strip():
            self._editing_element_id = None
            return
        element = {
            "page": self.page_number, "type": "new_text",
            "x": self._pending_box["x"], "y": self._pending_box["y"],
            "width": self._pending_box["width"], "height": self._pending_box["height"],
            "text": text, **{k: self._pending_style[k] for k in ("family", "bold", "italic", "underline", "size", "color", "align")},
        }
        if self._editing_element_id is not None:
            self.model.update(self._editing_element_id, **{k: v for k, v in element.items() if k != "page"})
            self.model.commit()
        else:
            self.model.add(element)
        self._editing_element_id = None

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.page_pixmap is not None:
            painter.drawPixmap(0, 0, self.page_pixmap)
        for el in self._elements():
            if el["type"] == "new_text":
                self._paint_new_text(painter, el)
            self._paint_chrome(painter, el)

    def _paint_new_text(self, painter: QPainter, el: dict) -> None:
        if self._editing_element_id == el["id"] and self._text_editor is not None:
            return  # the live QTextEdit overlay is showing instead
        rect = self._element_rect_px(el)
        painter.setFont(self._qfont_for(el))
        painter.setPen(QColor(el["color"]))
        align_flag = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[el["align"]]
        painter.drawText(rect, align_flag | Qt.AlignTop | Qt.TextWordWrap, el["text"])

    def _paint_chrome(self, painter: QPainter, el: dict) -> None:
        if self.model.selected_id != el["id"]:
            return
        marker = self._marker_rect(el)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QColor(220, 40, 40))
        painter.drawEllipse(marker)
        for rect in self._resize_handles(el).values():
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(40, 100, 220))
            painter.drawRect(rect)
```
Note `_commit_text_editor` is called explicitly by the tests (mirroring
how the dialog will wire it to the `QTextEdit`'s focus-out — since a real
`focusOutEvent` on a live `QTextEdit` child doesn't fire synthetically the
same way in an offscreen test as it does when the whole dialog is actually
shown, `EditPdfDialog` in Task 4 connects `editor.focusOutEvent`'s
equivalent — practically, an event filter or a direct call from wherever
the dialog detects an outside click — to call `_commit_text_editor()`;
these tests call it directly to prove the commit LOGIC itself is correct,
independent of exactly which Qt signal ends up triggering it in the real
running app).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k edit_page_widget -v`
Expected: PASS (6 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 1 plus 6.

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add the Edit PDF page widget with new_text support"
```

No trailer — `feat:`, not `fix:`.

---

### Task 3: `EditPageWidget` — `image` support

**Files:**
- Modify: `app/ui/edit_canvas.py` (extend `EditPageWidget`)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditPageWidget` (Task 2), extended in place.
- Produces: `EditPageWidget.create_mode = "image"` support; `.image_cache: dict[str, QPixmap]` (path -> loaded pixmap); `.create_image_at(x, y, image_path) -> str`; a new `on_image_click: Callable[[tuple[float, float]], None] | None = None` constructor parameter (called on an empty-space click while `create_mode == "image"`, since a page widget can't own its own file picker — the dialog does, and needs to know which page widget's click triggered it). Task 4 consumes the finished class, providing its own bound `on_image_click` per page widget.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def test_edit_page_widget_creating_an_image_element(tmp_path):
    from PySide6.QtGui import QPixmap as _QPixmap
    sig_pixmap = _QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "sig.png")
    sig_pixmap.save(sig_path, "PNG")

    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "image"
    w, h = widget.width(), widget.height()
    click = QPoint(int(w * 0.5), int(h * 0.5))
    widget.create_image_at(click.x() / w, click.y() / h, sig_path)
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "image"
    assert el["file_id"] == sig_path
    assert el["page"] == 1
    # 200x80 signature -> aspect 0.4 -> default width 0.25, height 0.1,
    # centered on the click point - same formula ImagePlacementWidget uses.
    assert el["width"] == pytest.approx(0.25)
    assert el["height"] == pytest.approx(0.1)
    assert el["x"] == pytest.approx(0.5 - 0.125)
    assert el["y"] == pytest.approx(0.5 - 0.05)


def test_edit_page_widget_image_corner_handle_resizes_with_locked_aspect(tmp_path):
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    handle_center = widget._resize_handles(el)["corner"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = next(e for e in model.elements if e["id"] == el_id)
    w = widget.width()
    expected_width = 0.2 + 40 / w
    assert resized["width"] == pytest.approx(expected_width)
    assert resized["height"] == pytest.approx(expected_width * 0.5)  # locked aspect 0.1/0.2 = 0.5


def test_edit_page_widget_image_width_only_handle_ignores_height():
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    handle_center = widget._resize_handles(el)["width"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))  # y-movement must be ignored
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = next(e for e in model.elements if e["id"] == el_id)
    w = widget.width()
    assert resized["width"] == pytest.approx(0.2 + 40 / w)
    assert resized["height"] == pytest.approx(0.1)  # unchanged


def test_edit_page_widget_image_height_only_handle_ignores_width():
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = model.elements[0]
    handle_center = widget._resize_handles(el)["height"].center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, handle_center)
    QTest.mouseMove(widget, QPoint(handle_center.x() + 40, handle_center.y() + 40))  # x-movement must be ignored
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(handle_center.x() + 40, handle_center.y() + 40))
    resized = next(e for e in model.elements if e["id"] == el_id)
    h = widget.height()
    assert resized["width"] == pytest.approx(0.2)  # unchanged
    assert resized["height"] == pytest.approx(0.1 + 40 / h)


def test_edit_page_widget_selecting_an_image_does_not_require_new_text_mode():
    # An existing image element must remain selectable/movable/deletable
    # even while create_mode is "new_text" - matching the web's "mode only
    # gates empty-space creation" behavior.
    model = EditElementsModel()
    el_id = model.add({"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.2, "height": 0.1, "file_id": "sig.png"})
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.create_mode = "new_text"  # deliberately the OTHER mode
    w, h = widget.width(), widget.height()
    marker = widget._marker_rect(model.elements[0])
    click = marker.center()
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, click)
    assert model.elements == []  # deleted, despite create_mode being "new_text"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "image and edit_page" -v`
Expected: FAIL — `_resize_handles` returns `{}` for `"image"`, `create_image_at` doesn't exist.

- [ ] **Step 3: Extend `EditPageWidget` with `image` support**

Add `QPixmap` to `app/ui/edit_canvas.py`'s existing `from PySide6.QtGui import ...` line. Add an `on_image_click` constructor parameter to `EditPageWidget.__init__` — since a page widget can't itself own a `QFileDialog` file picker (that's dialog-level UI, and the dialog needs to know WHICH page widget's click triggered it so it can call that widget's own `create_image_at`), an empty-space click in image mode calls this callback instead of creating anything directly:
```python
    def __init__(self, model, page_number: int, parent=None, on_image_click=None):
        super().__init__(parent)
        self.model = model
        self.page_number = page_number
        self.page_pixmap = None
        self.create_mode = "new_text"
        self.on_image_click = on_image_click
        self.image_cache: dict = {}
        self._drag: dict | None = None
        self._text_editor: QTextEdit | None = None
        self._editing_element_id: str | None = None
        self.model.on_change.append(self.update)
```
(this replaces Task 2's original `__init__` in full — the only changes are the new `on_image_click` parameter and the new `self.image_cache: dict = {}` line; every other line is unchanged from Task 2's version). Replace `_resize_handles` with:
```python
    def _resize_handles(self, el: dict) -> dict:
        """One handle for new_text (free resize, bottom-right). Three for
        image: a corner (aspect-locked uniform scale, matching
        ImagePlacementWidget's existing formula exactly), plus independent
        width-only and height-only handles (mid-right / mid-bottom edges)
        that deliberately allow aspect distortion, matching the web app's
        own three-handle image behavior (_apply_image's own
        keep_proportion=False trusts whatever box the editor produced)."""
        rect = self._element_rect_px(el)
        if el["type"] == "new_text":
            return {"corner": QRect(rect.right() - _HANDLE_SIZE, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE)}
        if el["type"] == "image":
            mid_x = rect.left() + rect.width() // 2
            mid_y = rect.top() + rect.height() // 2
            return {
                "corner": QRect(rect.right() - _HANDLE_SIZE, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE),
                "width": QRect(rect.right() - _HANDLE_SIZE, mid_y - _HANDLE_SIZE // 2, _HANDLE_SIZE, _HANDLE_SIZE),
                "height": QRect(mid_x - _HANDLE_SIZE // 2, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE),
            }
        return {}
```
Add `create_image_at` and extend `mousePressEvent`'s empty-space branch:
```python
    def create_image_at(self, x: float, y: float, image_path: str) -> str:
        pixmap = self.image_cache.get(image_path)
        if pixmap is None:
            pixmap = QPixmap(image_path)
            self.image_cache[image_path] = pixmap
        sig_w, sig_h = pixmap.width(), pixmap.height()
        width = 0.25
        height = min(0.9, width * (sig_h / sig_w))
        box_x = min(max(x - width / 2, 0), 1 - width)
        box_y = min(max(y - height / 2, 0), 1 - height)
        return self.model.add({
            "page": self.page_number, "type": "image",
            "x": box_x, "y": box_y, "width": width, "height": height,
            "file_id": image_path,
        })
```
In `mousePressEvent`, change the empty-space branch from:
```python
        if self.create_mode == "new_text":
            self._open_text_editor_for_new(point)
```
to:
```python
        if self.create_mode == "new_text":
            self._open_text_editor_for_new(point)
        elif self.create_mode == "image" and self.on_image_click is not None:
            self.on_image_click(point)
```
(the actual file-picker dialog is owned by `EditPdfDialog`, built in Task 4 — this widget only reports where the click landed via the callback; the dialog's own callback opens the picker and, if a file was chosen, calls this same widget's `create_image_at` back).

Extend `mouseMoveEvent`'s drag-mode branches to add the two new modes:
```python
        elif self._drag["mode"] == "resize-width":
            width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
            self.model.update(self._drag["id"], width=width)
        elif self._drag["mode"] == "resize-height":
            height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
            self.model.update(self._drag["id"], height=height)
```
(`resize-corner`'s existing branch, written in Task 2 for `new_text`'s free resize, needs a small correction here: for `image`, the corner handle must be ASPECT-LOCKED, unlike `new_text`'s free resize. Change the existing `elif self._drag["mode"] == "resize-corner":` branch to check the element's own type):
```python
        elif self._drag["mode"] == "resize-corner":
            if sp["type"] == "image":
                aspect = sp["height"] / sp["width"]
                width_cap = min(1 - sp["x"], (1 - sp["y"]) / aspect)
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, width_cap))
                height = width * aspect
                self.model.update(self._drag["id"], width=width, height=height)
            else:
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
                height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
                self.model.update(self._drag["id"], width=width, height=height)
```
Finally, extend `paintEvent`'s per-type dispatch:
```python
            if el["type"] == "new_text":
                self._paint_new_text(painter, el)
            elif el["type"] == "image":
                self._paint_image(painter, el)
            self._paint_chrome(painter, el)
```
```python
    def _paint_image(self, painter: QPainter, el: dict) -> None:
        pixmap = self.image_cache.get(el["file_id"])
        if pixmap is None:
            pixmap = QPixmap(el["file_id"])
            self.image_cache[el["file_id"]] = pixmap
        painter.drawPixmap(self._element_rect_px(el), pixmap)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "image and edit_page" -v`
Expected: PASS (5 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 2 plus 5 — including every Task 2 test unmodified (the `resize-corner` change only ADDS an `image`-specific branch; `new_text`'s own free-resize path is unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add image element support to the Edit PDF page widget"
```

No trailer — `feat:`, not `fix:`.

---

### Task 4: `EditPdfDialog`

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (add the new class)
- Modify: `app/main.py` (import line, registration line)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditElementsModel`, `EditPageWidget` (Tasks 1-3), unchanged.
- Produces: nothing consumed by another task (this is the last task in this plan — Phase 6B/6C add their own new dialog-level toolbar entries and `EditPageWidget` type-dispatch branches later, without needing to revisit this task's own code).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def test_edit_pdf_dialog_places_new_text_and_image_across_pages_and_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    sig_pixmap = QPixmap(200, 80)
    sig_pixmap.fill(Qt.blue)
    sig_path = str(tmp_path / "sig.png")
    sig_pixmap.save(sig_path, "PNG")

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    assert len(dlg._page_widgets) == 2

    page1 = dlg._page_widgets[0]
    page1.create_mode = "new_text"
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(page1._text_editor, "New text element")
    page1._commit_text_editor()

    page2 = dlg._page_widgets[1]
    page2.create_image_at(0.3, 0.3, sig_path)

    assert len(dlg.model.elements) == 2

    # Undo the image placement, then redo it, proving the model's history
    # survives into the actual export.
    dlg.model.undo()
    assert len(dlg.model.elements) == 1
    dlg.model.redo()
    assert len(dlg.model.elements) == 2

    params = dlg.gather_params()
    output_paths = dlg.run_operation([str(input_path)], params)
    result = fitz.open(output_paths[0])
    page1_text = result[0].get_text()
    page2_images = result[1].get_images()
    result.close()
    assert "New text element" in page1_text
    assert len(page2_images) == 1


def test_edit_pdf_dialog_undo_redo_and_delete_keyboard_shortcuts(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    page1 = dlg._page_widgets[0]
    page1.create_mode = "new_text"
    w, h = page1.width(), page1.height()
    click = QPoint(int(w * 0.3), int(h * 0.3))
    QTest.mousePress(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.mouseRelease(page1, Qt.LeftButton, Qt.NoModifier, click)
    QTest.keyClicks(page1._text_editor, "Some text")
    page1._commit_text_editor()
    assert len(dlg.model.elements) == 1

    dlg._handle_shortcut("undo")
    assert dlg.model.elements == []
    dlg._handle_shortcut("redo")
    assert len(dlg.model.elements) == 1

    dlg._handle_shortcut("delete")
    assert dlg.model.elements == []


def test_edit_pdf_dialog_arrow_key_nudges_the_selected_element(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    el_id = dlg.model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.05,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    dlg.model.select(el_id)
    QTest.keyClick(dlg, Qt.Key_Right)
    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(0.3 + 0.004)
    QTest.keyClick(dlg, Qt.Key_Down, Qt.ShiftModifier)
    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    assert el["y"] == pytest.approx(0.3 + 0.02)


def test_edit_pdf_dialog_shortcuts_are_suppressed_while_a_text_editor_is_open(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    el_id = dlg.model.add({
        "page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.1, "height": 0.05,
        "text": "Hi", "family": "helvetica", "bold": False, "italic": False,
        "underline": False, "size": 14, "color": "#000000", "align": "left",
    })
    dlg.model.select(el_id)
    page1 = dlg._page_widgets[0]
    page1._open_text_editor_for_existing(dlg.model.elements[0])
    assert page1._text_editor is not None
    # A "delete" shortcut fired while a text editor is still open (e.g. a
    # keyboard shortcut pressed mid-edit, before any real focus-out has
    # committed it) must be left for the QTextEdit itself to handle
    # (deleting a character), NOT deleted at the model level - matching
    # the web's own "any text-input-like element has focus" suppression
    # rule.
    dlg._handle_shortcut("delete")
    assert len(dlg.model.elements) == 1


def test_edit_pdf_dialog_gather_params_raises_when_no_elements_placed(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import EditPdfDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Some text")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = EditPdfDialog()
    dlg.on_files_changed([str(input_path)])
    params = dlg.gather_params()
    assert params["elements"] == []
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k edit_pdf_dialog -v`
Expected: FAIL (5 tests) — `EditPdfDialog` doesn't exist yet.

- [ ] **Step 3: Implement `EditPdfDialog`**

Add `edit_pdf` (already imported for `SignDialog`, confirm it's already on the `from app.core.pdf_ops import ...` line — do not duplicate) — no new `pdf_ops` import needed. Add `from app.ui.edit_canvas import EditElementsModel, EditPageWidget` as a new import line. Add `QScrollArea` to the existing `PySide6.QtWidgets` import line if not already present (check first — the Crop/Redact/Sign retrofit already added it). Add `QShortcut, QKeySequence` to the file's existing `from PySide6.QtGui import ...` line (they're in `QtGui`, not `QtWidgets`, in PySide6). Add this class at the end of the file:
```python
class EditPdfDialog(ToolDialog):
    title = "Edit PDF"
    dialog_size = (900, 800)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)

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
        layout.addLayout(mode_row)

        action_row = QHBoxLayout()
        undo_btn = QPushButton("Undo")
        undo_btn.clicked.connect(lambda: self._handle_shortcut("undo"))
        action_row.addWidget(undo_btn)
        redo_btn = QPushButton("Redo")
        redo_btn.clicked.connect(lambda: self._handle_shortcut("redo"))
        action_row.addWidget(redo_btn)
        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(lambda: self._handle_shortcut("copy"))
        action_row.addWidget(copy_btn)
        cut_btn = QPushButton("Cut")
        cut_btn.clicked.connect(lambda: self._handle_shortcut("cut"))
        action_row.addWidget(cut_btn)
        paste_btn = QPushButton("Paste")
        paste_btn.clicked.connect(lambda: self._handle_shortcut("paste"))
        action_row.addWidget(paste_btn)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(lambda: self._handle_shortcut("delete"))
        action_row.addWidget(delete_btn)
        layout.addLayout(action_row)

        reorder_row = QHBoxLayout()
        for label, direction in (("Bring to Front", "front"), ("Send to Back", "back"), ("Forward", "forward"), ("Backward", "backward")):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _, d=direction: self._reorder_selected(d))
            reorder_row.addWidget(btn)
        layout.addLayout(reorder_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        self.model = EditElementsModel()
        self._page_widgets: list[EditPageWidget] = []
        self._input_path: str | None = None

        for keys, action in (
            ("Ctrl+Z", "undo"), ("Ctrl+Y", "redo"),
            ("Ctrl+C", "copy"), ("Ctrl+X", "cut"), ("Ctrl+V", "paste"),
            ("Delete", "delete"), ("Backspace", "delete"),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda a=action: self._handle_shortcut(a))

    def _set_create_mode(self, mode: str) -> None:
        self.new_text_btn.setChecked(mode == "new_text")
        self.image_btn.setChecked(mode == "image")
        for widget in self._page_widgets:
            widget.create_mode = mode

    def _prompt_for_image(self, page_num: int, point: tuple[float, float]) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select image", "", "Image files (*.png *.jpg *.jpeg)")
        if not path:
            return
        self._page_widgets[page_num - 1].create_image_at(point[0], point[1], path)

    def _any_text_editor_open(self) -> bool:
        """Every model-level keyboard action (shortcuts AND arrow-key
        nudge) must be suppressed while ANY page's QTextEdit overlay is
        open for editing - e.g. Ctrl+C or Delete must edit the TEXT, not
        the model, matching the web's own "any text-input-like element
        has focus" suppression rule. Deliberately checks "is an editor
        currently open" rather than each editor's own .hasFocus() -
        confirmed empirically that QTextEdit.hasFocus() is unreliable
        under QT_QPA_PLATFORM=offscreen even after an explicit .show()/
        .setFocus() (real window activation never happens without a
        genuine event loop), so it's not a trustworthy signal in tests OR
        in the same code path this app already runs under for CI. "Open"
        is also the semantically right check for the real running app: a
        toolbar button click naturally commits the open editor (via its
        own focus-out) before the button's own click handler runs, so by
        the time _handle_shortcut executes, _text_editor is already back
        to None in that case - this check only actually matters for the
        case a real focus-out hasn't fired yet (e.g. a keyboard shortcut
        pressed while still actively typing). Centralized here so both
        _handle_shortcut and keyPressEvent share one check."""
        return any(w._text_editor is not None for w in self._page_widgets)

    def _handle_shortcut(self, action: str) -> None:
        if self._any_text_editor_open():
            return
        if action == "undo":
            self.model.undo()
        elif action == "redo":
            self.model.redo()
        elif action == "copy":
            self.model.copy()
        elif action == "cut":
            self.model.cut()
        elif action == "paste":
            self.model.paste()
        elif action == "delete":
            if self.model.selected_id is not None:
                self.model.remove(self.model.selected_id)

    def _reorder_selected(self, direction: str) -> None:
        if self.model.selected_id is not None:
            self.model.reorder(self.model.selected_id, direction)

    def keyPressEvent(self, e) -> None:
        arrow_deltas = {
            Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
            Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1),
        }
        if e.key() in arrow_deltas and not self._any_text_editor_open() and self.model.selected_id is not None:
            step = 0.02 if e.modifiers() & Qt.ShiftModifier else 0.004
            dx, dy = arrow_deltas[e.key()]
            self.model.nudge(self.model.selected_id, dx * step, dy * step)
            return
        super().keyPressEvent(e)

    def on_files_changed(self, paths: list[str]) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._page_widgets = []
        self.model = EditElementsModel()
        self._input_path = paths[0] if paths else None
        if self._input_path is None:
            return
        try:
            count = get_page_count(self._input_path)
        except PDFError:
            return
        for page_num in range(1, count + 1):
            try:
                thumb_bytes = render_page_thumbnail(self._input_path, page_num, max_size=450)
            except PDFError:
                continue
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            widget = EditPageWidget(self.model, page_num, on_image_click=lambda point, pn=page_num: self._prompt_for_image(pn, point))
            # addWidget (reparenting) BEFORE set_page_pixmap: keeps the
            # widget a real child of a shown container from the moment it
            # exists, rather than sitting unparented in between.
            self._container_layout.addWidget(widget)
            widget.set_page_pixmap(pixmap)
            self._page_widgets.append(widget)

    def gather_params(self) -> dict:
        elements = [{k: v for k, v in el.items() if k != "id"} for el in self.model.elements]
        image_paths = {el["file_id"]: el["file_id"] for el in elements if el["type"] == "image"}
        return {"elements": elements, "image_paths": image_paths}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_edited.pdf"))
        edit_pdf(input_path, out_path, params["elements"], params["image_paths"])
        return [out_path]
```
`_prompt_for_image` is the dialog-level counterpart to `EditPageWidget`'s
`on_image_click` callback (Task 3): each page widget is constructed with
its own bound callback (capturing that widget's own `page_num`), so
clicking empty space in image mode on ANY page widget immediately opens
the file picker and, once a file is chosen, places the image on exactly
the page the click happened on. Add `QFileDialog` to `edit_dialogs.py`'s
existing `PySide6.QtWidgets` import line if not already present (it
should already be there from `SignDialog`).

- [ ] **Step 4: Register `EditPdfDialog` in `app/main.py`**

Change the import line (currently ending `..., FillFormDialog, CompareDialog`):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog, RedactDialog, SignDialog, FillFormDialog, CompareDialog, EditPdfDialog
```
Add this line directly after `window.add_tool("Edit", "Compare PDF", CompareDialog)`:
```python
    window.add_tool("Edit", "Edit PDF", EditPdfDialog)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (all tests in the file, including this task's 5 new ones).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 3 plus 5.

- [ ] **Step 6: Commit**

```bash
git add app/ui/edit_canvas.py app/ui/dialogs/edit_dialogs.py app/main.py tests/test_ui_desktop.py
git commit -m "feat: add an Edit PDF dialog to the desktop app (new_text and image elements)"
```

No trailer — `feat:`, not `fix:`.

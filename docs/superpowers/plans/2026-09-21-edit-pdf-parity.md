# Edit PDF Parity + One-Row Toolbar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the desktop Edit PDF to parity with the web app's new drawing tools (dots for short strokes, drawing-wins, Eraser, freehand highlighter, Select with group move/delete), and put the Edit PDF toolbar on ONE row in both the web and desktop apps.

**Architecture:** Both apps share the export engine (`app/core/pdf_ops.edit_pdf`, which already accepts stroke `opacity`), so this is UI work. The desktop keeps its `EditElementsModel` (shared state) and `EditPageWidget` (per-page view); group operations are added to the model, pure geometry goes in a new Python module ported from `web/frontend/src/editGeometry.js`, and the widget/dialog gain the new tools. The toolbar rework touches `EditPdfCanvas.jsx` + `index.css` (web) and `EditPdfDialog` + `theme.py` (desktop).

**Tech Stack:** PySide6, pytest + QTest (offscreen), React 18, Vite, vitest.

## Global Constraints

- Element shapes are shared with the web and the exporter: a stroke is `{"page", "type": "stroke", "points": [{"x","y"}...], "color", "width"}` plus optional `"opacity"` (0 < opacity <= 1). Coordinates are page fractions 0-1. A highlighter stroke has `opacity` 0.4 and widths 8 / 14 / 24 pt.
- Colours/tokens come from `app/ui/theme.py` (mirrors the web CSS tokens).
- Commit trailers (`Co-Authored-By: ...`) go ONLY on commits whose subject starts with `fix:`; `feat:`/`build:`/`docs:`/`chore:` commits carry none. (User's standing instruction.)
- Existing tests must keep passing (`pytest -q`, `npm test` in `web/frontend`).
- Tests never touch the real Recent Files DB (autouse fixture in `tests/conftest.py`).
- Web behaviour being mirrored: strokes are selectable only with Select; Draw and Eraser ignore existing elements on press; switching mode clears selection; one Undo step per gesture (sweep / group move / group delete); copy/cut/paste stay single-element.
- Toolbar: ONE row containing modes, undo/redo, arrange (z-order) and the active mode's options. Modes are icon buttons; only the active mode shows its label. Order and names (web order): Select, Edit Text, Draw, Shapes, Highlight, Insert Image, Add Text, Eraser.

---

### Task 1: Geometry module and group operations in the model

**Files:**
- Create: `app/core/edit_geometry.py`
- Modify: `app/ui/edit_canvas.py` (`EditElementsModel`)
- Test: `tests/test_edit_geometry.py`, append to `tests/test_ui_desktop.py`

**Interfaces:**
- Produces (`app/core/edit_geometry.py`), all in page fractions:
  - `element_bounds(el: dict, text_edit_box: dict | None = None) -> dict | None` returning `{"left","top","right","bottom"}`; `text_edit_box` is `{"x","y","width","height"}` (the shape `EditElementsModel.text_edit_box` returns); a `text_edit` without a box gives `None`.
  - `rects_intersect(a, b) -> bool`, `rect_from_points(p, q)` (points are `(x, y)` tuples), `union_bounds(rects) -> dict | None`, `clamp_move(bounds, dx, dy) -> (dx, dy)`, `polyline_near_point(points, point, radius_px, page_w_px, page_h_px) -> bool` (`points` is a list of `{"x","y"}` dicts, `point` an `(x, y)` tuple).
- Produces (`EditElementsModel`):
  - `selected_ids: list[str]` (the marquee/group selection; independent of `selected_id`).
  - `element_bounds_for(el) -> dict | None` (bounds incl. text_edit via `text_edit_box`).
  - `select_many(ids: list[str]) -> None` (sets `selected_ids`, clears `selected_id`, notifies).
  - `clear_selection() -> None` (clears both, notifies).
  - `delete_selected_group() -> None` (one commit; removes every id in `selected_ids`; clears selection).
  - `translate_group(ids, dx, dy, base: list[dict] | None = None) -> None` live-moves each listed element by the group-clamped delta from `base` (a snapshot list of the pre-gesture elements; defaults to the current elements) with NO commit.
  - `nudge_group(dx, dy) -> None` one commit, moves `selected_ids` by the group-clamped delta.

- [ ] **Step 1: Write the failing geometry tests** in `tests/test_edit_geometry.py` mirroring `web/frontend/src/editGeometry.test.js` (bounds for stroke/shape/highlight/new_text/text_edit, intersects, rect_from_points, union incl. empty -> None, clamp_move, polyline_near_point incl. pixel-scaling and single-point dot).
- [ ] **Step 2: Run them; expect ImportError.** `venv/Scripts/python.exe -m pytest tests/test_edit_geometry.py -q`
- [ ] **Step 3: Implement `app/core/edit_geometry.py`** as a direct port of `editGeometry.js`.
- [ ] **Step 4: Run; expect pass.**
- [ ] **Step 5: Write failing model tests** (append to `tests/test_ui_desktop.py`): select_many sets ids and clears single selection; delete_selected_group removes all and is ONE undo step; translate_group clamps the group as a whole at the page edge and mixes types (stroke + shape + highlight + image); nudge_group is one undo step; text_edit without a loaded run is skipped, not crashed on.
- [ ] **Step 6: Implement the model methods**, reusing `clamped_translate` for each element after clamping the shared delta with `clamp_move`.
- [ ] **Step 7: Run the whole suite** (`venv/Scripts/python.exe -m pytest -q`), then commit: `feat: geometry helpers and group operations for the desktop Edit PDF` (no trailer).

---

### Task 2: Draw changes - dots, drawing wins, highlighter, Eraser (desktop)

**Files:**
- Modify: `app/ui/edit_canvas.py` (`EditPageWidget`), `app/ui/dialogs/edit_dialogs.py` (`EditPdfDialog`)
- Test: append to `tests/test_ui_desktop.py`

**Interfaces:**
- Consumes: Task 1 `polyline_near_point`.
- Produces: `EditPageWidget.create_mode` gains `"eraser"`; `EditPageWidget.draw_tool` (`"pen"` | `"marker"`), `marker_color`, `marker_width_preset`; `EditPdfDialog` sub-tool switch (`pen_btn`, `marker_btn`) inside Draw's options.

Behaviour (each gets a QTest test, offscreen):
- A press-release in Draw with no movement adds a 1-point stroke; a 2-pixel jitter stroke is kept.
- In Draw and Eraser mode a press on top of an existing element of ANY type starts drawing / erasing and never selects or moves it; in Select/other modes strokes are not hit-testable (no select, no drag) but other types behave as today.
- Marker stroke stores `opacity: 0.4`, colour from the marker palette, width 8/14/24; painted with alpha + round caps at `width * px_per_pt`.
- Eraser: a sparse jump (mouse events far apart) still erases every stroke the segment crosses; strokes are hidden while sweeping; release commits ONE undo step; one Undo restores all; Redo re-erases; non-stroke elements are never erased.
- Switching mode clears `selected_id`/`selected_ids`.
- End-to-end: draw a marker stroke + a dot, run `edit_pdf` via `gather_params`/`run_operation`, assert via PyMuPDF the exported page has translucent yellow pixels where the marker was and a dark dot where the dot was.

Commit: `feat: dots, drawing-wins, freehand highlighter and eraser in the desktop Edit PDF`.

---

### Task 3: Select tool - marquee, group move, delete, nudge (desktop)

**Files:**
- Modify: `app/ui/edit_canvas.py`, `app/ui/dialogs/edit_dialogs.py`
- Test: append to `tests/test_ui_desktop.py`

**Interfaces:**
- Consumes: Task 1 model group API, `rects_intersect`, `rect_from_points`, `union_bounds`.
- Produces: `create_mode == "select"`.

Behaviour (QTest):
- Drag on empty space draws a dashed marquee; on release every element on that page whose bounds intersect it becomes `selected_ids` (strokes, highlights, shapes, images, new_text, text_edit with a loaded run). A sub-0.5% drag is a plain click that clears selection.
- Selected members get an outline; pressing inside the group's union box and dragging moves the group (clamped as a whole, one undo step, live feedback via `translate_group`).
- Delete/Backspace deletes the group (one undo step); arrows nudge (Shift = big step); Esc clears; Undo after each restores exactly.
- A click on a single element in Select mode still selects/moves/resizes it as before (strokes included, via their bbox).
- Selection made on one page can't leak across pages: a new marquee replaces the old selection.

Commit: `feat: Select tool with group move and delete in the desktop Edit PDF`.

---

### Task 4: One-row toolbar - desktop

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (`EditPdfDialog.build_preview`), `app/ui/theme.py`
- Add icons: `cursor`, `cursor-text`, `pencil-simple`, `rectangle`, `highlighter`, `image-square`, `text-aa`, `eraser`, `arrow-u-up-left`, `arrow-u-up-right`, `stack-simple` (copy from `@phosphor-icons/core` regular set into `app/ui/assets/icons/`).
- Test: append to `tests/test_ui_desktop.py`

Behaviour:
- One horizontal bar: mode icon buttons (checkable; the active one shows its label, others icon-only with a tooltip), a divider, Undo/Redo icon buttons (disabled when their stacks are empty), an "Arrange" menu button with Bring to Front / Forward / Backward / Send to Back, Copy/Cut/Paste/Delete as icon buttons, a divider, then the ACTIVE mode's options inline (Draw: Pen|Highlighter + colours + widths; Shapes: type + colours + width + fill; Highlight: colours; Edit Text: style row when a run is open). The bar scrolls horizontally rather than wrapping when the window is narrow.
- Mode order/names: Select, Edit Text, Draw, Shapes, Highlight, Insert Image, Add Text, Eraser (rename "New Text" -> "Add Text").
- Existing attribute names used by tests (`new_text_btn`, `draw_btn`, ...) keep working or the tests are updated in the same commit; behaviour tests must still pass.
- Test: the bar's parent layout has exactly one toolbar row (no separate action/reorder rows); every mode button exists in the web's order; switching mode swaps the inline options.

Commit: `feat: one-row Edit PDF toolbar in the desktop app`.

---

### Task 5: One-row toolbar - web

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`, `web/frontend/src/index.css`

Behaviour: `edit-pdf-canvas__modes`, `__history-bar`, `__zorder-bar` and the active mode's `__style-bar` become ONE flex row (`flex-wrap: nowrap; overflow-x: auto`): mode icon buttons (active shows its label), divider, Undo/Redo icon buttons, an Arrange dropdown (Bring to front / Forward / Backward / Send to back, disabled when nothing selected), divider, the active mode's options inline. Existing behaviour and keyboard shortcuts unchanged. Verify in the browser at 1100 px and 700 px wide: one row, no wrapping, horizontal scroll at 700.

Commit: `feat: one-row Edit PDF toolbar in the web app`.

---

### Task 6: Verify, document, release

- [ ] Full `pytest -q`, `npm test`, `npm run build`.
- [ ] Offscreen desktop screenshots of Edit PDF (each mode) next to browser screenshots of the web app; fix visible mismatches.
- [ ] CHANGELOG entry for the release; README note.
- [ ] Bump `VERSION` (0.17.0), commit `chore:`, tag, watch the pipeline, confirm both installers publish.

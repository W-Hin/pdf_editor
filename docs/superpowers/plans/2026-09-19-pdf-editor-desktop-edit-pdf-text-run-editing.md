# Desktop App: Edit PDF, Phase 6C (In-Place Text-Run Editing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the desktop Edit PDF dialog edit an *existing* text run of the source PDF in place — the `text_edit` element type — using one unified rich-text editor, reusing the Phase 6A/6B `EditElementsModel`/`EditPageWidget`/`EditPdfDialog` foundation.

**Architecture:** The model gains per-page text-run data (`set_page_text_info`) and one geometry function (`text_edit_box`) that every consumer — hit-testing, painting, drag, nudge — shares, so a `text_edit`'s box is *always derived* from its run and never stored. `EditPageWidget` gains a run-editor (a `QTextEdit` overlay whose `QTextDocument` fragments convert directly to the `segments` list `edit_pdf` expects), an "Edit Text" creation mode gating double-click-on-a-run, and painting that mirrors what export will do (white-out the original run, draw the replacement). `EditPdfDialog` loads runs on file open, adds the 6th "Edit Text" mode button plus a style row (family/size/bold/italic/Revert), and — fixing a lifecycle gap that already affects Phase 6A's `new_text` — commits any open editor before `gather_params`.

**Tech Stack:** PySide6 (`QTextEdit`, `QTextDocument`, `QTextCursor`, `QTextCharFormat`, `QPainter`, `QTest`), PyMuPDF (`fitz`) via the existing `app.core.pdf_ops`, pytest.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task in this plan ships new behavior — commits are `feat:` and must **not** carry the trailer (or any attribution line), regardless of any generic instruction elsewhere.
- Real automated pytest tests using `PySide6.QtTest`, appended to the existing `tests/test_ui_desktop.py` — no second UI test file. The single core helper added in Task 1 is tested in the existing `tests/test_pdf_ops.py`. Tests use `tmp_path`; never write fixtures into the working directory.
- `app/core/pdf_ops.py`'s `extract_text_runs`, `_page_text_spans`, `_apply_text_edit` and `edit_pdf` are **unchanged** (already implemented, already tested). The one permitted core change is adding a small *new* function `get_page_size` (Task 1) — needed because the desktop must convert PDF points to thumbnail pixels for font sizes, and no existing helper exposes a page's size.
- **`text_edit` element shape (verified against the real core):** `{page, type: "text_edit", run_index, segments, [x, y]}`. `segments` is a list of `{text, family, bold, italic, size}`; `family` ∈ `{helvetica, times, courier}`; `size` is in **PDF points**. **No `width`/`height` is ever stored** — the box is always derived from the run. `x`/`y` (top-left of the displayed box, page fractions) are **either both present or both absent** (`edit_pdf` rejects one without the other: "Text position requires both x and y."); they exist only after the element has been moved. There are **no per-segment colours** — the core reuses the original run's colour.
- **One `text_edit` per `(page, run_index)`.** Verified empirically: two `text_edit` elements for the same run are BOTH drawn (overlapping text). Editing a run that already has a `text_edit` must *update* that element, never add a second.
- **Empty text is a real erase:** committing an editor whose document is empty produces one segment with empty text in the run's own default style (`[{"text": "", ...}]`). Verified: `edit_pdf` erases the original run and inserts nothing (an empty `segments` list behaves the same, but one empty segment matches the web app).
- **Unchanged-from-original is a no-op:** if no `text_edit` exists yet for the run and the committed segments are a single segment equal to the run's own text in the run's own default style (`closest base-14 family`, run `size`, run `bold`/`italic`), nothing is added — opening and closing the editor must not pollute `elements` or undo history.
- **Default style of a run:** family from `closest_base14_family(run["font"])` — a port of the web's `closestBase14Family` (`web/frontend/src/components/EditPdfCanvas.jsx:87`): lowercase font name containing `times`/`serif`/`georgia` → `"times"`; containing `courier`/`mono`/`consolas` → `"courier"`; else `"helvetica"`. `bold`/`italic`/`size` come straight from the run.
- **Run geometry:** `extract_text_runs` returns each run's `bbox` as inset-from-edges fractions `{top, left, right, bottom}` in *displayed* (rotation-applied) space; box width = `1 - left - right`, height = `1 - top - bottom`; top-left = `(left, top)`. Reuse the inset convention already used by highlights; do not reinvent it.
- **Moved boxes on 90°/270° pages swap dimensions in POINTS, not fractions.** The core draws a moved replacement upright in displayed space (`rotate=page.rotation`), so its extent is the transpose of the (sideways) original run's. The web swaps the *fractions*, which is only right for a square page; this plan converts to points with the page's displayed size `(W, H)`: `new_width_frac = height_frac * H / W`, `new_height_frac = width_frac * W / H`. An **unmoved** box is never swapped (it is still drawn in the original run's own orientation).
- **Known, accepted preview limitations (export is authoritative):** (1) the export shrinks replacement text that is wider than the original run to fit (never below 50%, `_TEXT_EDIT_SHRINK_FACTOR`); the on-screen preview draws the typed size unshrunk. (2) On a page with non-zero rotation the preview draws upright text at the box's top-left even for an *unmoved* edit (the export keeps the original run's own orientation). (3) The preview uses whatever system fonts Qt resolves for `helvetica`/`times`/`courier`, not the PDF base-14 metrics.
- **Preview size scale:** on-screen pixel size of a segment = `size_pt * px_per_pt`, where `px_per_pt = widget.width() / page_width_pt` (displayed page width). The segment's *true* PDF-point size is stored on the `QTextCharFormat` as a custom property so the round trip is exact (verified: `QTextFormat.UserProperty + 1` holds a float; `QTextFormat.FontPixelSize` sets the display size independent of screen DPI).
- **Verified Qt quirk:** after select-all + Delete, `QTextEdit` drops the character format, so text typed next is format-less. `segments_from_document` therefore falls back to the run's default `family`/`size` (and `bold`/`italic` False) for any fragment lacking them, and the editor document's default font is set from the run's default style so it also *displays* correctly. (`selectAll` followed directly by typing keeps the selection's format — verified.) `QTest.mouseDClick` sends only the double-click event (no press/release), which is enough for `mouseDoubleClickEvent` tests.
- **Single-line editor:** runs are single spans, so the run editor must not accept line breaks — a `QTextEdit` subclass ignores Return/Enter (verified: Return otherwise creates a second block), and the segment walk joins any remaining blocks with a single space defensively.
- **Clipboard exclusion:** `text_edit` is excluded from copy **and cut** — both are complete no-ops for it (a cut that copied nothing but still deleted would silently destroy the edit). Paste is therefore unreachable for it.
- **Paint order mirrors export:** `edit_pdf` applies every `text_edit` first and everything else afterwards in array order, so `paintEvent` paints `text_edit` elements in their own first pass, before the other element types.
- **Editor commit path (lessons from the 6A final review):** a typed editor is committed by (a) `mousePressEvent` (already true for `new_text`), (b) `EditPdfDialog.gather_params()` — *the user clicking Run without first clicking the page* — and (c) dialog toolbar-button actions and mode switches. Keyboard shortcuts stay suppressed while an editor is open (Ctrl+C/Delete edit the text). Before this plan (b) and (c) did not exist and a typed `new_text` draft was silently lost when the user clicked Run; Task 4 fixes that for both editor kinds.
- **Test gotchas known in this repo:** `QPoint(0, 0)` is a *null* QPoint and `QTest.mouseMove` silently substitutes the widget centre — use `QPoint(0, 1)` or larger; `QShortcut` never fires under `QT_QPA_PLATFORM=offscreen` (call `_handle_shortcut` or use `QTest.keyClick(widget, key)`); `QTextEdit.hasFocus()` is unreliable offscreen (use "is an editor open"); never call `show()` on an unparented widget in a test without `close()` (leaked windows hang the suite); every mutate-type test must also **export** through the real `edit_pdf` (a 6B move shipped producing coordinates that failed export for the whole document).
- **Mouse handling:** left button only (existing guards in `mousePressEvent`/`mouseReleaseEvent` must keep working); no gesture may leave `_drag`/an editor stranded.
- **Undo:** commit-before-mutate for every mutation; a zero-change gesture pushes no undo step. Moves go through the existing `_apply_drag` lazy-commit path.

---

### Task 1: Page text-run data on the model, run geometry, and `get_page_size`

**Files:**
- Modify: `app/core/pdf_ops.py` (add `get_page_size` next to `get_page_rotation`)
- Modify: `app/ui/edit_canvas.py` (model: text-run store, `closest_base14_family`, `text_edit_box`, `text_edit` branches in `clamped_translate`, `copy`/`cut` exclusion)
- Test: `tests/test_pdf_ops.py` (append one test), `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditElementsModel` as it exists after Phase 6B (`add/update/remove/select/commit/undo/redo/copy/cut/paste/reorder/clamped_translate/nudge`).
- Produces (for Tasks 2-4):
  - `pdf_ops.get_page_size(path: str, page_number: int) -> tuple[float, float]` — displayed page `(width_pt, height_pt)`.
  - Module function `closest_base14_family(font_name: str) -> str` in `app/ui/edit_canvas.py`.
  - `EditElementsModel.text_runs: dict[int, list[dict]]`, `.page_info: dict[int, dict]` (`{"rotation": int, "width_pt": float, "height_pt": float}`), and `.set_page_text_info(page: int, runs: list[dict], rotation: int, width_pt: float, height_pt: float) -> None`.
  - `EditElementsModel.find_run(page: int, run_index: int) -> dict | None`.
  - `EditElementsModel.text_edit_for_run(page: int, run_index: int) -> dict | None` (the pending `text_edit` element for a run, or `None`).
  - `EditElementsModel.text_edit_box(el: dict) -> dict | None` returning `{"x", "y", "width", "height"}` in page fractions, or `None` if the run is unknown.
  - `clamped_translate` handles `"text_edit"` and returns `{"x", "y"}` (never `width`/`height`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py`:
```python
def test_get_page_size_returns_the_displayed_size_including_rotation(tmp_path):
    from app.core.pdf_ops import get_page_size

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    path = tmp_path / "a.pdf"
    doc.save(str(path))
    doc.close()
    assert get_page_size(str(path), 1) == (595.0, 842.0)

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.set_rotation(90)
    rotated = tmp_path / "r.pdf"
    doc.save(str(rotated))
    doc.close()
    assert get_page_size(str(rotated), 1) == (842.0, 595.0)  # displayed, not raw


def test_get_page_size_rejects_a_missing_page(tmp_path):
    from app.core.pdf_ops import get_page_size

    doc = fitz.open()
    doc.new_page()
    path = tmp_path / "a.pdf"
    doc.save(str(path))
    doc.close()
    with pytest.raises(PDFError):
        get_page_size(str(path), 5)
```
(If `tests/test_pdf_ops.py` does not already import `fitz`, `pytest` and `PDFError`, add whichever of `import fitz`, `import pytest`, `from app.core.errors import PDFError` it lacks to its existing import block — check first.)

Append to `tests/test_ui_desktop.py` (the file already imports `EditElementsModel`, `pytest`, `fitz`, `QPoint`, `Qt`, `QPixmap`, `QTest`; extend the existing `from app.ui.edit_canvas import (...)` block with `closest_base14_family`):
```python
def _run(index=0, text="Hello", font="Helvetica", size=14.0, bold=False, italic=False,
         top=0.1, left=0.2, right=0.5, bottom=0.8):
    return {"index": index, "text": text, "font": font, "size": size, "bold": bold,
            "italic": italic, "bbox": {"top": top, "left": left, "right": right, "bottom": bottom}}


def _text_edit_element(page=1, run_index=0, text="Edited", **extra):
    el = {"page": page, "type": "text_edit", "run_index": run_index,
          "segments": [{"text": text, "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]}
    el.update(extra)
    return el


def test_closest_base14_family_matches_the_web_apps_rules():
    assert closest_base14_family("Times-Roman") == "times"
    assert closest_base14_family("DejaVuSerif") == "times"
    assert closest_base14_family("Georgia") == "times"
    assert closest_base14_family("Courier-Bold") == "courier"
    assert closest_base14_family("Consolas") == "courier"
    assert closest_base14_family("LucidaMono") == "courier"
    assert closest_base14_family("Helvetica") == "helvetica"
    assert closest_base14_family("Arial") == "helvetica"
    assert closest_base14_family("") == "helvetica"
    assert closest_base14_family(None) == "helvetica"


def test_edit_model_stores_page_text_info_and_finds_runs():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0), _run(1, text="Second")], rotation=0, width_pt=595, height_pt=842)
    assert model.find_run(1, 1)["text"] == "Second"
    assert model.find_run(1, 9) is None
    assert model.find_run(2, 0) is None
    assert model.page_info[1] == {"rotation": 0, "width_pt": 595, "height_pt": 842}


def test_edit_model_text_edit_box_defaults_to_the_runs_own_box_and_moves_with_xy():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0, top=0.1, left=0.2, right=0.5, bottom=0.8)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    el = next(e for e in model.elements if e["id"] == el_id)
    box = model.text_edit_box(el)
    assert box == pytest.approx({"x": 0.2, "y": 0.1, "width": 0.3, "height": 0.1})
    el.update(x=0.4, y=0.5)
    moved = model.text_edit_box(el)
    assert moved == pytest.approx({"x": 0.4, "y": 0.5, "width": 0.3, "height": 0.1})  # rotation 0: no swap
    assert model.text_edit_box({"page": 1, "type": "text_edit", "run_index": 9, "segments": []}) is None


def test_edit_model_text_edit_box_swaps_dimensions_in_points_when_moved_on_a_rotated_page():
    model = EditElementsModel()
    # displayed page 842 x 595 (a 90-degree page); the run is tall and narrow (sideways text)
    model.set_page_text_info(1, [_run(0, top=0.121, left=0.876, right=0.101, bottom=0.719)], rotation=90, width_pt=842, height_pt=595)
    el_id = model.add(_text_edit_element())
    el = next(e for e in model.elements if e["id"] == el_id)
    unmoved = model.text_edit_box(el)
    assert unmoved["width"] == pytest.approx(1 - 0.876 - 0.101)
    assert unmoved["height"] == pytest.approx(1 - 0.121 - 0.719)  # never swapped while unmoved
    el.update(x=0.3, y=0.3)
    moved = model.text_edit_box(el)
    w_pt, h_pt = unmoved["width"] * 842, unmoved["height"] * 595
    assert moved["width"] == pytest.approx(h_pt / 842)  # transposed extent, converted back to fractions
    assert moved["height"] == pytest.approx(w_pt / 595)


def test_edit_model_clamped_translate_for_text_edit_returns_only_xy_and_clamps_to_the_page():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0, top=0.1, left=0.2, right=0.5, bottom=0.8)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    el = next(e for e in model.elements if e["id"] == el_id)
    changes = model.clamped_translate(el, 0.1, 0.1)
    assert set(changes) == {"x", "y"}
    assert changes["x"] == pytest.approx(0.3) and changes["y"] == pytest.approx(0.2)
    far = model.clamped_translate(el, 5.0, 5.0)  # far past the bottom-right
    assert far["x"] == pytest.approx(1 - 0.3) and far["y"] == pytest.approx(1 - 0.1)
    away = model.clamped_translate(el, -5.0, -5.0)
    assert away["x"] == pytest.approx(0.0) and away["y"] == pytest.approx(0.0)


def test_edit_model_nudge_moves_a_text_edit_and_never_stores_width_or_height():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    model.nudge(el_id, 0.02, 0.0)
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(0.22) and el["y"] == pytest.approx(0.1)
    assert "width" not in el and "height" not in el
    model.undo()
    reverted = next(e for e in model.elements if e["id"] == el_id)
    assert "x" not in reverted and "y" not in reverted  # nudge was its own undo step


def test_edit_model_text_edit_for_run_finds_the_pending_edit():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0), _run(1)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element(run_index=1))
    assert model.text_edit_for_run(1, 1)["id"] == el_id
    assert model.text_edit_for_run(1, 0) is None
    assert model.text_edit_for_run(2, 1) is None


def test_edit_model_copy_and_cut_are_complete_no_ops_for_a_text_edit():
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0)], rotation=0, width_pt=595, height_pt=842)
    el_id = model.add(_text_edit_element())
    model.select(el_id)
    model.copy()
    assert model._clipboard is None
    model.cut()
    assert [e["id"] for e in model.elements] == [el_id]  # NOT deleted
    assert model.selected_id == el_id
    assert model.paste() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_ops.py -k get_page_size -v` and `pytest tests/test_ui_desktop.py -k "text_edit or base14 or page_text_info" -v`
Expected: FAIL — `get_page_size`, `closest_base14_family`, `set_page_text_info`, `text_edit_box` etc. don't exist yet.

- [ ] **Step 3: Implement**

In `app/core/pdf_ops.py`, add directly after `get_page_rotation` (which ends at its `finally: doc.close()`):
```python
def get_page_size(path: str, page_number: int) -> tuple[float, float]:
    """The DISPLAYED (rotation-applied) size of a page in PDF points - the
    same rect extract_text_runs' fractions are relative to."""
    doc = open_pdf(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFError(f"Page {page_number} does not exist in this document ({doc.page_count} pages).")
        rect = doc[page_number - 1].rect
        return (float(rect.width), float(rect.height))
    finally:
        doc.close()
```

In `app/ui/edit_canvas.py`, add this module-level function right after the constants block (after `_WIDTH_PRESETS`):
```python
def closest_base14_family(font_name) -> str:
    """Port of the web app's closestBase14Family (EditPdfCanvas.jsx:87): the
    core can only draw replacement text in the three base-14 families, so a
    run's detected font is snapped to the nearest one."""
    lowered = (font_name or "").lower()
    if "times" in lowered or "serif" in lowered or "georgia" in lowered:
        return "times"
    if "courier" in lowered or "mono" in lowered or "consolas" in lowered:
        return "courier"
    return "helvetica"
```

In `EditElementsModel.__init__`, add (after `self.on_change: list = []`):
```python
        # Per-page text-run data, filled by whoever opens a document (see
        # set_page_text_info). Kept on the model - not on the page widgets -
        # because clamped_translate/nudge need a text_edit's box and the
        # model is the single source of truth for move math.
        self.text_runs: dict[int, list[dict]] = {}
        self.page_info: dict[int, dict] = {}
```

Add these methods to `EditElementsModel` (place them right after `elements_for_page`):
```python
    def set_page_text_info(self, page: int, runs: list[dict], rotation: int, width_pt: float, height_pt: float) -> None:
        self.text_runs[page] = list(runs)
        self.page_info[page] = {"rotation": rotation, "width_pt": width_pt, "height_pt": height_pt}

    def find_run(self, page: int, run_index: int) -> dict | None:
        return next((r for r in self.text_runs.get(page, []) if r["index"] == run_index), None)

    def text_edit_for_run(self, page: int, run_index: int) -> dict | None:
        return next(
            (e for e in self.elements if e["type"] == "text_edit" and e["page"] == page and e["run_index"] == run_index),
            None,
        )

    def text_edit_box(self, el: dict) -> dict | None:
        """The box a text_edit occupies, in page fractions - ALWAYS derived
        from its run (a text_edit never stores width/height). Position is
        the element's own x/y once it has been moved, else the run's
        top-left. Once moved on a 90/270 page the core draws the replacement
        upright in displayed space, transposing the (sideways) original
        run's extent - swapped in POINTS, not fractions, so it is exact for
        a non-square page (the web app swaps the fractions)."""
        run = self.find_run(el["page"], el["run_index"])
        if run is None:
            return None
        bbox = run["bbox"]
        width = 1 - bbox["left"] - bbox["right"]
        height = 1 - bbox["top"] - bbox["bottom"]
        moved = el.get("x") is not None and el.get("y") is not None
        info = self.page_info.get(el["page"])
        if moved and info and info["rotation"] in (90, 270):
            w_pt, h_pt = width * info["width_pt"], height * info["height_pt"]
            width, height = h_pt / info["width_pt"], w_pt / info["height_pt"]
        return {
            "x": el["x"] if moved else bbox["left"],
            "y": el["y"] if moved else bbox["top"],
            "width": width,
            "height": height,
        }
```

In `EditElementsModel.clamped_translate`, add a `text_edit` branch right before the final `# new_text / image:` fallthrough:
```python
        if el_type == "text_edit":
            # Box comes from the run; only x/y are ever returned, so a
            # move can never leak width/height onto the stored element.
            box = self.text_edit_box(el)
            if box is None:
                return {}
            return {
                "x": min(max(box["x"] + dx, 0), 1 - box["width"]),
                "y": min(max(box["y"] + dy, 0), 1 - box["height"]),
            }
```

Replace `copy` and `cut` so `text_edit` is excluded:
```python
    def copy(self) -> None:
        if self.selected_id is None:
            return
        for el in self.elements:
            if el["id"] == self.selected_id:
                if el["type"] == "text_edit":
                    return  # a run_index is meaningless anywhere but its own run
                clip = dict(el)
                clip.pop("id", None)
                self._clipboard = clip
                return

    def cut(self) -> None:
        selected = next((e for e in self.elements if e["id"] == self.selected_id), None)
        if selected is not None and selected["type"] == "text_edit":
            return  # not copyable, so cutting would just destroy it
        self.copy()
        if self.selected_id is not None:
            self.remove(self.selected_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_ops.py -k get_page_size -v` → PASS.
Run: `pytest tests/test_ui_desktop.py -v` → PASS (whole file, including every pre-existing test).

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py app/ui/edit_canvas.py tests/test_pdf_ops.py tests/test_ui_desktop.py
git commit -m "feat: add text-run data and run geometry to the Edit PDF model"
```
No trailer — `feat:`, not `fix:`.

---

### Task 2: Run editing in `EditPageWidget` (Edit Text mode, rich editor, painting, move)

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes (Task 1): `model.find_run`, `model.text_edit_for_run`, `model.text_edit_box`, `model.text_runs`, `model.page_info`, `closest_base14_family`, `clamped_translate` for `text_edit`.
- Produces (for Task 3-4):
  - `EditPageWidget.create_mode` gains the value `"text"` ("Edit Text" mode); it only gates the double-click-on-a-run gesture.
  - `EditPageWidget.px_per_pt: float` (set by `set_page_pixmap` from `model.page_info`, default `1.0`).
  - `EditPageWidget._run_editor: _RunTextEdit | None`, `_editing_run: dict | None` (`{"run": run_dict}` while a run editor is open), and the module class `_RunTextEdit(QTextEdit)` (ignores Return/Enter).
  - `EditPageWidget.open_run_editor(run: dict) -> None`, `EditPageWidget.commit_open_editors() -> None` (commits BOTH kinds of open editor — `new_text` and run), `EditPageWidget.apply_run_style(**patch) -> None` (`family`/`bold`/`italic`/`size`, applied to the selection, or to the cursor's typing format when nothing is selected), `EditPageWidget.revert_run_editor() -> None`, `EditPageWidget.run_editor_state() -> dict | None` (`{"family", "bold", "italic", "size"}` at the cursor, for the dialog's style row).
  - Module functions `segments_from_document(doc: QTextDocument, default_style: dict) -> list[dict]` and `build_segments_document(segments, px_per_pt) -> QTextDocument`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py` (extend the `from app.ui.edit_canvas import (...)` block with `build_segments_document`, `segments_from_document`; add `from PySide6.QtGui import QTextCharFormat, QFont` to the file's existing PySide6 imports if missing):
```python
def _text_widget(model=None, runs=None, rotation=0, page=1, w=400, h=600):
    model = model or EditElementsModel()
    model.set_page_text_info(page, runs if runs is not None else [_run(0, text="Hello world", top=0.1, left=0.1, right=0.5, bottom=0.8)],
                             rotation=rotation, width_pt=595, height_pt=842)
    widget = EditPageWidget(model, page_number=page)
    widget.set_page_pixmap(QPixmap(w, h))
    widget.create_mode = "text"
    return model, widget


def _dclick_run(widget, run_index=0):
    run = widget.model.find_run(widget.page_number, run_index)
    b = run["bbox"]
    x = (b["left"] + (1 - b["right"])) / 2 * widget.width()
    y = (b["top"] + (1 - b["bottom"])) / 2 * widget.height()
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(x), int(y)))


def _fmt(family="helvetica", bold=False, italic=False, size=14.0, ppp=1.0):
    from PySide6.QtGui import QTextFormat
    f = QTextCharFormat()
    f.setFontFamilies([family])
    f.setFontWeight(QFont.Bold if bold else QFont.Normal)
    f.setFontItalic(italic)
    f.setProperty(QTextFormat.FontPixelSize, max(1, round(size * ppp)))
    f.setProperty(QTextFormat.UserProperty + 1, float(size))
    return f


_DEFAULT_STYLE = {"family": "helvetica", "bold": False, "italic": False, "size": 14.0}


def test_segments_from_document_walks_fragments_into_exact_segments():
    from PySide6.QtGui import QTextCursor
    doc = build_segments_document([], 1.0)
    cur = QTextCursor(doc)
    cur.insertText("Hello ", _fmt())
    cur.insertText("BOLD", _fmt(bold=True))
    cur.insertText(" and ", _fmt(italic=True))
    cur.insertText("plain", _fmt())
    cur.insertText("more", _fmt())  # identical neighbour - must merge
    cur.insertText("Mono", _fmt(family="courier", size=11.5))
    assert segments_from_document(doc, _DEFAULT_STYLE) == [
        {"text": "Hello ", "family": "helvetica", "bold": False, "italic": False, "size": 14.0},
        {"text": "BOLD", "family": "helvetica", "bold": True, "italic": False, "size": 14.0},
        {"text": " and ", "family": "helvetica", "bold": False, "italic": True, "size": 14.0},
        {"text": "plainmore", "family": "helvetica", "bold": False, "italic": False, "size": 14.0},
        {"text": "Mono", "family": "courier", "bold": False, "italic": False, "size": 11.5},
    ]


def test_segments_from_document_of_an_empty_document_is_one_empty_default_segment():
    doc = build_segments_document([], 1.0)
    assert segments_from_document(doc, _DEFAULT_STYLE) == [{"text": "", **_DEFAULT_STYLE}]


def test_build_segments_document_round_trips_segments_exactly():
    segs = [
        {"text": "a", "family": "times", "bold": True, "italic": False, "size": 12.0},
        {"text": "b", "family": "courier", "bold": False, "italic": True, "size": 9.5},
    ]
    doc = build_segments_document(segs, 0.534)
    assert segments_from_document(doc, _DEFAULT_STYLE) == segs


def test_segments_from_document_joins_multiple_blocks_with_a_single_space():
    from PySide6.QtGui import QTextCursor
    doc = build_segments_document([], 1.0)
    cur = QTextCursor(doc)
    cur.insertText("ab", _fmt())
    cur.insertBlock()
    cur.insertText("cd", _fmt())
    assert "".join(s["text"] for s in segments_from_document(doc, _DEFAULT_STYLE)) == "ab cd"


def test_double_click_on_a_run_in_edit_text_mode_opens_the_editor_seeded_with_the_run():
    model, widget = _text_widget()
    _dclick_run(widget)
    assert widget._run_editor is not None
    assert widget._run_editor.toPlainText() == "Hello world"
    assert model.elements == []  # opening adds nothing


def test_double_click_on_a_run_outside_edit_text_mode_does_nothing():
    model, widget = _text_widget()
    widget.create_mode = "new_text"
    _dclick_run(widget)
    assert widget._run_editor is None


def test_double_click_off_any_run_opens_nothing():
    model, widget = _text_widget()
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(widget.width() * 0.9), int(widget.height() * 0.9)))
    assert widget._run_editor is None


def test_opening_and_closing_an_untouched_run_editor_adds_no_element_and_no_undo_step():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget.commit_open_editors()
    assert widget._run_editor is None
    assert model.elements == []
    assert model._undo_stack == []


def test_editing_a_run_and_clicking_elsewhere_commits_a_text_edit_with_segments():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Brand new")
    # a real click on empty page space is the production commit path
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(widget.width() * 0.9), int(widget.height() * 0.9)))
    assert widget._run_editor is None
    assert len(model.elements) == 1
    el = model.elements[0]
    assert el["type"] == "text_edit" and el["run_index"] == 0 and el["page"] == 1
    assert el["segments"] == [{"text": "Brand new", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]
    assert "x" not in el and "y" not in el and "width" not in el and "height" not in el


def test_a_run_editor_edits_the_existing_text_edit_instead_of_adding_a_second():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "First")
    widget.commit_open_editors()
    _dclick_run(widget)
    assert widget._run_editor.toPlainText() == "First"  # reopened from the stored segments
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Second")
    widget.commit_open_editors()
    assert len(model.elements) == 1  # exactly one text_edit per run
    assert model.elements[0]["segments"][0]["text"] == "Second"


def test_editing_an_existing_text_edit_is_undoable_back_to_the_previous_text():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "First")
    widget.commit_open_editors()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Second")
    widget.commit_open_editors()
    model.undo()
    assert model.elements[0]["segments"][0]["text"] == "First"  # commit-before-mutate
    model.undo()
    assert model.elements == []


def test_reopening_a_styled_text_edit_rebuilds_its_rich_content():
    model, widget = _text_widget()
    segs = [
        {"text": "Hi ", "family": "helvetica", "bold": False, "italic": False, "size": 14.0},
        {"text": "there", "family": "times", "bold": True, "italic": True, "size": 12.0},
    ]
    model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs})
    _dclick_run(widget)
    assert segments_from_document(widget._run_editor.document(), _DEFAULT_STYLE) == segs


def test_an_intentionally_emptied_run_commits_as_a_real_erase():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClick(widget._run_editor, Qt.Key_Delete)
    widget.commit_open_editors()
    assert len(model.elements) == 1
    assert model.elements[0]["segments"] == [{"text": "", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]


def test_apply_run_style_restyles_only_the_selection():
    from PySide6.QtGui import QTextCursor
    model, widget = _text_widget(runs=[_run(0, text="abcdef", top=0.1, left=0.1, right=0.5, bottom=0.8)])
    _dclick_run(widget)
    cur = widget._run_editor.textCursor()
    cur.setPosition(2)
    cur.setPosition(4, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    widget.apply_run_style(bold=True)
    widget.commit_open_editors()
    assert [(s["text"], s["bold"]) for s in model.elements[0]["segments"]] == [("ab", False), ("cd", True), ("ef", False)]


def test_apply_run_style_with_no_selection_styles_what_is_typed_next():
    model, widget = _text_widget(runs=[_run(0, text="", top=0.1, left=0.1, right=0.5, bottom=0.8)])
    _dclick_run(widget)
    widget.apply_run_style(bold=True, family="times", size=20)
    QTest.keyClicks(widget._run_editor, "typed")
    widget.commit_open_editors()
    assert model.elements[0]["segments"] == [{"text": "typed", "family": "times", "bold": True, "italic": False, "size": 20.0}]


def test_revert_run_editor_discards_the_pending_edit_and_reseeds_from_the_run():
    model, widget = _text_widget()
    _dclick_run(widget)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Changed")
    widget.commit_open_editors()
    assert len(model.elements) == 1
    _dclick_run(widget)
    widget.revert_run_editor()
    assert model.elements == []
    assert widget._run_editor.toPlainText() == "Hello world"  # editor still open, reseeded
    widget.commit_open_editors()
    assert model.elements == []  # reverted and unchanged: still nothing


def test_opening_a_run_editor_and_moving_its_cursor_emit_the_style_row_signal():
    model, widget = _text_widget()
    seen = []
    widget.run_editor_cursor_moved.connect(lambda: seen.append(1))
    _dclick_run(widget)
    assert len(seen) >= 1  # emitted on open so the style row shows the run's style straight away
    before = len(seen)
    cur = widget._run_editor.textCursor()
    cur.setPosition(3)
    widget._run_editor.setTextCursor(cur)
    assert len(seen) > before


def test_run_editor_ignores_the_return_key():
    model, widget = _text_widget()
    _dclick_run(widget)
    QTest.keyClick(widget._run_editor, Qt.Key_Return)
    QTest.keyClick(widget._run_editor, Qt.Key_Enter)
    assert widget._run_editor.document().blockCount() == 1


def test_a_text_edit_is_selectable_and_movable_and_the_move_is_clamped_and_undoable():
    model, widget = _text_widget()
    el_id = model.add(_text_edit_element())
    w, h = widget.width(), widget.height()
    box = model.text_edit_box(model.elements[0])
    body = QPoint(int((box["x"] + box["width"] / 2) * w), int((box["y"] + box["height"] / 2) * h))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(body.x() + 30, body.y() + 20))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(body.x() + 30, body.y() + 20))
    el = next(e for e in model.elements if e["id"] == el_id)
    assert el["x"] == pytest.approx(box["x"] + 30 / w) and el["y"] == pytest.approx(box["y"] + 20 / h)
    assert "width" not in el and "height" not in el
    assert model.selected_id == el_id
    model.undo()
    assert "x" not in model.elements[0]  # back to un-moved

    # drag far past the top-left: must clamp to the page, not leave it
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(1, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    el = model.elements[0]
    assert 0 <= el["x"] <= 1 - box["width"] + 1e-9 and 0 <= el["y"] <= 1 - box["height"] + 1e-9


def test_a_zero_movement_click_on_a_text_edit_pushes_no_undo_step():
    model, widget = _text_widget()
    model.add(_text_edit_element())
    before = len(model._undo_stack)
    box = model.text_edit_box(model.elements[0])
    pt = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, pt)
    assert len(model._undo_stack) == before
    assert "x" not in model.elements[0]


def test_a_text_edit_dragged_against_its_own_clamp_does_not_pin_xy_without_a_move():
    # a box already flush with the top-left corner: dragging further up-left
    # changes nothing, so it must not add x/y or push an undo step
    model, widget = _text_widget(runs=[_run(0, top=0.0, left=0.0, right=0.7, bottom=0.9)])
    model.add(_text_edit_element())
    before = len(model._undo_stack)
    pt = QPoint(int(0.15 * widget.width()), int(0.05 * widget.height()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, pt)
    QTest.mouseMove(widget, QPoint(1, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    assert "x" not in model.elements[0] and len(model._undo_stack) == before


def test_a_text_edits_marker_click_removes_it_and_restores_the_original_run():
    model, widget = _text_widget()
    model.add(_text_edit_element())
    model.select(model.elements[0]["id"])
    marker = widget._marker_rect(model.elements[0])
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def test_a_text_edit_paints_the_replacement_and_whites_out_the_original_run():
    model, widget = _text_widget()
    pm = QPixmap(400, 600)
    pm.fill(Qt.black)  # a dark "page" so the white-out is unmistakable
    widget.set_page_pixmap(pm)
    run_box = model.find_run(1, 0)["bbox"]
    model.add({"page": 1, "type": "text_edit", "run_index": 0,
               "segments": [{"text": "", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]})
    img = widget.grab().toImage()
    cx = int(((run_box["left"] + (1 - run_box["right"])) / 2) * 400)
    cy = int(((run_box["top"] + (1 - run_box["bottom"])) / 2) * 600)
    assert img.pixelColor(cx, cy).lightness() > 200  # original run area painted white (erased)


def test_text_edit_elements_paint_before_other_elements_like_the_export_applies_them():
    model, widget = _text_widget()
    pm = QPixmap(400, 600)
    pm.fill(Qt.black)
    widget.set_page_pixmap(pm)
    run_box = model.find_run(1, 0)["bbox"]
    # a filled red rectangle covering the run, added BEFORE the text_edit in the array
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0,
               "color": "#ff0000", "width": 1, "filled": True})
    model.add({"page": 1, "type": "text_edit", "run_index": 0,
               "segments": [{"text": "", "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]})
    model.select(None)
    img = widget.grab().toImage()
    cx = int(((run_box["left"] + (1 - run_box["right"])) / 2) * 400)
    cy = int(((run_box["top"] + (1 - run_box["bottom"])) / 2) * 600)
    c = img.pixelColor(cx, cy)
    assert c.red() > 200 and c.green() < 60  # the shape is on top of the white-out, as in the export


def test_a_run_with_a_pending_edit_still_opens_by_double_click_on_its_element():
    model, widget = _text_widget()
    model.add(_text_edit_element(text="Pending"))
    box = model.text_edit_box(model.elements[0])
    pt = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mouseDClick(widget, Qt.LeftButton, Qt.NoModifier, pt)
    assert widget._run_editor is not None and widget._run_editor.toPlainText() == "Pending"
```

Also append the **mutate-then-export** end-to-end test for this task (it exercises the widget, model and the real core together):
```python
def test_run_edit_move_and_export_through_the_real_core(tmp_path):
    from app.core.pdf_ops import edit_pdf, extract_text_runs, get_page_size

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "First line of text", fontname="helv", fontsize=14)
    page.insert_text((72, 160), "Second line", fontname="helv", fontsize=12)
    src = tmp_path / "in.pdf"
    doc.save(str(src))
    doc.close()

    runs = extract_text_runs(str(src), 1)
    w_pt, h_pt = get_page_size(str(src), 1)
    model, widget = _text_widget(runs=runs)
    widget.px_per_pt = 400 / w_pt

    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Edited")
    widget.commit_open_editors()

    # drag it hard toward the top-left corner: must clamp, and must still export
    box = model.text_edit_box(model.elements[0])
    body = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(1, 1))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(1, 1))
    el = model.elements[0]
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1

    out = tmp_path / "out.pdf"
    elements = [{k: v for k, v in e.items() if k != "id"} for e in model.elements]
    edit_pdf(str(src), str(out), elements, {})
    result = fitz.open(str(out))
    text = result[0].get_text()
    result.close()
    assert "Edited" in text
    assert "First line of text" not in text  # the original run was erased
    assert "Second line" in text             # untouched runs survive
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "run_editor or text_edit or segments or double_click or apply_run_style or revert_run" -v`
Expected: FAIL — none of the run-editing machinery exists yet.

- [ ] **Step 3: Implement**

**3a. Imports** at the top of `app/ui/edit_canvas.py` — extend the two PySide6 lines (keep everything already there):
```python
from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygon,
    QTextCharFormat, QTextCursor, QTextDocument, QTextFormat,
)
from PySide6.QtWidgets import QTextEdit, QWidget
```

**3b. Module-level helpers**, placed after `closest_base14_family`:
```python
_PDF_SIZE_PROP = QTextFormat.UserProperty + 1  # a segment's TRUE size in PDF points


def _segment_format(segment: dict, px_per_pt: float) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontFamilies([segment["family"]])
    fmt.setFontWeight(QFont.Bold if segment["bold"] else QFont.Normal)
    fmt.setFontItalic(segment["italic"])
    # Display size in pixels (independent of screen DPI); the true PDF-point
    # size rides along as a custom property so the round trip is exact.
    fmt.setProperty(QTextFormat.FontPixelSize, max(1, round(segment["size"] * px_per_pt)))
    fmt.setProperty(_PDF_SIZE_PROP, float(segment["size"]))
    return fmt


def build_segments_document(segments: list[dict], px_per_pt: float) -> QTextDocument:
    """A QTextDocument holding `segments` in order - used both to seed the
    editor and to paint a committed edit, so the two can never disagree."""
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    cursor = QTextCursor(doc)
    for segment in segments:
        cursor.insertText(segment["text"], _segment_format(segment, px_per_pt))
    return doc


def segments_from_document(doc: QTextDocument, default_style: dict) -> list[dict]:
    """Walks the document block-by-block, fragment-by-fragment - each
    QTextFragment is already a maximal run of uniform formatting, i.e. one
    segment - merging any identical neighbours. Blocks (a run is a single
    line, and the editor refuses Return, so this is defensive) are joined by
    one space. An empty document is an intentional erase: one empty segment
    in the run's own default style."""
    segments: list[dict] = []

    def push(text, style):
        if segments and all(segments[-1][k] == style[k] for k in ("family", "bold", "italic", "size")):
            segments[-1]["text"] += text
        else:
            segments.append({"text": text, **style})

    block = doc.begin()
    first = True
    while block.isValid():
        if not first and segments:
            push(" ", {k: segments[-1][k] for k in ("family", "bold", "italic", "size")})
        first = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                fmt = frag.charFormat()
                families = fmt.fontFamilies()
                pdf_size = fmt.property(_PDF_SIZE_PROP)
                push(frag.text(), {
                    "family": families[0] if families else default_style["family"],
                    "bold": fmt.fontWeight() >= QFont.Bold,
                    "italic": fmt.fontItalic(),
                    "size": float(pdf_size) if pdf_size else float(default_style["size"]),
                })
            it += 1
        block = block.next()
    if not segments or all(s["text"] == "" for s in segments):
        return [{"text": "", **{k: default_style[k] for k in ("family", "bold", "italic", "size")}}]
    return segments


class _RunTextEdit(QTextEdit):
    """The in-place run editor. A run is a single text span, so line breaks
    are refused outright (verified: without this Return starts a second
    block)."""

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(e)
```

**3c. `EditPageWidget`** — add this class attribute directly under the class docstring (above `__init__`):
```python
    run_editor_cursor_moved = Signal()  # the dialog's style row listens to keep itself in step
```
and in `__init__`, add after `self.filled = False`:
```python
        self.px_per_pt = 1.0
        self._run_editor: _RunTextEdit | None = None
        self._editing_run: dict | None = None
```

**3d. `set_page_pixmap`** — replace with a version that derives the point-to-pixel scale:
```python
    def set_page_pixmap(self, pixmap) -> None:
        self.page_pixmap = pixmap
        self.setFixedSize(pixmap.size())
        info = self.model.page_info.get(self.page_number)
        if info and info["width_pt"]:
            self.px_per_pt = pixmap.width() / info["width_pt"]
        self.update()
```

**3e. Geometry** — replace `_element_rect_px`'s first lines so `text_edit` (derived box) is handled; change the head of the method to:
```python
    def _element_rect_px(self, el: dict) -> QRect:
        t = el.get("type")
        if t == "text_edit":
            box = self.model.text_edit_box(el)
            if box is None:
                return QRect()
            x0, y0, x1, y1 = box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"]
        elif t == "shape":
```
(i.e. insert the new `text_edit` branch first and turn the existing leading `if t == "shape":` into `elif t == "shape":`; the rest of the method is unchanged.)

In `_resize_handles` nothing changes: `text_edit` already falls through to `return {}` (move-only, matching the web).

**3f. Run helpers** — add to `EditPageWidget` (place them right after `_qfont_for`):
```python
    def _run_bbox_rect_px(self, run: dict) -> QRect:
        b = run["bbox"]
        x0, y0 = b["left"] * self.width(), b["top"] * self.height()
        x1, y1 = (1 - b["right"]) * self.width(), (1 - b["bottom"]) * self.height()
        return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def _run_at(self, pos) -> dict | None:
        """The detected run under `pos`, topmost (last) first."""
        for run in reversed(self.model.text_runs.get(self.page_number, [])):
            if self._run_bbox_rect_px(run).contains(pos):
                return run
        return None

    @staticmethod
    def _run_default_style(run: dict) -> dict:
        return {"family": closest_base14_family(run["font"]), "bold": run["bold"],
                "italic": run["italic"], "size": float(run["size"])}
```

**3g. Editor lifecycle** — add these methods (place them right after `_commit_text_editor`, and rename nothing existing):
```python
    def open_run_editor(self, run: dict) -> None:
        """Opens the unified rich-text editor over a detected run, seeded from
        the pending text_edit's segments if there is one, else from the run's
        own text in the run's own default style."""
        self.commit_open_editors()
        pending = self.model.text_edit_for_run(self.page_number, run["index"])
        default = self._run_default_style(run)
        segments = pending["segments"] if pending else [{"text": run["text"], **default}]
        editor = _RunTextEdit(self)
        editor.setFrameShape(QTextEdit.NoFrame)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setLineWrapMode(QTextEdit.NoWrap)
        doc = build_segments_document(segments, self.px_per_pt)
        doc.setParent(editor)  # QTextEdit does not own a parentless document; without this it can be collected mid-use
        # Verified: after select-all + Delete, Qt drops the character format,
        # so whatever is typed next is unformatted. The document's default font
        # is what such text displays in - set it to the run's own default style
        # (export already falls back to that same style for a format-less
        # fragment, see segments_from_document).
        default_font = QFont(default["family"])
        default_font.setPixelSize(max(1, round(default["size"] * self.px_per_pt)))
        default_font.setBold(default["bold"])
        default_font.setItalic(default["italic"])
        doc.setDefaultFont(default_font)
        editor.setDocument(doc)
        editor.setStyleSheet("QTextEdit { background: white; color: #1f2937; }")
        # typing continues in the style of the last segment (or the run's default)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.setTextCursor(cursor)
        editor.setCurrentCharFormat(_segment_format(segments[-1] if segments else {**default, "text": ""}, self.px_per_pt))
        rect = self._element_rect_px(pending) if pending else self._run_bbox_rect_px(run)
        # never narrower than a usable input, never past the page's right edge
        width = min(max(rect.width() + 8, 120), max(self.width() - rect.x(), 40))
        editor.setGeometry(rect.x(), rect.y(), width, max(rect.height() + 6, 20))
        editor.show()
        editor.setFocus()
        self._run_editor = editor
        self._editing_run = {"run": run, "default": default}
        editor.cursorPositionChanged.connect(self.run_editor_cursor_moved)
        self.run_editor_cursor_moved.emit()
        self.update()

    def _commit_run_editor(self) -> None:
        if self._run_editor is None:
            return
        editor, info = self._run_editor, self._editing_run
        self._run_editor = None
        self._editing_run = None
        run = info["run"]
        segments = segments_from_document(editor.document(), info["default"])
        editor.deleteLater()
        pending = self.model.text_edit_for_run(self.page_number, run["index"])
        default = info["default"]
        unchanged = (
            len(segments) == 1 and segments[0]["text"] == run["text"]
            and all(segments[0][k] == default[k] for k in ("family", "bold", "italic", "size"))
        )
        if pending is None and unchanged:
            self.update()
            return  # opened and closed without touching it: no element, no undo step
        if pending is not None:
            # commit() BEFORE update(): the snapshot must be the pre-edit
            # state so undo really restores the previous segments.
            self.model.commit()
            self.model.update(pending["id"], segments=segments)
        else:
            self.model.add({"page": self.page_number, "type": "text_edit", "run_index": run["index"], "segments": segments})
        self.update()

    def commit_open_editors(self) -> None:
        """Commits whichever editor is open (new_text or run). Safe to call
        with none open."""
        if self._text_editor is not None:
            self._commit_text_editor()
        if self._run_editor is not None:
            self._commit_run_editor()

    def apply_run_style(self, **patch) -> None:
        """Applies family/bold/italic/size to the run editor's SELECTION, or -
        with nothing selected - to the cursor's typing format, so the next
        characters typed take the style. No-op with no run editor open."""
        if self._run_editor is None:
            return
        fmt = QTextCharFormat()
        if "family" in patch:
            fmt.setFontFamilies([patch["family"]])
        if "bold" in patch:
            fmt.setFontWeight(QFont.Bold if patch["bold"] else QFont.Normal)
        if "italic" in patch:
            fmt.setFontItalic(patch["italic"])
        if "size" in patch:
            fmt.setProperty(QTextFormat.FontPixelSize, max(1, round(float(patch["size"]) * self.px_per_pt)))
            fmt.setProperty(_PDF_SIZE_PROP, float(patch["size"]))
        cursor = self._run_editor.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
            self._run_editor.setTextCursor(cursor)
        else:
            self._run_editor.mergeCurrentCharFormat(fmt)
        self._run_editor.setFocus()

    def run_editor_state(self) -> dict | None:
        """The style at the run editor's cursor (for the dialog's style row)."""
        if self._run_editor is None:
            return None
        fmt = self._run_editor.currentCharFormat()
        families = fmt.fontFamilies()
        size = fmt.property(_PDF_SIZE_PROP)
        default = self._editing_run["default"]
        return {
            "family": families[0] if families else default["family"],
            "bold": fmt.fontWeight() >= QFont.Bold,
            "italic": fmt.fontItalic(),
            "size": float(size) if size else default["size"],
        }

    def revert_run_editor(self) -> None:
        """Discards this run's pending text_edit (if any) and reseeds the
        still-open editor from the run's own original text and style."""
        if self._run_editor is None:
            return
        run, default = self._editing_run["run"], self._editing_run["default"]
        pending = self.model.text_edit_for_run(self.page_number, run["index"])
        if pending is not None:
            self.model.remove(pending["id"])
        doc = build_segments_document([{"text": run["text"], **default}], self.px_per_pt)
        doc.setParent(self._run_editor)
        self._run_editor.setDocument(doc)
        self._run_editor.setCurrentCharFormat(_segment_format({**default, "text": ""}, self.px_per_pt))
        self._run_editor.setFocus()
        self.update()
```

**3h. Wire the existing `new_text` commit call sites to the combined committer.** In `mousePressEvent`, replace
```python
        if self._text_editor is not None:
            self._commit_text_editor()
```
with
```python
        self.commit_open_editors()
```
and in `_show_text_editor` leave its own `_commit_text_editor()` call untouched.

**3i. Double-click** — replace `mouseDoubleClickEvent`:
```python
    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        for el in reversed(self._elements()):
            if el["type"] == "new_text" and self._element_rect_px(el).contains(pos):
                self._drag = None
                self._open_text_editor_for_existing(el)
                return
            if el["type"] == "text_edit" and self.create_mode == "text" and self._element_rect_px(el).contains(pos):
                run = self.model.find_run(self.page_number, el["run_index"])
                if run is not None:
                    self._drag = None
                    self.open_run_editor(run)
                return
        if self.create_mode == "text":
            run = self._run_at(pos)
            if run is not None:
                self._drag = None
                self.open_run_editor(run)
```

**3j. Move for `text_edit`** — in `mouseMoveEvent`'s `"move"` branch, the existing line
```python
            self._apply_drag(**self.model.clamped_translate(sp, dx, dy))
```
already routes `text_edit` through `clamped_translate` (Task 1). Add one guard directly above it so a drag that changes nothing never pins `x`/`y` or pushes a junk undo step (a `text_edit` without `x`/`y` looks "changed" to `_apply_drag` because `current.get("x")` is `None`):
```python
            changes = self.model.clamped_translate(sp, dx, dy)
            if sp["type"] == "text_edit" and sp.get("x") is None:
                box = self.model.text_edit_box(sp)
                if box is not None and changes.get("x") == box["x"] and changes.get("y") == box["y"]:
                    return  # clamped to exactly where it already is: no move
            self._apply_drag(**changes)
```
(and delete the original single-line `self._apply_drag(**self.model.clamped_translate(sp, dx, dy))` below it).

**3k. Painting.** Replace `paintEvent`:
```python
    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.page_pixmap is not None:
            painter.drawPixmap(0, 0, self.page_pixmap)
        elements = self._elements()
        # edit_pdf applies every text_edit FIRST and everything else after,
        # in array order - paint in that same order so the preview layers
        # the way the export will.
        for el in elements:
            if el["type"] == "text_edit":
                self._paint_text_edit(painter, el)
        for el in elements:
            if el["type"] == "new_text":
                self._paint_new_text(painter, el)
            elif el["type"] == "image":
                self._paint_image(painter, el)
            elif el["type"] == "shape":
                self._paint_shape(painter, el)
            elif el["type"] == "stroke":
                self._paint_stroke(painter, el)
            elif el["type"] == "highlight":
                self._paint_highlight(painter, el)
        for el in elements:
            self._paint_chrome(painter, el)
        self._paint_create_preview(painter)
```
and add the new painter method (place it right after `_paint_new_text`):
```python
    def _paint_text_edit(self, painter: QPainter, el: dict) -> None:
        run = self.model.find_run(el["page"], el["run_index"])
        if run is None:
            return
        # the export redacts the ORIGINAL run with a white fill, wherever the
        # replacement ends up - mirror that
        painter.fillRect(self._run_bbox_rect_px(run), QColor("white"))
        if self._editing_run is not None and self._editing_run["run"]["index"] == el["run_index"]:
            return  # the live editor overlay is showing this run's text
        rect = self._element_rect_px(el)
        doc = build_segments_document(el["segments"], self.px_per_pt)
        painter.save()
        painter.translate(rect.x(), rect.y())
        painter.setPen(QColor("#1f2937"))
        doc.drawContents(painter, QRectF(0, 0, max(rect.width(), int(doc.idealWidth()) + 1), max(rect.height(), 1)))
        painter.restore()
```
While the run editor is open on a run **with no pending `text_edit`** the original run must also be whited out under the overlay (the editor's own white background already covers the run's box, so nothing further is needed).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "run_editor or text_edit or segments or double_click or apply_run_style or revert_run or run_edit" -v` → PASS.
Run: `pytest tests/test_ui_desktop.py -v` → PASS (whole file, every pre-existing test).

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add in-place text-run editing to the Edit PDF page widget"
```
No trailer — `feat:`, not `fix:`.

---

### Task 3: Keyboard-nudge, delete and undo interplay for `text_edit`, plus the page-widget run wiring

**Files:**
- Modify: `app/ui/edit_canvas.py` (only if a test below fails)
- Test: `tests/test_ui_desktop.py` (append)

This task is a **verification task**: Tasks 1-2 already give `text_edit` nudge (via `clamped_translate`), delete, undo/redo and reorder for free. Its job is to *prove* each of those paths at the model/export level — including the mutate-then-export combination that the 6B review found missing — and to fix whatever the tests expose. (The dialog-level arrow-key and delete paths are proven in Task 4, where the dialog loads runs.) If every test below already passes against Task 2's code, this task's commit is the tests alone.

**Interfaces:**
- Consumes: everything from Tasks 1-2.
- Produces: nothing new.

- [ ] **Step 1: Write the tests**

Append to `tests/test_ui_desktop.py`:
```python
def _export(model, src, out):
    from app.core.pdf_ops import edit_pdf
    elements = [{k: v for k, v in e.items() if k != "id"} for e in model.elements]
    edit_pdf(str(src), str(out), elements, {})
    result = fitz.open(str(out))
    text = result[0].get_text()
    result.close()
    return text


def _two_run_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "First line of text", fontname="helv", fontsize=14)
    page.insert_text((72, 160), "Second line", fontname="helv", fontsize=12)
    src = tmp_path / "in.pdf"
    doc.save(str(src))
    doc.close()
    return src


def _model_for(src):
    from app.core.pdf_ops import extract_text_runs, get_page_size, get_page_rotation
    model = EditElementsModel()
    w, h = get_page_size(str(src), 1)
    model.set_page_text_info(1, extract_text_runs(str(src), 1), get_page_rotation(str(src), 1), w, h)
    return model


def test_nudging_a_text_edit_to_the_page_edge_stays_in_bounds_and_exports(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    el_id = model.add(_text_edit_element(text="Nudged"))
    for _ in range(400):  # far more than enough to hit the right edge
        model.nudge(el_id, 0.02, 0.02)
    el = next(e for e in model.elements if e["id"] == el_id)
    box = model.text_edit_box(el)
    assert box["x"] + box["width"] <= 1 + 1e-9 and box["y"] + box["height"] <= 1 + 1e-9
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1
    assert "width" not in el and "height" not in el
    assert "Nudged" in _export(model, src, tmp_path / "out.pdf")


def test_undo_and_redo_of_a_text_edit_round_trip_through_export(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add(_text_edit_element(text="Undone"))
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
               "color": "#ff0000", "width": 3, "filled": False})
    model.undo()  # removes the shape
    model.undo()  # removes the text_edit
    assert model.elements == []
    model.redo()
    assert "Undone" in _export(model, src, tmp_path / "o.pdf")


def test_a_text_edit_and_a_shape_on_the_same_page_export_together(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
               "color": "#ff0000", "width": 3, "filled": False})
    model.add(_text_edit_element(text="With shape"))
    text = _export(model, src, tmp_path / "o.pdf")
    assert "With shape" in text and "Second line" in text


def test_reordering_a_text_edit_never_breaks_the_export(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
               "color": "#ff0000", "width": 3, "filled": False})
    te = model.add(_text_edit_element(text="Reordered"))
    for direction in ("back", "forward", "front", "backward"):
        model.reorder(te, direction)
    assert "Reordered" in _export(model, src, tmp_path / "o.pdf")


def test_two_different_runs_each_get_their_own_text_edit_and_both_export(tmp_path):
    src = _two_run_pdf(tmp_path)
    model = _model_for(src)
    model.add(_text_edit_element(run_index=0, text="One"))
    model.add(_text_edit_element(run_index=1, text="Two"))
    text = _export(model, src, tmp_path / "o.pdf")
    assert "One" in text and "Two" in text
    assert "First line of text" not in text and "Second line" not in text
```

- [ ] **Step 2: Run tests to see which fail**

Run: `pytest tests/test_ui_desktop.py -k "nudging_a_text_edit or undo_and_redo_of_a_text_edit or text_edit_and_a_shape or reordering_a_text_edit or two_different_runs" -v`
Expected: all PASS against Tasks 1-2's code (this task's whole point is to prove those paths). Any FAIL is a real bug — fix it in Step 3.

- [ ] **Step 3: Implement only what the tests expose**

Expected code changes: none for the model-level tests. If `test_nudging_a_text_edit_to_the_page_edge_stays_in_bounds_and_exports` fails, the bug is in `clamped_translate`'s `text_edit` branch — fix it there (the box is derived, only `x`/`y` may be returned). If a reorder or undo test fails, fix `EditElementsModel` — do not special-case `text_edit` in the dialog.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_ui_desktop.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: cover text-edit nudge, delete, undo and reorder with export tests"
```
No trailer — `feat:`, not `fix:`. (If `edit_canvas.py` needed no change, `git add` of it is a no-op — that is fine.)

---

### Task 4: Dialog wiring — load runs, "Edit Text" mode, style row, and the commit-before-Run fix

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: Task 1 `model.set_page_text_info`, `pdf_ops.get_page_size`/`get_page_rotation`/`extract_text_runs`; Task 2 `EditPageWidget.create_mode == "text"`, `commit_open_editors`, `apply_run_style`, `run_editor_state`, `revert_run_editor`, `_run_editor`.
- Produces: nothing consumed by another task (last task).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py` (`_export`, `_two_run_pdf`, `_model_for`, `_text_edit_element`, `_run`, `_dclick_run` come from Tasks 1-3's tests):
```python
def _dialog_with_text(tmp_path, pages=1):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), "First line of text", fontname="helv", fontsize=14)
        page.insert_text((72, 160), "Second line", fontname="tiro", fontsize=12)
    src = tmp_path / "in.pdf"
    doc.save(str(src))
    doc.close()
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    return dlg, src


def test_edit_pdf_dialog_loads_each_pages_text_runs_and_scale_on_file_open(tmp_path):
    dlg, src = _dialog_with_text(tmp_path, pages=2)
    assert [r["text"] for r in dlg.model.text_runs[1]] == ["First line of text", "Second line"]
    assert dlg.model.page_info[2]["width_pt"] == 595 and dlg.model.page_info[2]["height_pt"] == 842
    assert dlg._page_widgets[0].px_per_pt == pytest.approx(dlg._page_widgets[0].width() / 595)


def test_edit_pdf_dialog_a_page_whose_runs_cannot_be_read_still_loads_without_runs(tmp_path, monkeypatch):
    from app.core.errors import PDFError
    import app.ui.dialogs.edit_dialogs as mod
    dlg, src = _dialog_with_text(tmp_path)

    def boom(path, page):
        raise PDFError("no text layer")
    monkeypatch.setattr(mod, "extract_text_runs", boom)
    dlg.on_files_changed([str(src)])
    assert len(dlg._page_widgets) == 1 and dlg.model.text_runs.get(1, []) == []


def test_edit_pdf_dialog_edit_text_mode_button_is_mutually_exclusive_with_the_others(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    assert dlg.edit_text_btn.isChecked() is True
    for other in (dlg.new_text_btn, dlg.image_btn, dlg.draw_btn, dlg.shapes_btn, dlg.highlight_btn):
        assert other.isChecked() is False
    assert dlg._page_widgets[0].create_mode == "text"
    assert dlg._text_options.isHidden() is False
    dlg._set_create_mode("shape")
    assert dlg.edit_text_btn.isChecked() is False and dlg._text_options.isHidden() is True


def test_edit_pdf_dialog_pages_opened_while_edit_text_is_active_inherit_that_mode(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    dlg.on_files_changed([str(src)])
    assert dlg._page_widgets[0].create_mode == "text"


def test_edit_pdf_dialog_edit_a_run_and_export_through_the_real_ui_path(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Rewritten")
    # the user clicks straight on Run - no click back on the page first
    params = dlg.gather_params()
    assert widget._run_editor is None  # gather_params committed the open editor
    assert [e["type"] for e in dlg.model.elements] == ["text_edit"]
    out = dlg.run_operation([str(src)], params)
    result = fitz.open(out[0])
    text = result[0].get_text()
    result.close()
    assert "Rewritten" in text and "First line of text" not in text and "Second line" in text


def test_edit_pdf_dialog_typed_new_text_is_not_lost_when_run_is_clicked_first(tmp_path):
    # Phase 6A shipped with this bug: a new_text draft only committed on the
    # next click on the PAGE, so clicking Run first silently dropped it.
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("new_text")
    widget = dlg._page_widgets[0]
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(int(widget.width() * 0.5), int(widget.height() * 0.6)))
    QTest.keyClicks(widget._text_editor, "Typed then Run")
    params = dlg.gather_params()
    assert widget._text_editor is None
    assert [e["type"] for e in dlg.model.elements] == ["new_text"]
    assert params["elements"][0]["text"] == "Typed then Run"


def test_edit_pdf_dialog_toolbar_buttons_commit_an_open_editor_before_acting(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Committed by button")
    dlg._toolbar_action("undo")  # a real toolbar click, not the (suppressed) keyboard shortcut
    assert widget._run_editor is None
    # commit pushed the edit, then undo took it back out
    assert dlg.model.elements == []


def test_edit_pdf_dialog_keyboard_shortcuts_stay_suppressed_while_a_run_editor_is_open(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    el_id = dlg.model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
                           "color": "#ff0000", "width": 3, "filled": False})
    dlg.model.select(el_id)
    dlg._handle_shortcut("delete")  # a keystroke that belongs to the text editor
    assert len(dlg.model.elements) == 1
    assert widget._run_editor is not None


def test_edit_pdf_dialog_style_row_restyles_the_selection_and_reflects_the_cursor(tmp_path):
    from PySide6.QtGui import QTextCursor
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    cur = widget._run_editor.textCursor()
    cur.setPosition(0)
    cur.setPosition(5, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    dlg.text_bold_btn.click()
    dlg.text_family_combo.setCurrentText("courier")
    dlg.text_size_spin.setValue(20)
    dlg.text_italic_btn.click()
    widget.commit_open_editors()
    first = dlg.model.elements[0]["segments"][0]
    assert first["text"] == "First" and first["bold"] is True and first["italic"] is True
    assert first["family"] == "courier" and first["size"] == 20.0
    # the rest of the run kept the run's own style
    assert dlg.model.elements[0]["segments"][1]["bold"] is False


def test_edit_pdf_dialog_style_row_follows_the_cursor_position(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    model = dlg.model
    model.add({"page": 1, "type": "text_edit", "run_index": 1, "segments": [
        {"text": "Plain ", "family": "helvetica", "bold": False, "italic": False, "size": 12.0},
        {"text": "Loud", "family": "times", "bold": True, "italic": False, "size": 18.0}]})
    _dclick_run(widget, 1)
    cur = widget._run_editor.textCursor()
    cur.setPosition(9)  # inside "Loud"
    widget._run_editor.setTextCursor(cur)
    dlg._sync_text_style_row()
    assert dlg.text_bold_btn.isChecked() is True
    assert dlg.text_family_combo.currentText() == "times"
    assert dlg.text_size_spin.value() == 18


def test_edit_pdf_dialog_revert_button_restores_the_original_run(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Changed")
    widget.commit_open_editors()
    _dclick_run(widget, 0)
    dlg.text_revert_btn.click()
    assert dlg.model.elements == []
    assert widget._run_editor.toPlainText() == "First line of text"


def test_edit_pdf_dialog_a_text_edit_moved_by_mouse_still_exports(tmp_path):
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Dragged")
    widget.commit_open_editors()
    box = dlg.model.text_edit_box(dlg.model.elements[0])
    body = QPoint(int((box["x"] + box["width"] / 2) * widget.width()), int((box["y"] + box["height"] / 2) * widget.height()))
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, body)
    QTest.mouseMove(widget, QPoint(widget.width() - 2, widget.height() - 2))
    QTest.mouseRelease(widget, Qt.LeftButton, Qt.NoModifier, QPoint(widget.width() - 2, widget.height() - 2))
    el = dlg.model.elements[0]
    assert 0 <= el["x"] <= 1 and 0 <= el["y"] <= 1 and "width" not in el
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    assert "Dragged" in result[0].get_text()
    result.close()


def test_edit_pdf_dialog_mixed_styling_end_to_end_lands_in_the_exported_pdf(tmp_path):
    from PySide6.QtGui import QTextCursor
    dlg, src = _dialog_with_text(tmp_path)
    dlg._set_create_mode("text")
    widget = dlg._page_widgets[0]
    _dclick_run(widget, 0)
    widget._run_editor.selectAll()
    QTest.keyClicks(widget._run_editor, "Plain and BOLD")
    cur = widget._run_editor.textCursor()
    cur.setPosition(10)
    cur.setPosition(14, QTextCursor.KeepAnchor)
    widget._run_editor.setTextCursor(cur)
    dlg.text_bold_btn.click()
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    spans = [s for b in result[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    result.close()
    by_text = {s["text"].strip(): s for s in spans}
    assert "Plain and" in by_text and "BOLD" in by_text
    assert by_text["BOLD"]["flags"] & 16          # bold font flag
    assert not by_text["Plain and"]["flags"] & 16
```

Also append these two dialog-level tests (they need the dialog to have loaded runs):
```python
def test_nudging_a_text_edit_through_the_dialogs_arrow_keys_exports(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    src = _two_run_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    el_id = dlg.model.add(_text_edit_element(text="Arrow nudged"))
    dlg.model.select(el_id)
    QTest.keyClick(dlg, Qt.Key_Right)
    QTest.keyClick(dlg, Qt.Key_Down, Qt.ShiftModifier)
    el = next(e for e in dlg.model.elements if e["id"] == el_id)
    box = dlg.model.text_edit_box({**el, "x": None, "y": None})  # the run's own top-left
    assert el["x"] == pytest.approx(box["x"] + 0.004)
    assert el["y"] == pytest.approx(box["y"] + 0.02)
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    assert "Arrow nudged" in result[0].get_text()
    result.close()


def test_deleting_a_text_edit_via_the_dialog_restores_the_original_run_on_export(tmp_path):
    from app.ui.dialogs.edit_dialogs import EditPdfDialog
    src = _two_run_pdf(tmp_path)
    dlg = EditPdfDialog()
    dlg.on_files_changed([str(src)])
    dlg.model.add(_text_edit_element(text="Temporary"))
    dlg.model.add({"page": 1, "type": "shape", "shape": "rectangle", "x0": 0.1, "y0": 0.5, "x1": 0.3, "y1": 0.6,
                   "color": "#ff0000", "width": 3, "filled": False})  # export needs some element left
    text_edit_id = dlg.model.elements[0]["id"]
    dlg.model.select(text_edit_id)
    dlg._handle_shortcut("delete")
    assert all(e["type"] != "text_edit" for e in dlg.model.elements)
    out = dlg.run_operation([str(src)], dlg.gather_params())
    result = fitz.open(out[0])
    text = result[0].get_text()
    result.close()
    assert "First line of text" in text and "Temporary" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "edit_pdf_dialog" -v`
Expected: FAIL — `edit_text_btn`, `_text_options`, `_toolbar_action`, `_sync_text_style_row`, `text_*` controls and run loading don't exist yet.

- [ ] **Step 3: Implement**

**3a. Imports** at the top of `app/ui/dialogs/edit_dialogs.py`: add `extract_text_runs`, `get_page_rotation`, `get_page_size` to the existing `from app.core.pdf_ops import ...` line; add `QSpinBox` to the existing `PySide6.QtWidgets` import if it is not already there (check first; do not duplicate).

**3b. Mode row + style row.** In `EditPdfDialog.build_preview`, right after the `highlight_btn` block (before `layout.addLayout(mode_row)`), add the sixth mode button:
```python
        self.edit_text_btn = QPushButton("Edit Text")
        self.edit_text_btn.setCheckable(True)
        self.edit_text_btn.clicked.connect(lambda: self._set_create_mode("text"))
        mode_row.addWidget(self.edit_text_btn)
```
and, right after the `self._highlight_options` block (before the `self._width_combos = ...` line), add the text style row:
```python
        self._text_options = QWidget()
        text_row = QHBoxLayout(self._text_options)
        self.text_family_combo = QComboBox()
        self.text_family_combo.addItems(["helvetica", "times", "courier"])
        self.text_family_combo.currentTextChanged.connect(lambda text: self._apply_text_style(family=text))
        text_row.addWidget(self.text_family_combo)
        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(4, 200)
        self.text_size_spin.setValue(12)
        self.text_size_spin.valueChanged.connect(lambda value: self._apply_text_style(size=value))
        text_row.addWidget(self.text_size_spin)
        self.text_bold_btn = QPushButton("B")
        self.text_bold_btn.setCheckable(True)
        self.text_bold_btn.setFocusPolicy(Qt.NoFocus)
        self.text_bold_btn.clicked.connect(lambda checked: self._apply_text_style(bold=checked))
        text_row.addWidget(self.text_bold_btn)
        self.text_italic_btn = QPushButton("I")
        self.text_italic_btn.setCheckable(True)
        self.text_italic_btn.setFocusPolicy(Qt.NoFocus)
        self.text_italic_btn.clicked.connect(lambda checked: self._apply_text_style(italic=checked))
        text_row.addWidget(self.text_italic_btn)
        self.text_revert_btn = QPushButton("Revert")
        self.text_revert_btn.setFocusPolicy(Qt.NoFocus)
        self.text_revert_btn.clicked.connect(self._revert_open_run)
        text_row.addWidget(self.text_revert_btn)
        layout.addWidget(self._text_options)
```
Set `self._text_options.setVisible(False)` alongside the three existing `setVisible(False)` calls.

**3c. Toolbar actions commit first.** Replace the six action-button connects and the four reorder connects so toolbar *clicks* go through `_toolbar_action` (keyboard shortcuts keep calling `_handle_shortcut` directly and stay suppressed while an editor is open):
```python
        undo_btn.clicked.connect(lambda: self._toolbar_action("undo"))
        redo_btn.clicked.connect(lambda: self._toolbar_action("redo"))
        copy_btn.clicked.connect(lambda: self._toolbar_action("copy"))
        cut_btn.clicked.connect(lambda: self._toolbar_action("cut"))
        paste_btn.clicked.connect(lambda: self._toolbar_action("paste"))
        delete_btn.clicked.connect(lambda: self._toolbar_action("delete"))
```
and the reorder buttons: `btn.clicked.connect(lambda _, d=direction: self._reorder_from_toolbar(d))`, with this method added next to `_toolbar_action`:
```python
    def _reorder_from_toolbar(self, direction: str) -> None:
        self._commit_open_editors()
        self._reorder_selected(direction)
```

**3d. New methods** on `EditPdfDialog` (place them after `_set_filled`):
```python
    def _commit_open_editors(self) -> None:
        for widget in self._page_widgets:
            widget.commit_open_editors()

    def _toolbar_action(self, action: str) -> None:
        """A toolbar CLICK (unlike a keyboard shortcut, whose keystroke
        belongs to an open text editor) finishes any open editor first so the
        click acts on the committed state. Before this existed the buttons
        silently did nothing while an editor was open, and a typed draft was
        never committed by them at all."""
        self._commit_open_editors()
        self._handle_shortcut(action)

    def _open_run_widget(self):
        return next((w for w in self._page_widgets if w._run_editor is not None), None)

    def _apply_text_style(self, **patch) -> None:
        widget = self._open_run_widget()
        if widget is not None:
            widget.apply_run_style(**patch)

    def _revert_open_run(self) -> None:
        widget = self._open_run_widget()
        if widget is not None:
            widget.revert_run_editor()
            self._sync_text_style_row()

    def _sync_text_style_row(self) -> None:
        """Shows the style at the open run editor's cursor in the row's
        controls (signals blocked so reading state never writes it back)."""
        widget = self._open_run_widget()
        state = widget.run_editor_state() if widget is not None else None
        if state is None:
            return
        for control in (self.text_family_combo, self.text_size_spin, self.text_bold_btn, self.text_italic_btn):
            control.blockSignals(True)
        self.text_family_combo.setCurrentText(state["family"])
        self.text_size_spin.setValue(int(round(state["size"])))
        self.text_bold_btn.setChecked(state["bold"])
        self.text_italic_btn.setChecked(state["italic"])
        for control in (self.text_family_combo, self.text_size_spin, self.text_bold_btn, self.text_italic_btn):
            control.blockSignals(False)
```
Keep the style row live: in `EditPdfDialog.on_files_changed`, right after creating each `EditPageWidget`, add `widget.run_editor_cursor_moved.connect(self._sync_text_style_row)` (the signal is declared and emitted by the widget in Task 2).

**3e. Mode switching.** In `_set_create_mode` add `self.edit_text_btn.setChecked(mode == "text")` and `self._text_options.setVisible(mode == "text")`, and call `self._commit_open_editors()` as its first line (switching tool finishes any open editor). `_widget_create_mode` already returns `self._create_mode` unchanged for `"text"` (only `"draw"` is translated), and `_active_style_tool` returns `None` for it, so no style push happens — nothing else to change there.

**3f. Load runs on file open.** In `on_files_changed`, right after `self.model = EditElementsModel()` and the `count = get_page_count(...)` block, and **before** each `widget.set_page_pixmap(pixmap)` (so `px_per_pt` is derived from `page_info`), add inside the per-page loop, just after the thumbnail try/except:
```python
            try:
                runs = extract_text_runs(self._input_path, page_num)
                width_pt, height_pt = get_page_size(self._input_path, page_num)
                rotation = get_page_rotation(self._input_path, page_num)
            except PDFError:
                runs, width_pt, height_pt, rotation = [], 0.0, 0.0, 0
            if width_pt:
                self.model.set_page_text_info(page_num, runs, rotation, width_pt, height_pt)
```
(A page whose runs cannot be read simply has no editable runs; the rest of the dialog still works.)

**3g. Commit before Run.** Replace `gather_params`:
```python
    def gather_params(self) -> dict:
        # THE production commit path for a typed draft when the user clicks
        # Run without first clicking back on the page. Without it, both
        # new_text and run-editor drafts were silently dropped.
        self._commit_open_editors()
        elements = [{k: v for k, v in el.items() if k != "id"} for el in self.model.elements]
        image_paths = {el["file_id"]: el["file_id"] for el in elements if el["type"] == "image"}
        return {"elements": elements, "image_paths": image_paths}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "edit_pdf_dialog or text_edit or run_edit or run_editor" -v` → PASS.
Run: `pytest tests/test_ui_desktop.py -v` → PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "feat: add an Edit Text mode with a rich-text run editor to the Edit PDF dialog"
```
No trailer — `feat:`, not `fix:`.

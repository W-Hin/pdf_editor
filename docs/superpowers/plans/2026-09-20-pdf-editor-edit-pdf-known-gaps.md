# Edit PDF Known Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four known gaps left after Phases 6A-6C of the desktop Edit PDF tool: text-edit preview vs export sizing, `text_edit` segment validation in the core, the invisible delete hotspot on every element type, and on-screen stroke/arrow/font sizes that don't match the export.

**Architecture:** One small core function (`text_edit_final_sizes`) becomes the single source of truth for how the export shrinks replacement text, and `_apply_text_edit` and the desktop preview both call it. `edit_pdf` gains a `text_edit` segments validator. The desktop widget gets a `px_per_pt` scale (already computed from the page size) applied to pen widths, arrowheads and `new_text` fonts, and the delete-marker hit-test is gated on selection for every type.

**Tech Stack:** PyMuPDF (`fitz`) in `app/core/pdf_ops.py`; PySide6 + QTest in `app/ui/edit_canvas.py`; pytest.

## Global Constraints

- **Commit rule for this plan:** all four tasks are fixes for known gaps, so every commit is a `fix:` commit and **carries** the trailer line `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` at the end of the message body (this project's rule: `fix:` commits carry it, `feat:`/`docs:` commits never do).
- Tests: core tests go in the existing `tests/test_pdf_ops.py`; UI tests are appended to `tests/test_ui_desktop.py` (no new test files); use `tmp_path`; real assertions; never `show()` an unparented widget without `close()`. Known Qt gotchas here: `QPoint(0, 0)` is a null point that `QTest.mouseMove` replaces with the widget centre; `QShortcut` doesn't fire offscreen.
- Do not run the full `pytest -q` suite as an implementer (the controller does); run targeted tests plus `pytest tests/test_ui_desktop.py -v` (UI tasks) or `pytest tests/test_pdf_ops.py -v` and `pytest tests/web -q` (core task).
- `_TEXT_EDIT_SHRINK_FACTOR = 0.5` and `_TEXT_EDIT_MIN_SIZE = 6` (`app/core/pdf_ops.py`) define how the export shrinks over-wide replacement text: total measured width of all segments (each in its base-14 font at its own size) over the ORIGINAL run's width in raw (unrotated) space; if wider, every segment's size is scaled by `max(0.5, original_width / total)`, and no segment goes below 6pt. The same scaling applies whether the edit is in place or moved (verified in the source: `scale` is computed before the override branch).
- The original run's width in raw space: for a page with rotation 0/180 it is the run's displayed width; for 90/270 it is the run's displayed *height* (raw and displayed axes are swapped). The desktop has the run as inset fractions of the displayed page plus the displayed page size in points (`model.page_info[page]` = `{"rotation", "width_pt", "height_pt"}`).
- Web contract to preserve: the web app's `TextSegment` (`web/backend/routes/tools.py:425`) is `{text: str, family: str, bold: bool, italic: bool, size: float > 0}`; `family` is an unconstrained string and unknown families deliberately fall back to helvetica in `_base14_alias` — so validation must NOT reject an unknown family. The web requires `segments` to be non-empty, but the desktop legitimately produces `[]`-equivalent (one empty-text segment) and the core already accepts an empty list (erase) — keep accepting it.
- `px_per_pt` on `EditPageWidget` is `widget.width() / page_width_pt` (set in `set_page_pixmap` from `model.page_info`; default `1.0` when unknown). On-screen pixel size = PDF points × `px_per_pt`.
- Preview limits that remain accepted after this plan: system fonts vs base-14 metrics (the preview measures with the real base-14 metrics for sizing, but draws with whatever Qt resolves), and on rotated pages an unmoved edit previews upright.

---

### Task 1: Core — `text_edit_final_sizes` and `text_edit` segment validation

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py` (append)

**Interfaces:**
- Consumes: existing `_base14_alias`, `_TEXT_EDIT_SHRINK_FACTOR`, `_TEXT_EDIT_MIN_SIZE`, `_apply_text_edit`, `edit_pdf`'s per-element validation loop.
- Produces: `text_edit_final_sizes(segments: list[dict], original_width: float) -> list[float]` (public, used by Task 2) and `_validate_text_edit_segments(el: dict) -> None` (called from `edit_pdf`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py` (it already imports `fitz`, `pytest`, `PDFError`, `edit_pdf`, `extract_text_runs`; add whichever it lacks):
```python
def _seg(text="x", family="helvetica", bold=False, italic=False, size=12):
    return {"text": text, "family": family, "bold": bold, "italic": italic, "size": size}


def _one_run_pdf(tmp_path, text="First line of text", size=14):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), text, fontname="helv", fontsize=size)
    path = tmp_path / "in.pdf"
    doc.save(str(path))
    doc.close()
    return path


def test_text_edit_final_sizes_leaves_text_that_fits_untouched():
    from app.core.pdf_ops import text_edit_final_sizes
    assert text_edit_final_sizes([_seg("Hi", size=12)], original_width=500) == [12]


def test_text_edit_final_sizes_shrinks_every_segment_by_the_same_factor():
    from app.core.pdf_ops import text_edit_final_sizes
    segs = [_seg("A" * 20, size=20), _seg("B" * 20, size=10, bold=True)]
    total = sum(fitz.get_text_length(s["text"], fontname=n, fontsize=s["size"])
                for s, n in zip(segs, ("helv", "hebo")))
    sizes = text_edit_final_sizes(segs, original_width=total / 2)
    assert sizes[0] == pytest.approx(10) and sizes[1] == pytest.approx(6)  # x0.5 (the floor), 6pt minimum
    assert sizes[1] >= 6


def test_text_edit_final_sizes_never_shrinks_below_half_or_six_points():
    from app.core.pdf_ops import text_edit_final_sizes
    sizes = text_edit_final_sizes([_seg("W" * 200, size=20)], original_width=10)
    assert sizes == [10.0]  # factor floors at 0.5
    assert text_edit_final_sizes([_seg("W" * 200, size=8)], original_width=10) == [6]  # 6pt floor beats 0.5


def test_text_edit_final_sizes_ignores_a_zero_original_width():
    from app.core.pdf_ops import text_edit_final_sizes
    assert text_edit_final_sizes([_seg("Hello", size=12)], original_width=0) == [12]


def test_text_edit_final_sizes_matches_what_the_export_actually_draws(tmp_path):
    from app.core.pdf_ops import text_edit_final_sizes
    src = _one_run_pdf(tmp_path)
    run = extract_text_runs(str(src), 1)[0]
    page_w = 595
    original_width = (1 - run["bbox"]["left"] - run["bbox"]["right"]) * page_w
    segs = [_seg("A much longer replacement than the original line held", size=14)]
    expected = text_edit_final_sizes(segs, original_width)[0]
    out = tmp_path / "out.pdf"
    edit_pdf(str(src), str(out), [{"page": 1, "type": "text_edit", "run_index": 0, "segments": segs}], {})
    doc = fitz.open(str(out))
    spans = [s for b in doc[0].get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    doc.close()
    assert spans[0]["size"] == pytest.approx(expected, abs=0.1)
    assert expected < 14  # it really did shrink


def test_edit_pdf_rejects_malformed_text_edit_segments_with_a_clean_error(tmp_path):
    src = _one_run_pdf(tmp_path)
    bad = [
        "not a list",
        [123],
        [{"text": "x", "family": "helvetica", "bold": False, "italic": False}],            # no size
        [{"text": "x", "family": "helvetica", "italic": False, "size": 12}],               # no bold
        [{"family": "helvetica", "bold": False, "italic": False, "size": 12}],             # no text
        [_seg("x", size=0)],
        [_seg("x", size=-3)],
        [_seg("x", size="12")],
        [_seg("x", size=True)],
        [_seg("x", size=float("nan"))],
        [{"text": 5, "family": "helvetica", "bold": False, "italic": False, "size": 12}],
        [{"text": "x", "family": None, "bold": False, "italic": False, "size": 12}],
        [{"text": "x", "family": "helvetica", "bold": "yes", "italic": False, "size": 12}],
    ]
    for segments in bad:
        with pytest.raises(PDFError):
            edit_pdf(str(src), str(tmp_path / "o.pdf"), [{"page": 1, "type": "text_edit", "run_index": 0, "segments": segments}], {})


def test_edit_pdf_still_accepts_valid_segments_an_unknown_family_and_an_empty_list(tmp_path):
    src = _one_run_pdf(tmp_path)
    for segments in ([_seg("ok")], [_seg("ok", family="Comic Sans")], [_seg("")], []):
        edit_pdf(str(src), str(tmp_path / "o.pdf"),
                 [{"page": 1, "type": "text_edit", "run_index": 0, "segments": segments}], {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_ops.py -k "text_edit_final_sizes or malformed_text_edit or still_accepts_valid" -v`
Expected: FAIL (`text_edit_final_sizes` missing; malformed segments raise `KeyError`/`TypeError`/nothing instead of `PDFError`).

- [ ] **Step 3: Implement**

In `app/core/pdf_ops.py`, add this function immediately BEFORE `_apply_text_edit`:
```python
def text_edit_final_sizes(segments: list[dict], original_width: float) -> list[float]:
    """The size each replacement segment is actually drawn at: when the whole
    replacement is wider than the original run (measured in each segment's
    own base-14 font at its own size), every segment is scaled by the same
    factor - never below _TEXT_EDIT_SHRINK_FACTOR - and no segment goes below
    _TEXT_EDIT_MIN_SIZE. Single source of truth: _apply_text_edit draws with
    it and the desktop preview sizes its on-screen text with it, so the two
    can't drift apart."""
    resolved = [
        (seg["text"], _base14_alias(seg["family"], seg["bold"], seg["italic"]), seg["size"])
        for seg in segments
    ]
    total_measured = sum(fitz.get_text_length(text, fontname=fontname, fontsize=size) for text, fontname, size in resolved)
    scale = 1.0
    if total_measured > original_width > 0:
        scale = max(_TEXT_EDIT_SHRINK_FACTOR, original_width / total_measured)
    return [max(size * scale, _TEXT_EDIT_MIN_SIZE) for _text, _fontname, size in resolved]
```

In `_apply_text_edit`, replace this block
```python
    resolved = [
        (seg["text"], _base14_alias(seg["family"], seg["bold"], seg["italic"]), seg["size"])
        for seg in segments
    ]
    total_measured = sum(fitz.get_text_length(text, fontname=fontname, fontsize=size) for text, fontname, size in resolved)
    original_width = raw_bbox.width
    scale = 1.0
    if total_measured > original_width > 0:
        scale = max(_TEXT_EDIT_SHRINK_FACTOR, original_width / total_measured)
    color = fitz.sRGB_to_pdf(span.get("color", 0))
```
with
```python
    resolved = [
        (seg["text"], _base14_alias(seg["family"], seg["bold"], seg["italic"]), seg["size"])
        for seg in segments
    ]
    final_sizes = text_edit_final_sizes(segments, raw_bbox.width)
    color = fitz.sRGB_to_pdf(span.get("color", 0))
```
and in BOTH loops replace `for text, fontname, size in resolved:` + `final_size = max(size * scale, _TEXT_EDIT_MIN_SIZE)` with an indexed form:
```python
        for (text, fontname, _size), final_size in zip(resolved, final_sizes):
```
(delete the `final_size = max(...)` line in each loop; keep the rest of each loop body unchanged).

Add the validator right after `_validate_new_text` (or next to the other `_validate_*` functions):
```python
def _validate_text_edit_segments(el: dict) -> None:
    """Rejects malformed segments up front with a clean PDFError instead of a
    raw KeyError/TypeError deep inside the apply step. An unknown `family` is
    deliberately NOT rejected: _base14_alias falls back to helvetica, and the
    web app's own TextSegment schema leaves family an unconstrained string."""
    segments = el["segments"]
    if not isinstance(segments, list):
        raise PDFError("Text edit segments must be a list.")
    for seg in segments:
        if not isinstance(seg, dict):
            raise PDFError("Each text edit segment must be an object.")
        for key, kind in (("text", str), ("family", str), ("bold", bool), ("italic", bool)):
            if key not in seg or not isinstance(seg[key], kind):
                raise PDFError(f"Text edit segment '{key}' is missing or the wrong type.")
        size = seg.get("size")
        if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
            raise PDFError("Text edit segment 'size' must be a positive number.")
```
(`math` is already imported in this module — `_draw_arrow` uses it; confirm.) In `edit_pdf`'s validation loop, inside the `if el_type == "text_edit":` branch, add as the FIRST statement: `_validate_text_edit_segments(el)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_ops.py -v` and `pytest tests/web -q` and `pytest tests/test_ui_desktop.py -v`
Expected: PASS (existing `_apply_text_edit`/`edit_pdf` tests prove the refactor kept behaviour).

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "fix: validate text_edit segments and share the export's shrink-to-fit sizing"
```
Body must end with the line `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` (a `fix:` commit carries the trailer).

---

### Task 2: Desktop preview uses the export's shrink-to-fit sizes

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `text_edit_final_sizes` (Task 1), `EditElementsModel.find_run/page_info`, `build_segments_document`, `EditPageWidget._paint_text_edit`.
- Produces: `EditPageWidget._text_edit_preview_segments(el: dict, run: dict) -> list[dict]` (segments with the export's final sizes; the STORED element is never changed).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py` (reuse `_text_widget`, `_run`, `_text_edit_element`, `_DEFAULT_STYLE` helpers from Phase 6C's tests; grep to confirm names):
```python
def test_preview_segments_shrink_an_over_wide_replacement_like_the_export():
    from app.core.pdf_ops import text_edit_final_sizes
    model, widget = _text_widget(runs=[_run(0, text="Hi", top=0.1, left=0.1, right=0.8, bottom=0.85, size=14.0)])
    segs = [{"text": "A replacement far wider than the tiny original run", "family": "helvetica",
             "bold": False, "italic": False, "size": 14.0}]
    el_id = model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs})
    el = next(e for e in model.elements if e["id"] == el_id)
    run = model.find_run(1, 0)
    preview = widget._text_edit_preview_segments(el, run)
    original_width = (1 - 0.1 - 0.8) * 595  # displayed width == raw width at rotation 0
    assert preview[0]["size"] == pytest.approx(text_edit_final_sizes(segs, original_width)[0])
    assert preview[0]["size"] < 14
    assert el["segments"][0]["size"] == 14.0          # the stored element is untouched
    assert preview[0]["text"] == segs[0]["text"]


def test_preview_segments_are_unchanged_when_the_text_fits():
    model, widget = _text_widget(runs=[_run(0, text="Hello world", top=0.1, left=0.1, right=0.1, bottom=0.85)])
    segs = [{"text": "Hi", "family": "helvetica", "bold": False, "italic": False, "size": 12.0}]
    assert widget._text_edit_preview_segments({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs},
                                              model.find_run(1, 0)) == segs


def test_preview_segments_use_the_displayed_height_as_the_original_width_on_a_rotated_page():
    from app.core.pdf_ops import text_edit_final_sizes
    # 90-degree page: displayed 842 x 595; the run is tall and narrow (sideways text)
    model = EditElementsModel()
    model.set_page_text_info(1, [_run(0, top=0.1, left=0.5, right=0.45, bottom=0.2)], rotation=90, width_pt=842, height_pt=595)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 300))
    segs = [{"text": "W" * 40, "family": "helvetica", "bold": False, "italic": False, "size": 14.0}]
    run = model.find_run(1, 0)
    displayed_h_pt = (1 - 0.1 - 0.2) * 595
    preview = widget._text_edit_preview_segments({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs}, run)
    assert preview[0]["size"] == pytest.approx(text_edit_final_sizes(segs, displayed_h_pt)[0])


def test_preview_segments_fall_back_to_the_stored_sizes_without_page_info():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    segs = [{"text": "abc", "family": "helvetica", "bold": False, "italic": False, "size": 12.0}]
    assert widget._text_edit_preview_segments({"page": 1, "type": "text_edit", "run_index": 0, "segments": segs},
                                              _run(0)) == segs


def test_a_shrunk_preview_is_actually_painted_smaller(tmp_path):
    model, widget = _text_widget(runs=[_run(0, text="Hi", top=0.1, left=0.1, right=0.8, bottom=0.85, size=14.0)])
    widget.px_per_pt = 400 / 595
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    long_segs = [{"text": "W" * 60, "family": "helvetica", "bold": False, "italic": False, "size": 30.0}]
    model.add({"page": 1, "type": "text_edit", "run_index": 0, "segments": long_segs})
    model.select(None)
    img = widget.grab().toImage()
    # the dark text must fit in a band no taller than the SHRUNK size allows (<= 0.5 x 30pt x px_per_pt + slack)
    dark_rows = [y for y in range(600) if any(img.pixelColor(x, y).lightness() < 128 for x in range(0, 400, 2))]
    assert dark_rows, "the replacement text should have been painted"
    assert (max(dark_rows) - min(dark_rows)) <= 30 * 0.5 * (400 / 595) * 1.6 + 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "preview_segments or shrunk_preview" -v` — Expected: FAIL (`_text_edit_preview_segments` doesn't exist).

- [ ] **Step 3: Implement**

At the top of `app/ui/edit_canvas.py` add `from app.core.pdf_ops import text_edit_final_sizes` next to the existing local imports.

Add to `EditPageWidget` (place right before `_paint_text_edit`):
```python
    def _text_edit_preview_segments(self, el: dict, run: dict) -> list[dict]:
        """The segments as the EXPORT will draw them: over-wide replacement
        text is shrunk to fit the original run's width by the core's own
        text_edit_final_sizes (never below half size / 6pt). Only the
        preview uses these sizes - the stored element is never touched.
        Falls back to the stored sizes when the page's size is unknown."""
        info = self.model.page_info.get(el["page"])
        if not info or not info["width_pt"] or not el["segments"]:
            return el["segments"]
        b = run["bbox"]
        displayed_w = (1 - b["left"] - b["right"]) * info["width_pt"]
        displayed_h = (1 - b["top"] - b["bottom"]) * info["height_pt"]
        # raw and displayed axes are swapped on a 90/270 page
        original_width = displayed_h if info["rotation"] in (90, 270) else displayed_w
        sizes = text_edit_final_sizes(el["segments"], original_width)
        return [{**seg, "size": size} for seg, size in zip(el["segments"], sizes)]
```
In `_paint_text_edit`, change `doc = build_segments_document(el["segments"], self.px_per_pt)` to `doc = build_segments_document(self._text_edit_preview_segments(el, run), self.px_per_pt)`. (The run editor overlay is NOT shrunk while typing — only the committed preview.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k "preview_segments or shrunk_preview" -v`, then `pytest tests/test_ui_desktop.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "fix: preview edited text at the size the export will actually draw it"
```
Body must end with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

### Task 3: Delete marker only reacts when its element is selected (all types)

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append; adjust existing tests only where they clicked an unselected element's marker)

**Interfaces:**
- Consumes: `EditPageWidget.mousePressEvent`'s marker hit-test loop, which currently skips unselected `text_edit` elements only.
- Produces: the same loop gating EVERY element type on `self.model.selected_id == el["id"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def _typed_elements():
    return [
        ("new_text", {"page": 1, "type": "new_text", "x": 0.3, "y": 0.3, "width": 0.3, "height": 0.1, "text": "Hi",
                      "family": "helvetica", "bold": False, "italic": False, "underline": False, "size": 14,
                      "color": "#000000", "align": "left"}),
        ("image", {"page": 1, "type": "image", "x": 0.3, "y": 0.3, "width": 0.3, "height": 0.2, "file_id": "x.png"}),
        ("shape", _shape_element(x0=0.3, y0=0.3, x1=0.6, y1=0.5)),
        ("stroke", _stroke_element(points=[{"x": 0.3, "y": 0.3}, {"x": 0.6, "y": 0.5}])),
        ("highlight", _highlight_element(top=0.3, left=0.3, right=0.4, bottom=0.5)),
    ]


@pytest.mark.parametrize("kind,element", _typed_elements(), ids=[k for k, _ in _typed_elements()])
def test_an_unselected_elements_invisible_marker_area_does_not_delete_it(kind, element):
    model = EditElementsModel()
    model.add(element)
    model.select(None)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    marker = widget._marker_rect(model.elements[0])
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert len(model.elements) == 1  # not deleted
    assert model.selected_id == model.elements[0]["id"]  # the click selected it instead


@pytest.mark.parametrize("kind,element", _typed_elements(), ids=[k for k, _ in _typed_elements()])
def test_a_selected_elements_marker_still_deletes_it(kind, element):
    model = EditElementsModel()
    el_id = model.add(element)  # add() selects
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    marker = widget._marker_rect(model.elements[0])
    QTest.mousePress(widget, Qt.LeftButton, Qt.NoModifier, marker.center())
    assert model.elements == []


def test_clicking_an_unselected_elements_marker_area_then_clicking_again_deletes_it():
    model = EditElementsModel()
    model.add(_shape_element(x0=0.3, y0=0.3, x1=0.6, y1=0.5))
    model.select(None)
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    marker = widget._marker_rect(model.elements[0])
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, marker.center())   # selects
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, marker.center())   # now the visible marker is hit
    assert model.elements == []
```
(The helper names `_shape_element`, `_stroke_element`, `_highlight_element` are the Phase 6B test helpers — grep to confirm.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "invisible_marker or selected_elements_marker or marker_area_then" -v` — Expected: the unselected tests FAIL for every kind except `text_edit`-less kinds already gated (none of these five are gated yet).

- [ ] **Step 3: Implement**

In `EditPageWidget.mousePressEvent`, the marker loop currently reads (after Phase 6C's fix):
```python
        for i in reversed(range(len(elements))):
            el = elements[i]
            if el["type"] == "text_edit" and self.model.selected_id != el["id"]:
                continue
            if self._marker_rect(el).contains(pos):
```
(check the exact current text with `grep -n "_marker_rect(el).contains" app/ui/edit_canvas.py`). Change the gate so it applies to every type:
```python
            if self.model.selected_id != el["id"]:
                continue  # the marker is only DRAWN for the selected element, so it must only be clickable then
```
Update the comment above it accordingly (it should say the marker is drawn only for the selected element, for every element type). Then run the whole UI test file: any EXISTING test that clicked the marker of an element that was not selected will now fail — for each, add `model.select(<id>)` (or use the id returned by `model.add`, which selects) before the click, keeping the test's intent; list every test you had to adjust in your report.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "fix: only the selected element's delete marker is clickable"
```
Body must end with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

### Task 4: Preview sizes — pen widths, arrowheads and new-text fonts follow the page scale

**Files:**
- Modify: `app/ui/edit_canvas.py`
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `EditPageWidget.px_per_pt`, `_paint_shape`, `_paint_stroke`, `_draw_arrow_head`, `_qfont_for`.
- Produces: pen widths, arrowhead length and `new_text` font pixel sizes expressed as PDF points x `px_per_pt`. Unknown page size keeps `px_per_pt == 1.0`, so behaviour without page info is unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`:
```python
def _line_thickness(widget, y):
    img = widget.grab().toImage()
    x = widget.width() // 2
    ys = [yy for yy in range(widget.height()) if img.pixelColor(x, yy).lightness() < 128]
    return len(ys), (min(ys), max(ys)) if ys else None


def test_shape_pen_width_is_scaled_from_pdf_points_to_pixels():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    widget.px_per_pt = 0.5
    el_id = model.add(_shape_element(shape="line", x0=0.1, y0=0.5, x1=0.9, y1=0.5, color="#000000", width=6))
    model.select(None)
    thickness, _ = _line_thickness(widget, 300)
    assert 2 <= thickness <= 4   # 6pt at 0.5 px/pt is a 3px line, not the raw 6px


def test_stroke_pen_width_is_scaled_from_pdf_points_to_pixels():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    widget.px_per_pt = 0.5
    model.add(_stroke_element(points=[{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}], color="#000000", width=6))
    model.select(None)
    thickness, _ = _line_thickness(widget, 300)
    assert 2 <= thickness <= 4


def test_pen_width_is_unchanged_when_the_page_scale_is_unknown():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)   # no page info -> px_per_pt stays 1.0
    assert widget.px_per_pt == 1.0
    model.add(_shape_element(shape="line", x0=0.1, y0=0.5, x1=0.9, y1=0.5, color="#000000", width=6))
    model.select(None)
    thickness, _ = _line_thickness(widget, 300)
    assert 5 <= thickness <= 7


def test_arrowhead_length_follows_the_page_scale():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    pm = QPixmap(400, 600)
    pm.fill(Qt.white)
    widget.set_page_pixmap(pm)
    model.add(_shape_element(shape="arrow", x0=0.1, y0=0.5, x1=0.9, y1=0.5, color="#000000", width=3))
    model.select(None)

    def head_height():
        img = widget.grab().toImage()
        x = int(0.9 * 400) - 3          # just behind the tip, inside the head
        ys = [y for y in range(600) if img.pixelColor(x, y).lightness() < 128]
        return (max(ys) - min(ys)) if ys else 0

    widget.px_per_pt = 1.0
    big = head_height()
    widget.px_per_pt = 0.5
    widget.update()
    small = head_height()
    assert big > small > 0


def test_new_text_font_pixel_size_follows_the_page_scale():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    el = {"family": "helvetica", "bold": False, "italic": False, "underline": False, "size": 20}
    widget.px_per_pt = 1.0
    assert widget._qfont_for(el).pixelSize() == 20
    widget.px_per_pt = 0.5
    assert widget._qfont_for(el).pixelSize() == 10
    widget.px_per_pt = 0.01
    assert widget._qfont_for(el).pixelSize() >= 1   # never zero


def test_new_text_editor_and_painted_text_use_the_same_scaled_font():
    model = EditElementsModel()
    widget = EditPageWidget(model, page_number=1)
    widget.set_page_pixmap(QPixmap(400, 600))
    widget.px_per_pt = 0.5
    widget.create_mode = "new_text"
    QTest.mouseClick(widget, Qt.LeftButton, Qt.NoModifier, QPoint(200, 300))
    assert widget._text_editor.font().pixelSize() == 7    # the default new-text size is 14pt x 0.5
    widget.commit_open_editors()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k "pen_width or arrowhead_length or font_pixel_size or same_scaled_font" -v` — Expected: FAIL (widths are raw pixels; `_qfont_for` uses points).

- [ ] **Step 3: Implement**

In `_paint_shape`, replace `painter.setPen(QPen(color, el["width"]))` with:
```python
        painter.setPen(QPen(color, max(1.0, el["width"] * self.px_per_pt)))
```
and pass the scaled width into the arrow: change the arrow branch call to `self._draw_arrow_head(painter, x0_px, y0_px, x1_px, y1_px, el["width"])` (unchanged) and inside `_draw_arrow_head` change `head_len = max(8, width * 3)` to
```python
        head_len = max(8, width * 3) * self.px_per_pt  # the core's head length is in PDF points
```
In `_paint_stroke`, replace `painter.setPen(QPen(QColor(el["color"]), el["width"]))` with:
```python
        painter.setPen(QPen(QColor(el["color"]), max(1.0, el["width"] * self.px_per_pt)))
```
Replace `_qfont_for`:
```python
    def _qfont_for(self, el: dict) -> QFont:
        font = QFont(el["family"])
        # el["size"] is in PDF points; the thumbnail is px_per_pt pixels per
        # point (1.0 when the page size is unknown), so size in pixels - not
        # in screen points, which would depend on the display's DPI.
        font.setPixelSize(max(1, round(el["size"] * self.px_per_pt)))
        font.setBold(el["bold"])
        font.setItalic(el["italic"])
        font.setUnderline(el["underline"])
        return font
```
Highlight and `_paint_chrome` need no change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v` — Expected: PASS. If an existing new-text test asserted a point size, update it to the pixel-size equivalent at `px_per_pt == 1.0` and say so in the report.

- [ ] **Step 5: Commit**

```bash
git add app/ui/edit_canvas.py tests/test_ui_desktop.py
git commit -m "fix: draw pen widths, arrowheads and new-text fonts at the page's scale"
```
Body must end with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

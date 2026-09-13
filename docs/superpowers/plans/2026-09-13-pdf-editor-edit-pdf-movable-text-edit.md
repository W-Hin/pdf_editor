# Edit PDF: Movable In-Place Text Edits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `text_edit` element (an in-place edit to existing PDF text) be dragged to a new position on the page, independent of the original text run's own location, instead of always redrawing at the exact spot the original text occupied.

**Architecture:** Backend: `_apply_text_edit` gains an optional `override_xy` (page-fraction) parameter; when present it draws the replacement at a new DISPLAYED-space position (converted to raw/mediabox space via the page's own rotation matrices, with `insert_text`'s `rotate=` set to match the page's rotation) instead of the original run's raw origin — the redaction of the original text is unchanged either way. `TextEditElement` gains optional `x`/`y` fraction fields matching every other element type's convention. Frontend: `text_edit` elements stop being a special case excluded from the generalized select/drag/z-order system — they become one more draggable box (fixed size, matching the original run's own dimensions), with double-click reopening the style/type editor at the box's current position.

**Tech Stack:** Python (FastAPI backend, PyMuPDF/`fitz`), React (frontend), pytest.

## Global Constraints

- Move only, never resize — a `text_edit` element's box always keeps the exact width/height the original run had. No task in this plan adds resize handles or width/height fields to `text_edit`.
- The font-size auto-shrink logic (`_TEXT_EDIT_SHRINK_FACTOR`, `_TEXT_EDIT_MIN_SIZE`) is completely unchanged — it keeps measuring against the original run's raw width regardless of where the text is drawn.
- When a `text_edit` element has no `x`/`y` (the common case — never moved), backend output must be byte-identical to today's behavior.
- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Both tasks in this plan ship new, intentional behavior — their commits are `feat:` and must **not** carry the trailer.
- No frontend automated tests (established project convention for frontend-only work) — manual browser verification instead, including checking the actual exported/downloaded PDF's content, not just on-screen appearance.

---

## Empirically verified conversion math (read this before Task 1)

The obvious-looking approach — convert the frontend's `x`/`y` page-fraction straight to an absolute point via `page.rect` and hand it to `insert_text` with no other changes — was tested directly against a real rotated PDF and is **wrong**: on a 90°-rotated page it draws the replacement text sideways, because `insert_text`'s default `rotate=0` draws glyphs upright in *raw* mediabox space, and a freshly-chosen DISPLAYED-space position needs the glyphs counter-rotated to appear upright to the viewer — exactly the reason `_apply_new_text` (`app/core/pdf_ops.py:790-838`) and `_apply_image` already pass `rotate=page.rotation % 360`. A second, independent problem: `_apply_text_edit`'s existing multi-segment loop advances the cursor along the **raw** x-axis (`x += fitz.get_text_length(...)`), which is only safe today because the original run's raw and displayed reading directions coincide (nothing has moved) — a moved box needs the advance done in *displayed* space instead, or later segments drift off along the wrong axis once the page is rotated.

The verified-correct formula (confirmed with a throwaway script reproducing `_page_text_spans`/`_base14_alias`/`_TEXT_EDIT_SHRINK_FACTOR` exactly, across page rotations 0/90/180/270, single- and multi-segment lines):

```python
raw_bbox = fitz.Rect(span["bbox"])
rm = page.rotation_matrix        # raw -> displayed
dm = page.derotation_matrix      # displayed -> raw
displayed_bbox = raw_bbox * rm
# How far below/right of the run's own box the original baseline sat, in
# DISPLAYED space — preserved across the move so segments still share one
# baseline the same way they do today.
baseline_offset = (fitz.Point(*span["origin"]) * rm) - displayed_bbox.tl

rect = page.rect
new_topleft_displayed = fitz.Point(rect.x0 + x_frac * rect.width, rect.y0 + y_frac * rect.height)
cursor_displayed = new_topleft_displayed + baseline_offset
rotate = page.rotation % 360

for text, fontname, size in resolved:            # unchanged per-segment loop body
    origin = fitz.Point(cursor_displayed.x, cursor_displayed.y) * dm
    # insert_text(origin, text, fontsize=final_size, fontname=fontname, color=color, rotate=rotate)
    advance = fitz.get_text_length(text, fontname=fontname, fontsize=final_size)
    cursor_displayed = fitz.Point(cursor_displayed.x + advance, cursor_displayed.y)
```

Verified end-to-end (via a full simulated `edit_pdf` run, not just the isolated function) on a 612×792 page rotated 90°, with an original run "OMEGA ORIGINAL" at raw `(72, 700)` and a second untouched run "ALPHA KEEP" at raw `(72, 72)`, replaced with two segments `"OMEGA "` (regular, size 11) and `"MOVED"` (bold, size 11) at override `x=0.5, y=0.05`:

- Target displayed top-left: `(396.0, 30.6)`.
- Resulting displayed spans: `"OMEGA "` → `(399.29, 18.78, 443.30, 33.89)`, `"MOVED"` → `(443.30, 18.83, 483.64, 33.98)` — contiguous (`"MOVED"`'s left edge exactly meets `"OMEGA "`'s right edge), both near the target top-left (offset by the baseline_offset, as expected), both reading left-to-right in DISPLAYED space despite the 90° page rotation.
- `"OMEGA ORIGINAL"` is completely gone from the extracted text; `"ALPHA KEEP"` is byte-identical to its original position.

And on a non-rotated 612×792 page, an original run "Hello World" at raw `(72, 100)` replaced with `"Goodbye Mars"` at override `x=0.2, y=0.5`: resulting bbox `(122.4, 399.19, 194.74, 414.35)` — `x0` lands exactly on the target top-left x (`122.4`), confirming `baseline_offset.x == 0` is preserved correctly for a run whose origin already sat flush with its own box's left edge.

Task 1 below bakes these exact verified numbers into its regression tests.

---

### Task 1: Backend — override position for `_apply_text_edit`

**Files:**
- Modify: `app/core/pdf_ops.py:580-638` (`_apply_text_edit`), `app/core/pdf_ops.py:841-893` (`edit_pdf`'s validation loop and text-edit apply loop)
- Modify: `web/backend/routes/tools.py:437-441` (`TextEditElement`)
- Test: `tests/test_pdf_ops.py` (new tests near the existing `test_edit_pdf_text_edit_*` tests, currently at lines 886-1016)

**Interfaces:**
- Consumes: nothing new from other tasks (this is the first task).
- Produces: `TextEditElement.x: float | None = None`, `TextEditElement.y: float | None = None` — Task 2 (frontend) sends these as page fractions, same convention as `ImageElement`/`NewTextElement`'s `x`/`y`. `edit_pdf`'s element-dict contract for `text_edit` becomes `{"type": "text_edit", "page": int, "run_index": int, "segments": [...], "x": float | None, "y": float | None}` — `x`/`y` are both present or both absent (the frontend never sends one without the other; Task 2 relies on this).

- [ ] **Step 1: Write the failing tests**

Add these two tests to `tests/test_pdf_ops.py`, directly after `test_edit_pdf_text_edit_handles_rotated_page` (currently ending at line 945):

```python
def test_edit_pdf_text_edit_moves_replacement_to_an_overridden_position(tmp_path):
    """Verified independently against a throwaway script before writing this
    (see the movable-text-edit plan) — a naive fraction-to-point conversion
    with no rotate= draws the moved text sideways on a rotated page, and a
    raw-space segment advance drifts off the wrong axis. Both are exercised
    here: two differently-styled segments, on a 90-degree-rotated page,
    moved well away from the original run's own spot."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 700), "OMEGA ORIGINAL")  # displayed top-left after rotation
    page.insert_text((72, 72), "ALPHA KEEP")        # displayed top-right after rotation
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)
    target = next(r for r in runs if r["text"] == "OMEGA ORIGINAL")

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{
            "type": "text_edit", "page": 1, "run_index": target["index"],
            "segments": [
                {"text": "OMEGA ", "family": "helvetica", "bold": False, "italic": False, "size": 11},
                {"text": "MOVED", "family": "helvetica", "bold": True, "italic": False, "size": 11},
            ],
            "x": 0.5, "y": 0.05,
        }],
        {},
    )

    result = fitz.open(str(output_path))
    page2 = result[0]
    rm = page2.rotation_matrix
    d = page2.get_text("dict")
    spans = [s for b in d["blocks"] for l in b["lines"] for s in l["spans"]]
    result.close()

    full_text = "".join(s["text"] for s in spans)
    assert "OMEGA ORIGINAL" not in full_text
    assert "OMEGA " in full_text and "MOVED" in full_text

    omega = next(s for s in spans if s["text"] == "OMEGA ")
    moved = next(s for s in spans if s["text"] == "MOVED")
    omega_displayed = fitz.Rect(omega["bbox"]) * rm
    moved_displayed = fitz.Rect(moved["bbox"]) * rm

    # Lands near the target displayed top-left (396.0, 30.6) — offset by the
    # original run's own baseline-to-box-top distance, preserved across the
    # move (this is why it's "near", not exactly on top of, the raw target).
    assert omega_displayed.x0 == pytest.approx(399.29, abs=0.1)
    assert omega_displayed.y0 == pytest.approx(18.78, abs=0.1)
    # The second segment starts exactly where the first ends — contiguous,
    # reading left-to-right in DISPLAYED space despite the page's rotation.
    assert moved_displayed.x0 == pytest.approx(omega_displayed.x1, abs=0.01)
    # Both segments still sit on one shared visual line.
    assert moved_displayed.y0 == pytest.approx(omega_displayed.y0, abs=1.0)

    # The untouched run is completely unaffected.
    alpha = next(s for s in spans if s["text"] == "ALPHA KEEP")
    alpha_displayed = fitz.Rect(alpha["bbox"]) * rm
    assert alpha_displayed.x0 == pytest.approx(716.71, abs=0.1)
    assert alpha_displayed.y0 == pytest.approx(72.0, abs=0.1)


def test_edit_pdf_text_edit_without_position_is_unchanged(tmp_path):
    """x/y absent must remain byte-identical to today's in-place behavior —
    this is the existing test_edit_pdf_text_edit_replaces_text_and_keeps_surrounding_content
    scenario, re-asserted here specifically to lock in that adding the
    override path did not disturb the no-override path."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{
            "type": "text_edit", "page": 1, "run_index": 0,
            "segments": [{"text": "Goodbye Mars", "family": "helvetica", "bold": False, "italic": False, "size": 14}],
        }],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 1
    assert spans[0]["text"] == "Goodbye Mars"
    # Unchanged: still starts exactly at the original run's own raw origin.
    assert spans[0]["origin"][0] == pytest.approx(72.0, abs=0.01)


def test_edit_pdf_text_edit_moves_to_a_non_rotated_position(tmp_path):
    """The simpler, more common case: no page rotation at all. Confirms the
    baseline_offset math degrades correctly to a flush top-left placement
    when the original run's origin already sat flush with its own box."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Hello World", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{
            "type": "text_edit", "page": 1, "run_index": 0,
            "segments": [{"text": "Goodbye Mars", "family": "helvetica", "bold": False, "italic": False, "size": 14}],
            "x": 0.2, "y": 0.5,
        }],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 1
    assert spans[0]["text"] == "Goodbye Mars"
    assert spans[0]["bbox"][0] == pytest.approx(122.4, abs=0.05)
    assert spans[0]["bbox"][1] == pytest.approx(399.19, abs=0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_ops.py -k "text_edit_moves or text_edit_without_position" -v`
Expected: FAIL — `test_edit_pdf_text_edit_without_position_is_unchanged` may pass already (it's asserting current behavior), but both `*_moves_*` tests must fail, since `x`/`y` are silently ignored by the current `_apply_text_edit`/`TextEditElement` (they land at the *original* run's position instead of the override).

- [ ] **Step 3: Add `x`/`y` to `TextEditElement`**

In `web/backend/routes/tools.py`, change (currently lines 437-441):

```python
class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    segments: list[TextSegment] = Field(min_length=1)
```

to:

```python
class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    segments: list[TextSegment] = Field(min_length=1)
    x: float | None = None
    y: float | None = None
```

No change needed to `edit_pdf_route` (`web/backend/routes/tools.py:522-535`) — it already does `elements = [el.model_dump() for el in req.elements]`, so the new optional fields flow through to the `dict` `edit_pdf` receives with no other code changes.

- [ ] **Step 4: Rewrite `_apply_text_edit` with the override path**

Replace the current `_apply_text_edit` (`app/core/pdf_ops.py:580-638`) with:

```python
def _apply_text_edit(
    page: fitz.Page, span: dict, segments: list[dict], override_xy: tuple[float, float] | None = None
) -> list[tuple]:
    raw_bbox = fitz.Rect(span["bbox"])
    page.add_redact_annot(raw_bbox, fill=(1, 1, 1))
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
    inserts = []

    if override_xy is not None:
        # The replacement is being drawn at a NEW position the user dragged
        # it to (a page fraction, matching every other element type's
        # convention), not at the original run's own spot. Two things the
        # "redact in place" case gets for free break once position and
        # redaction diverge — both verified empirically against a real
        # rotated PDF before writing this (see the movable-text-edit plan):
        # insert_text's default rotate=0 only looks right when reusing the
        # original run's own raw origin, and the multi-segment x-advance
        # must happen in DISPLAYED space, not raw space, or later segments
        # drift off the wrong axis once the page is rotated.
        rect = page.rect
        dm = page.derotation_matrix
        rm = page.rotation_matrix
        displayed_bbox = raw_bbox * rm
        baseline_offset = (fitz.Point(*span["origin"]) * rm) - displayed_bbox.tl
        x_frac, y_frac = override_xy
        new_topleft_displayed = fitz.Point(rect.x0 + x_frac * rect.width, rect.y0 + y_frac * rect.height)
        cursor_displayed = new_topleft_displayed + baseline_offset
        rotate = page.rotation % 360
        for text, fontname, size in resolved:
            final_size = max(size * scale, _TEXT_EDIT_MIN_SIZE)
            origin = fitz.Point(cursor_displayed.x, cursor_displayed.y) * dm
            inserts.append((origin, text, fontname, final_size, color, rotate))
            advance = fitz.get_text_length(text, fontname=fontname, fontsize=final_size)
            cursor_displayed = fitz.Point(cursor_displayed.x + advance, cursor_displayed.y)
        return inserts

    x = raw_bbox.x0
    y = span["origin"][1]
    for text, fontname, size in resolved:
        final_size = max(size * scale, _TEXT_EDIT_MIN_SIZE)
        inserts.append((fitz.Point(x, y), text, fontname, final_size, color, 0))
        x += fitz.get_text_length(text, fontname=fontname, fontsize=final_size)
    return inserts
```

Note the `inserts` tuples are now 6-element (`origin, text, fontname, size, color, rotate` — `rotate` is new, always `0` on the no-override path, so behavior there is unchanged).

- [ ] **Step 5: Update `edit_pdf`'s call site and validation**

In `edit_pdf` (`app/core/pdf_ops.py:841-893`), the validation loop's `text_edit` branch (currently lines 852-857):

```python
            if el_type == "text_edit":
                if page_num not in run_cache:
                    run_cache[page_num] = _page_text_spans(doc[page_num - 1])
                spans = run_cache[page_num]
                if el["run_index"] < 0 or el["run_index"] >= len(spans):
                    raise PDFError(f"Text run {el['run_index']} not found on page {page_num}.")
```

becomes:

```python
            if el_type == "text_edit":
                if page_num not in run_cache:
                    run_cache[page_num] = _page_text_spans(doc[page_num - 1])
                spans = run_cache[page_num]
                if el["run_index"] < 0 or el["run_index"] >= len(spans):
                    raise PDFError(f"Text run {el['run_index']} not found on page {page_num}.")
                has_x, has_y = el.get("x") is not None, el.get("y") is not None
                if has_x != has_y:
                    raise PDFError("Text position requires both x and y.")
                if has_x and (not (0 <= el["x"] <= 1) or not (0 <= el["y"] <= 1)):
                    raise PDFError("Text position must be within the page.")
```

And the text-edit apply loop (currently lines 884-893):

```python
        for page_num, page_edits in text_edits_by_page.items():
            page = doc[page_num - 1]
            spans = run_cache[page_num]
            pending_inserts = []
            for el in page_edits:
                span = spans[el["run_index"]]
                pending_inserts.extend(_apply_text_edit(page, span, el["segments"]))
            page.apply_redactions()
            for origin, text, fontname, size, color in pending_inserts:
                page.insert_text(origin, text, fontsize=size, fontname=fontname, color=color)
```

becomes:

```python
        for page_num, page_edits in text_edits_by_page.items():
            page = doc[page_num - 1]
            spans = run_cache[page_num]
            pending_inserts = []
            for el in page_edits:
                span = spans[el["run_index"]]
                override_xy = (el["x"], el["y"]) if el.get("x") is not None else None
                pending_inserts.extend(_apply_text_edit(page, span, el["segments"], override_xy))
            page.apply_redactions()
            for origin, text, fontname, size, color, rotate in pending_inserts:
                page.insert_text(origin, text, fontsize=size, fontname=fontname, color=color, rotate=rotate)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_pdf_ops.py -k text_edit -v`
Expected: PASS — all `test_edit_pdf_text_edit_*` tests (the 5 pre-existing ones plus the 3 new ones from Step 1).

Run the full backend suite to confirm no regressions: `pytest -q`
Expected: PASS, same total count as before plus 3 (the existing suite was at 248 passing before this plan).

- [ ] **Step 7: Commit**

```bash
git add app/core/pdf_ops.py web/backend/routes/tools.py tests/test_pdf_ops.py
git commit -m "feat: let a text_edit element be drawn at an overridden position"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 2: Frontend — wire `text_edit` into the generalized element system

This task is deliberately ONE cohesive unit, not split further: wiring `text_edit` into the drag system, transferring the double-click entry point away from the original run, and updating what "revert" clears are all part of the same interaction model — leaving any one of them out mid-plan would put the feature in a state that behaves like neither the old nor the new design, which is exactly the kind of half-finished intermediate state that makes a task-level diff hard to judge on its own.

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx` (see exact regions below)
- Modify: `web/frontend/src/index.css` (new rules for the moved box's own class)

**Interfaces:**
- Consumes: `TextEditElement`'s new optional `x`/`y` fields from Task 1 (page fractions) — this task is the only sender of those fields.
- Produces: nothing consumed by later tasks (this is the last task in the plan).

- [ ] **Step 1: Add a shared box-rect helper**

Just above `pendingTextEditFor` (`web/frontend/src/components/EditPdfCanvas.jsx:992`), add:

```javascript
  // The box a text_edit element (or its live editor overlay) occupies: the
  // original run's own detected size always (per this feature's "move only,
  // never resize" scope decision), positioned at the element's moved x/y
  // once it has one, falling back to the run's own top-left when it hasn't
  // been moved yet (or no pending edit exists at all).
  function textEditBoxRect(run, pending) {
    const width = 1 - run.bbox.left - run.bbox.right;
    const height = 1 - run.bbox.top - run.bbox.bottom;
    const left = pending?.x ?? run.bbox.left;
    const top = pending?.y ?? run.bbox.top;
    return { left, top, width, height };
  }
```

- [ ] **Step 2: Add a `text_edit` branch to `moveElement`**

In `moveElement` (`web/frontend/src/components/EditPdfCanvas.jsx:927-955`), insert a new branch **before** the final `// x/y/width/height (image, new_text)` fallback (after the existing `"points" in el"` branch, before its closing brace's next line):

```javascript
    if (el.type === "text_edit") {
      // Reconstructed explicitly (not `{ ...el, x, y }`) so the width/height
      // this function needs for clamping — merged onto `el` only for the
      // duration of the drag by renderTextEditElement below — never leaks
      // into the stored element. A text_edit element's size always comes
      // from its own run, never from anything persisted on the element.
      const x = Math.min(Math.max(el.x + dx, 0), 1 - el.width);
      const y = Math.min(Math.max(el.y + dy, 0), 1 - el.height);
      return { id: el.id, type: el.type, page: el.page, run_index: el.run_index, segments: el.segments, x, y };
    }
```

The existing fallback branch's comment (`// x/y/width/height (image, new_text)`) should be updated to `// x/y/width/height (image, new_text) — text_edit has its own branch above`, so a future reader doesn't wonder why text_edit isn't listed there.

- [ ] **Step 3: Extract the segment-span renderer**

In `renderRunStyleOverlay` (`web/frontend/src/components/EditPdfCanvas.jsx:1499-1518`), the `spanEls` computation is currently inline. Extract it into a standalone function placed just above `renderRunStyleOverlay`:

```javascript
  function renderSegmentSpans(segments) {
    let offset = 0;
    return segments.map((seg, i) => {
      const start = offset;
      offset += seg.text.length;
      return (
        <span
          key={i}
          data-seg-start={start}
          style={{
            fontFamily: newTextFontFamilyCss(seg.family),
            fontWeight: seg.bold ? "bold" : "normal",
            fontStyle: seg.italic ? "italic" : "normal",
            fontSize: `${seg.size}px`,
          }}
        >
          {seg.text}
        </span>
      );
    });
  }
```

Then change `renderRunStyleOverlay`'s own `spanEls` computation to just `const spanEls = renderSegmentSpans(runEditor.segments);`. `data-seg-start` is only read by `handleStyleSelectionChange` (line 1090's `Number(anchorSpan.dataset.segStart)`), which only ever runs against the live `runEditor.segments` overlay, not the static `renderTextEditElement` box — so reusing this same function for the static box (Step 6 below) is safe even though the `data-seg-start` attributes it produces go unused there.

- [ ] **Step 4: Use the shared box rect in the existing editor overlays**

In `renderRunEditorOverlay` (`web/frontend/src/components/EditPdfCanvas.jsx:1608-1680`), replace:

```javascript
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
```

with a `box` computed once at the top of the function and reused:

```javascript
    const box = textEditBoxRect(run, pendingTextEditFor(run));
    // ... existing `seg`/`updateSeg` code stays where it is ...
        style={{
          left: `${box.left * 100}%`,
          top: `${box.top * 100}%`,
          width: `${box.width * 100}%`,
          height: `${box.height * 100}%`,
        }}
```

Do the same in `renderRunStyleOverlay` (`web/frontend/src/components/EditPdfCanvas.jsx:1499-1562`): compute `const pending = pendingTextEditFor(run);` once near the top (reuse it for the existing `{pendingTextEditFor(run) && (...)}` Revert-button check at line 1548 too, changing that check to `{pending && (...)}`), compute `const box = textEditBoxRect(run, pending);`, and use `box.left/top/width/height` in place of the `run.bbox.left/top/(1 - run.bbox.left - run.bbox.right)/(1 - run.bbox.top - run.bbox.bottom)` expressions currently at lines 1525-1528.

This makes double-clicking a *moved* `text_edit` element reopen its editor at the box's current position, not the original run's spot — the editor overlay and the static draggable box (Step 6) now read position from the exact same helper.

- [ ] **Step 5: Preserve position across content/style edits; stop `renderTextRun` from re-exposing an edited run**

In `commitRunEditor` (`web/frontend/src/components/EditPdfCanvas.jsx:1019-1047`), the `newEl` object currently built is:

```javascript
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editor.page,
      run_index: editor.runIndex,
      segments: [{ text: seg.text, family: seg.family, bold: seg.bold, italic: seg.italic, size: seg.size }],
    };
```

Add `x: pending?.x, y: pending?.y` (both keys always present; `undefined` values are dropped by `JSON.stringify`, matching Task 1's `el.get("x") is not None` check on the backend for the "never moved" case):

```javascript
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editor.page,
      run_index: editor.runIndex,
      segments: [{ text: seg.text, family: seg.family, bold: seg.bold, italic: seg.italic, size: seg.size }],
      x: pending?.x,
      y: pending?.y,
    };
```

Make the identical addition (`x: pending?.x, y: pending?.y`) to `applySelectionStyle`'s `newEl` object (`web/frontend/src/components/EditPdfCanvas.jsx:1097-1112`).

`revertRunEditor` (`web/frontend/src/components/EditPdfCanvas.jsx:1049-1061`) needs no change — it already deletes the pending element entirely (`commitElements(elements.filter((el) => el.id !== pending.id))`), which discards any `x`/`y` it had along with everything else. A subsequent re-edit creates a brand new element with no position, matching the "revert restores position too" scope decision for free.

In `renderTextRun` (`web/frontend/src/components/EditPdfCanvas.jsx:1682-1700`), add a guard so a run with a pending edit stops being independently double-click-able once `renderTextEditElement` (Step 6) becomes the sole entry point back into it:

```javascript
  function renderTextRun(run, pageNumber) {
    if (runEditor && runEditor.page === pageNumber && runEditor.runIndex === run.index) {
      return renderRunEditorOverlay(run);
    }
    if (pendingTextEditFor(run)) return null;
    return (
      <div
        key={run.index}
        className="edit-pdf-canvas__run"
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onDoubleClick={() => openRunEditor(pageNumber, run)}
      />
    );
  }
```

(The `"edit-pdf-canvas__run--queued"` class and its conditional are removed from this function — that visual "an edit is queued here" indicator on the original spot no longer applies once the original spot stops rendering anything at all for an edited run. The class name in `index.css` can stay unused/removed; leave the CSS rule in place since removing unused CSS is out of scope for this task.)

- [ ] **Step 6: Add `renderTextEditElement` and wire it into the dispatcher and per-page filter**

Add a new function modeled on `renderNewTextElement` (`web/frontend/src/components/EditPdfCanvas.jsx:1346-1393`), placed just above `renderElement`:

```javascript
  function renderTextEditElement(el, pageRef) {
    const run = runs.find((r) => r.page === el.page && r.index === el.run_index);
    if (!run) return null; // runs haven't loaded yet for this page
    const box = textEditBoxRect(run, el);
    const positioned = { ...el, x: box.left, y: box.top, width: box.width, height: box.height };
    return (
      <div
        className={
          el.id === selectedId
            ? "edit-pdf-canvas__text-edit-el edit-pdf-canvas__text-edit-el--selected"
            : "edit-pdf-canvas__text-edit-el"
        }
        style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}
        onMouseDown={(e) => {
          setSelectedId(el.id);
          startElementDrag(pageRef, positioned, "move", e);
        }}
        onClick={(e) => e.stopPropagation()}
        onDoubleClick={(e) => {
          e.stopPropagation();
          openRunEditor(el.page, run);
        }}
      >
        <div className="edit-pdf-canvas__run-style-text edit-pdf-canvas__run-style-text--static">
          {renderSegmentSpans(el.segments)}
        </div>
      </div>
    );
  }
```

Add its dispatch case to `renderElement` (`web/frontend/src/components/EditPdfCanvas.jsx:1395-1402`):

```javascript
  function renderElement(el, pageNumber, pageRef) {
    if (el.type === "stroke") return renderStroke(el, pageRef);
    if (el.type === "shape") return renderShape(el, pageRef);
    if (el.type === "highlight") return renderHighlight(el, pageRef);
    if (el.type === "image") return renderImageElement(el, pageRef);
    if (el.type === "new_text") return renderNewTextElement(el, pageRef);
    if (el.type === "text_edit") return renderTextEditElement(el, pageRef);
    return null;
  }
```

Update the per-page element filter in `renderPageOverlay` (`web/frontend/src/components/EditPdfCanvas.jsx:1712-1713`), which currently excludes `text_edit` entirely:

```javascript
        {elements
          .filter((el) => el.page === pageNumber && el.type !== "text_edit" && el.id !== textDraft?.id)
```

to include `text_edit` elements except the one whose editor is currently open (that one's box is replaced by the editor overlay, rendered separately via `renderTextRun`'s dispatch to `renderRunEditorOverlay`/`renderRunStyleOverlay` — showing both at once would be a confusing duplicate):

```javascript
        {elements
          .filter((el) => {
            if (el.page !== pageNumber || el.id === textDraft?.id) return false;
            if (el.type === "text_edit" && runEditor && runEditor.page === el.page && runEditor.runIndex === el.run_index) {
              return false;
            }
            return true;
          })
```

- [ ] **Step 7: Add CSS for the new box class**

In `web/frontend/src/index.css`, add (modeled directly on the existing `.edit-pdf-canvas__new-text-el`/`--selected` rules, minus any resize handle — this box is never resizable):

```css
.edit-pdf-canvas__text-edit-el {
  position: absolute;
  pointer-events: auto;
  cursor: move;
}

.edit-pdf-canvas__text-edit-el--selected {
  outline: 2px solid var(--color-accent);
  outline-offset: 1px;
}

.edit-pdf-canvas__run-style-text--static {
  pointer-events: none;
}
```

(`.edit-pdf-canvas__run-style-text` already exists and supplies `width: 100%; height: 100%; overflow: hidden; white-space: nowrap;` — the `--static` modifier only adds `pointer-events: none` so the static box's drag/double-click handlers on its parent `<div>` aren't blocked by the text underneath.)

- [ ] **Step 8: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds with no errors.

Start the dev server (`npm run dev` in `web/frontend`, backend already running per this project's usual dev setup) and manually verify, using a PDF with existing text (a rotated-page PDF if available, to exercise the rotation-aware path; otherwise verify the un-rotated case and trust Task 1's rotated backend test for that coverage):

1. Double-click an existing text run, type a replacement, click away — the replacement appears at the original run's position, same as before this plan (no regression).
2. Select the replacement (click once) and drag it to a new spot on the page — it moves independently of where the original text was; the box's size does not change while dragging.
3. Double-click the *moved* box — the style/type editor reopens positioned at the box's *current* (moved) location, not the original run's spot.
4. Confirm the original run's own spot is no longer double-click-able or hover-highlighted once an edit exists there (only the moved box responds to interaction).
5. Click "Revert" from the style editor (or from the type editor, if reopened into typing) — the edit disappears entirely, and double-clicking the *original* spot now reopens a fresh editor there (position reset, matching pre-edit behavior).
6. Restyle only part of a multi-word run's text (select a sub-range, change bold/size) while the box has already been moved — confirm the moved box, when just sitting there selected (not actively being edited), shows the real per-segment styling (e.g. one bold word, one regular word, if the run had one restyled) rather than a flattened single style.
7. Export/download the PDF after moving a text edit — open the downloaded file and confirm the replacement text is genuinely at the new position and the original spot is genuinely blank, matching what Task 1's backend tests already assert programmatically.
8. Confirm pressing Delete/Backspace while a (non-editing) moved text_edit box is selected removes it entirely (this already works via the existing generic Delete/Backspace handler, which has no type-specific exclusion — this step only confirms no regression was introduced for text_edit specifically).

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: make in-place text edits draggable, independent of the original run's position"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

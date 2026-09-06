# Edit PDF: Partial Mid-Run Text Styling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user select part of a line of text (character-level, any range) inside Edit PDF's real-time text editor and style just that part — differently from the rest of the same line — via a small floating popover, while typing/committing the base text stays exactly the single-style `<input>` interaction Sub-project 4 already shipped.

**Architecture:** `text_edit` elements move from a single `{text, font_override}` pair to an ordered list of styled `segments` (`[{text, family, bold, italic, size}, ...]`), fully replacing the old shape — a hard cutover, not a dual format. The backend (`_apply_text_edit`) redacts the original run once, then inserts each segment side-by-side on the same baseline, shrinking every segment's size by one shared proportional factor if their combined width overflows. The frontend's existing `runEditor` state machine (Sub-project 4) gains a `phase` field: `"type"` is exactly today's plain single-line `<input>` (now just editing `segments[0]`); `"style"` is a new read-only view of the committed segments as adjacent styled `<span>`s, drag-selectable via the browser's native text selection, with a floating popover offering family/bold/italic/size controls that split and restyle only the selected range.

**Tech Stack:** Python/PyMuPDF (`fitz`) backend, Pydantic request models, React frontend (function components, hooks) in the same `EditPdfCanvas.jsx` Sub-project 4 just shipped.

## Global Constraints

- **Hard cutover, one format only.** `text_edit`'s `text`/`font_override` fields are removed entirely and replaced by `segments`. There is no dual-format support — `EditPdfCanvas.jsx` is the only producer of `text_edit` elements in this codebase (verified: `grep -rn "text_edit"` across the repo finds no other caller of the `/tools/edit-pdf` route), so there is no compatibility concern to preserve.
- **Deliberate scope decision — embedded/detected-font preservation is removed.** Today, `font_override: null` means "keep this run's own actual font" (including a real embedded font, extracted via `_extract_embedded_font`) when only the text changes, not the styling. The approved spec's segment shape (`{text, family, bold, italic, size}`) has no null/optional field — every segment always specifies an explicit base-14 family. Supporting embedded-font preservation would require a nullable per-segment override, reintroducing exactly the "two parallel formats" the spec explicitly says this migration must avoid. This plan therefore removes `_extract_embedded_font`, its one dedicated test, and the whole embedded-font code path from `_apply_text_edit` — every `text_edit`, from now on, always renders through a base-14 font (`_base14_alias`), same as Add Text already does. This is mitigated (not eliminated) by Task 2's `closestBase14Family` helper: a freshly-opened, never-styled run defaults its single segment to the *closest base-14 approximation* of the run's own detected font (serif → times, monospace → courier, else helvetica) instead of Sub-project 4's current hardcoded-to-helvetica default — so the visual regression is "closest base-14 match" rather than "always Helvetica."
- **Character-level selection.** Any character range can be selected and restyled — not word-level-only. (Confirmed by the user during brainstorming.)
- **Two-phase interaction, not one continuous rich-text surface.** Typing/committing the base text is phase `"type"` — a plain single-style `<input>`, unchanged from Sub-project 4 except for now writing/reading `segments` instead of `text`/`font_override`. Styling a selection is phase `"style"` — a *separate* interaction on already-typed, static text; a run enters phase `"style"` only when *reopened* after already being committed (double-clicking a run with no pending edit always opens phase `"type"`; double-clicking one with a pending edit opens phase `"style"`). Applying a style commits immediately (`commitElements`) — there is no "type" step interleaved with styling.
- **Proportional combined-shrink.** If the segments' combined measured width exceeds the run's original width, every segment's size is multiplied by the *same* scale factor (never independently) — preserving relative size differences between segments. The scale factor itself is still floored at `_TEXT_EDIT_SHRINK_FACTOR` (0.5) and each segment's *final* size is still floored at the absolute `_TEXT_EDIT_MIN_SIZE` (6pt), exactly generalizing today's single-segment shrink formula (which is the N=1 case of this same logic).
- **Defensive focus handling for every new conditionally-rendered focusable control.** Sub-project 4's fix wave found and fixed a real bug: a focusable button that conditionally unmounts itself immediately after being clicked (because the very click changed the condition it's rendered under) drops the browser's focus silently, since React can't dispatch a blur through an already-deleted fiber — permanently wedging `runEditor` non-null and disabling every keyboard shortcut in the tool. This plan's new floating popover is exactly this kind of control (its own visibility is gated on `runEditor.selection`, and a naive "auto-clear selection on any click" design would make its buttons vanish mid-click the same way). Task 3 designs around this from the start: `runEditor.selection` is **only** ever set/replaced by a fresh drag-selection ending (an `onMouseUp` on the styled-text view itself, in phase `"style"`); it is never cleared reactively by a global `selectionchange` listener or by the browser's native selection collapsing for any other reason. This means clicking a popover control cannot unmount the popover as a side effect, without needing to special-case every individual button.
- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. This plan's task commits are all `feat:`/`docs:` and must **not** carry the trailer.
- No frontend automated tests (established project convention) — `npm run build` plus a specific manual browser checklist per frontend task.
- Backend changes follow TDD with concrete, empirically-verified assertions (span inspection via `get_text("dict")`, ratio-based shrink comparison) — every numeric value used in this plan's backend tests was verified by directly running the equivalent code against real PDFs before being written here.

---

### Task 1: Backend — segments data model, multi-segment placement, proportional shrink

**Files:**
- Modify: `app/core/pdf_ops.py` (`_apply_text_edit`, `edit_pdf`'s text-edit loop; delete `_extract_embedded_font`, `_SUBSET_PREFIX_RE`)
- Modify: `web/backend/routes/tools.py` (`TextEditElement`; add `TextSegment`)
- Modify: `tests/test_pdf_ops.py` (update 3 existing tests to the new shape, delete the embedded-font test, add 2 new tests)
- Modify: `tests/web/test_tools_edit_convert.py` (update 1 existing route-level test to the new shape)

**Interfaces:**
- Consumes: `_base14_alias(family, bold, italic)`, `_hex_to_rgb` (unused here, `fitz.sRGB_to_pdf` is what's actually used for a run's color), `_TEXT_EDIT_MIN_SIZE` (6), `_TEXT_EDIT_SHRINK_FACTOR` (0.5) — all pre-existing, unchanged.
- Produces: `_apply_text_edit(page: fitz.Page, span: dict, segments: list[dict]) -> list[tuple]` — returns one `(fitz.Point, str, str, float, tuple)` tuple (origin, text, fontname, size, color) per segment, in order. `edit_pdf`'s loop now does `pending_inserts.extend(...)` instead of `pending_inserts.append(...)`, and each tuple unpacks to 5 values (not 6 — `embedded_buf` is gone). The `TextSegment` Pydantic model (`{text: str, family: str, bold: bool, italic: bool, size: float}`) and `TextEditElement.segments: list[TextSegment]` (replacing `text`/`font_override`) are what later tasks' frontend commit path sends.

- [ ] **Step 1: Write the failing tests for multi-segment placement and proportional shrink**

Add to `tests/test_pdf_ops.py`, near `test_edit_pdf_text_edit_auto_shrinks_when_overflowing`:

```python
def test_edit_pdf_text_edit_places_multiple_segments_side_by_side(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "This is the original run text here", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{
            "type": "text_edit", "page": 1, "run_index": 0,
            "segments": [
                {"text": "Hello ", "family": "helvetica", "bold": False, "italic": False, "size": 14},
                {"text": "World", "family": "helvetica", "bold": True, "italic": False, "size": 14},
            ],
        }],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 2
    assert spans[0]["text"] == "Hello "
    assert spans[0]["font"] == "Helvetica"
    assert not (spans[0]["flags"] & 16)  # not bold
    assert spans[1]["text"] == "World"
    assert spans[1]["font"] == "Helvetica-Bold"
    assert spans[1]["flags"] & 16  # bold
    # Both segments sit on the same baseline; the second starts exactly where
    # the first's measured width ends (verified empirically: 72.0 -> 107.78).
    assert spans[0]["origin"][1] == spans[1]["origin"][1]
    assert spans[1]["origin"][0] > spans[0]["origin"][0]
    assert spans[1]["origin"][0] == pytest.approx(72.0 + fitz.get_text_length("Hello ", fontname="helv", fontsize=14), abs=0.5)


def test_edit_pdf_text_edit_shrinks_all_segments_by_the_same_proportional_factor(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hi there", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{
            "type": "text_edit", "page": 1, "run_index": 0,
            # Combined width (~100.6pt at these sizes) overflows the original
            # run's ~49pt width, forcing a shrink. 20pt/30pt has a 1.5 ratio —
            # verified empirically: at scale 0.5 (the shrink floor), this
            # produces exactly 10pt/15pt, preserving the 1.5 ratio exactly.
            "segments": [
                {"text": "Hi", "family": "helvetica", "bold": False, "italic": False, "size": 20},
                {"text": " there", "family": "helvetica", "bold": True, "italic": False, "size": 30},
            ],
        }],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 2
    assert spans[0]["size"] < 20  # actually shrunk
    assert spans[1]["size"] < 30  # actually shrunk
    # The RATIO between the two sizes must be preserved (proportional, not
    # independent, shrinking) — not just that both got smaller.
    assert spans[1]["size"] / spans[0]["size"] == pytest.approx(30 / 20, rel=0.01)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k "multiple_segments or same_proportional" -v`
Expected: both FAIL — `edit_pdf` currently expects `el["text"]`/`el.get("font_override")`, not `el["segments"]`, so this raises a `KeyError: 'text'`.

- [ ] **Step 3: Rewrite `_apply_text_edit` for segments, delete the embedded-font path**

In `app/core/pdf_ops.py`, replace the entire `_apply_text_edit` function (currently around lines 578-637):

```python
def _apply_text_edit(page: fitz.Page, span: dict, segments: list[dict]) -> list[tuple]:
    """Adds the redact annotation for this run's original text and returns one
    (origin, text, fontname, size, color) tuple per segment, in left-to-right
    order, needed to insert the replacement side-by-side on the same
    baseline.

    Verified empirically (unchanged from before this function supported
    multiple segments): inserting replacement text right away (before
    page.apply_redactions() has actually run) does NOT work in this PyMuPDF
    build — the new text overlaps the same rect as the pending redaction
    annotation, and apply_redactions() clips/removes it right along with the
    original, since redaction acts on whatever is in the content stream at
    the moment it runs, not just what was there when the annotation was
    added. The caller must call page.apply_redactions() first and only then
    insert the text this function returns.
    """
    raw_bbox = fitz.Rect(span["bbox"])
    page.add_redact_annot(raw_bbox, fill=(1, 1, 1))

    # Every segment always specifies an explicit base-14 family/bold/italic —
    # this run's original detected/embedded font is never reused once any
    # edit exists, a deliberate simplification (see this plan's Global
    # Constraints: "embedded/detected-font preservation is removed").
    resolved = [
        (seg["text"], _base14_alias(seg["family"], seg["bold"], seg["italic"]), seg["size"])
        for seg in segments
    ]
    total_measured = sum(fitz.get_text_length(text, fontname=fontname, fontsize=size) for text, fontname, size in resolved)

    original_width = raw_bbox.width
    scale = 1.0
    if total_measured > original_width > 0:
        # ONE shared scale factor applied to every segment — never
        # independently — is what preserves the relative size differences
        # between segments. Floored at _TEXT_EDIT_SHRINK_FACTOR so no
        # segment ever shrinks more than 50% in one step, exactly
        # generalizing the pre-existing single-segment formula (which is
        # the N=1 case of this same shape: max(raw_scale, SHRINK_FACTOR)).
        scale = max(_TEXT_EDIT_SHRINK_FACTOR, original_width / total_measured)

    # span["color"] is an sRGB integer; sRGB_to_pdf turns it into the (r, g, b)
    # float triple insert_text's color= expects. Keeping the run's own colour
    # means replacement text no longer silently turns black on coloured runs.
    # Color is NOT per-segment — only family/bold/italic/size are stylable
    # per this sub-project's scope; every segment on a line keeps the run's
    # one original color.
    color = fitz.sRGB_to_pdf(span.get("color", 0))

    inserts = []
    x = raw_bbox.x0
    y = span["origin"][1]
    for text, fontname, size in resolved:
        # Absolute floor applied to each segment's FINAL size, same safety
        # net the single-segment formula already had via
        # max(_TEXT_EDIT_MIN_SIZE, ...).
        final_size = max(size * scale, _TEXT_EDIT_MIN_SIZE)
        inserts.append((fitz.Point(x, y), text, fontname, final_size, color))
        x += fitz.get_text_length(text, fontname=fontname, fontsize=final_size)
    return inserts
```

Delete `_extract_embedded_font` and `_SUBSET_PREFIX_RE` entirely (currently around lines 495-522) — nothing else in the codebase calls them (verified: `grep -rn "_extract_embedded_font\|_SUBSET_PREFIX_RE"` across `app/` and `tests/` finds only their own definition/the one test being deleted in Step 6).

- [ ] **Step 4: Update `edit_pdf`'s text-edit loop**

In `app/core/pdf_ops.py`, find the text-edit loop inside `edit_pdf` (currently around lines 883-900):

```python
        for page_num, page_edits in text_edits_by_page.items():
            page = doc[page_num - 1]
            spans = run_cache[page_num]
            pending_inserts = []
            for i, el in enumerate(page_edits):
                span = spans[el["run_index"]]
                pending_inserts.append(
                    _apply_text_edit(doc, page, span, el["text"], el.get("font_override"), f"TE{page_num}_{i}")
                )
            page.apply_redactions()
            for origin, text, fontname, size, embedded_buf, color in pending_inserts:
                # apply_redactions() wipes the page's font resources, so an
                # embedded font must be (re-)registered here, after redaction
                # has already run, immediately before the insert_text() call
                # that needs it — registering it earlier is silently undone.
                if embedded_buf is not None:
                    page.insert_font(fontname=fontname, fontbuffer=embedded_buf)
                page.insert_text(origin, text, fontsize=size, fontname=fontname, color=color)
```

Replace with:

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

- [ ] **Step 5: Run the two new tests, then the rest of the text-edit tests, to confirm they still reference the old shape**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k "multiple_segments or same_proportional" -v`
Expected: PASS (both new tests).

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k text_edit -v`
Expected: the 3 pre-existing tests using the old `text`/`font_override` shape now FAIL with `KeyError: 'segments'`, and `test_edit_pdf_text_edit_uses_subset_embedded_font` FAILS or errors (it calls the old signature) — this is expected; Step 6 fixes them.

- [ ] **Step 6: Update the 3 pre-existing text-edit tests to the new shape, delete the embedded-font test**

In `tests/test_pdf_ops.py`, find each of these three element dicts and replace:

```python
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": "Goodbye Mars", "font_override": None}],
```
→
```python
        [{
            "type": "text_edit", "page": 1, "run_index": 0,
            "segments": [{"text": "Goodbye Mars", "family": "helvetica", "bold": False, "italic": False, "size": 14}],
        }],
```
(in `test_edit_pdf_text_edit_replaces_text_and_keeps_surrounding_content`)

```python
        [{"type": "text_edit", "page": 1, "run_index": target["index"], "text": "OMEGA REPLACED", "font_override": None}],
```
→
```python
        [{
            "type": "text_edit", "page": 1, "run_index": target["index"],
            "segments": [{"text": "OMEGA REPLACED", "family": "helvetica", "bold": False, "italic": False, "size": 20}],
        }],
```
(in `test_edit_pdf_text_edit_handles_rotated_page` — size 20 matches `page.insert_text((72, 700), "OMEGA ORIGINAL")`'s default fontsize of 11... actually check: `page.insert_text` without an explicit `fontsize=` defaults to 11pt. Use `"size": 11` to match the original call's default exactly, avoiding an unrelated auto-shrink from an arbitrarily-chosen size.)

```python
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": long_text, "font_override": None}],
```
→
```python
        [{
            "type": "text_edit", "page": 1, "run_index": 0,
            "segments": [{"text": long_text, "family": "helvetica", "bold": False, "italic": False, "size": 20}],
        }],
```
(in `test_edit_pdf_text_edit_auto_shrinks_when_overflowing` — 20 matches the original run's own `fontsize=20`, preserving this test's exact intent.)

Delete `test_edit_pdf_text_edit_uses_subset_embedded_font` entirely (it tests a code path — embedded font preservation — that no longer exists; see this plan's Global Constraints for why).

- [ ] **Step 7: Update the Pydantic request models**

In `web/backend/routes/tools.py`, find `TextEditElement` (currently around lines 300-305):

```python
class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    text: str
    font_override: FontOverride | None = None
```

Replace with:

```python
class TextSegment(BaseModel):
    text: str
    family: str
    bold: bool
    italic: bool
    # A blanked number input arrives as 0 from the frontend; insert_text()
    # accepts fontsize=0 silently, rendering the segment invisible. Reject it
    # here, matching FontOverride.size/NewTextElement.size's identical guard.
    size: float = Field(gt=0)


class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    segments: list[TextSegment] = Field(min_length=1)
```

`FontOverride` (used only by `TextEditElement` before this change) is now unused — remove it too (currently around lines 290-297); confirm nothing else references it (`grep -n "FontOverride" web/backend/routes/tools.py` should show only its own definition and the one `TextEditElement` field being removed here).

- [ ] **Step 8: Update the route-level test**

In `tests/web/test_tools_edit_convert.py`, find (around line 325-336):

```python
def test_edit_pdf_text_edit_element_succeeds():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "text_edit", "page": 1, "run_index": 0, "text": "Replaced", "font_override": None}
            ],
        },
    )
    assert response.status_code == 200
```

Replace the `elements` list entry with:

```python
                {
                    "type": "text_edit", "page": 1, "run_index": 0,
                    "segments": [{"text": "Replaced", "family": "helvetica", "bold": False, "italic": False, "size": 14}],
                }
```

- [ ] **Step 9: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing. Starting count is 186 (before this task); this task adds 2 new tests and removes 1 (the embedded-font test), so expect 187.

- [ ] **Step 10: Commit**

```bash
git add app/core/pdf_ops.py web/backend/routes/tools.py tests/test_pdf_ops.py tests/web/test_tools_edit_convert.py
git commit -m "feat: replace text_edit's single style with an ordered list of styled segments"
```

No `Co-Authored-By` trailer.

---

### Task 2: Frontend — migrate the commit path to segments

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`

**Interfaces:**
- Consumes: Task 1's `TextEditElement.segments` shape (`[{text, family, bold, italic, size}]`), unchanged `pendingTextEditFor(run)`, `commitElements`, `elements`, `newElementId`, `newTextFontFamilyCss`, `FAMILY_OPTIONS`.
- Produces: `runEditor`'s new shape — `{ page, runIndex, phase: "type" | "style", segments: [{text, family, bold, italic, size}, ...], selection: {start, end} | null }` (replacing Sub-project 4's flat `{page, runIndex, text, family, bold, italic, size, familyTouched}`). `closestBase14Family(fontName)` (new). This task only ever produces/reads phase `"type"` and single-element `segments` arrays — Task 3 is what makes `phase: "style"` and multi-element `segments` reachable. After this task, the app's VISIBLE behavior for plain typing is byte-for-byte identical to Sub-project 4 (same UI, same interactions) — only the underlying data shape changes.

- [ ] **Step 1: Add `closestBase14Family`**

Add near `newTextFontFamilyCss` in `web/frontend/src/components/EditPdfCanvas.jsx`:

```jsx
// Mirrors app/core/pdf_ops.py's _closest_base14_family exactly, so a
// freshly-opened run's default style is the closest base-14 APPROXIMATION
// of its actually-detected font (serif -> times, monospace -> courier, else
// helvetica) instead of always defaulting to helvetica regardless of the
// run's real font — see this plan's Global Constraints for why the run's
// actual embedded font itself can no longer be preserved once any edit
// exists.
function closestBase14Family(fontName) {
  const lowered = (fontName || "").toLowerCase();
  if (lowered.includes("times") || lowered.includes("serif") || lowered.includes("georgia")) return "times";
  if (lowered.includes("courier") || lowered.includes("mono") || lowered.includes("consolas")) return "courier";
  return "helvetica";
}
```

- [ ] **Step 2: Rewrite `openRunEditor` to build `segments`**

Find (around line 782-796):

```jsx
  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    // Re-opening a queued edit that already carries an override means its
    // family was an explicit choice — keep it explicit.
    setRunEditor({
      page: pageNumber,
      runIndex: run.index,
      text: pending ? pending.text : run.text,
      family: pending?.font_override?.family ?? "helvetica",
      bold: pending?.font_override?.bold ?? run.bold,
      italic: pending?.font_override?.italic ?? run.italic,
      size: pending?.font_override?.size ?? run.size,
      familyTouched: Boolean(pending?.font_override),
    });
  }
```

Replace with:

```jsx
  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    // No pending edit: nothing to style yet, open straight into typing.
    // A pending edit already exists: open into the styling view instead
    // (Task 3) — reopening an already-committed run is normally to review
    // or restyle it, not retype it from scratch. "Edit text" (Task 3) is
    // the explicit way back into phase "type" from there.
    const segments = pending
      ? pending.segments
      : [{ text: run.text, family: closestBase14Family(run.font), bold: run.bold, italic: run.italic, size: run.size }];
    setRunEditor({
      page: pageNumber,
      runIndex: run.index,
      phase: pending ? "style" : "type",
      segments,
      selection: null,
    });
  }
```

- [ ] **Step 3: Rewrite `commitRunEditor` for `segments`, gate it on phase `"type"`**

Find (around line 798-826):

```jsx
  function commitRunEditor() {
    const editor = runEditor;
    setRunEditor(null);
    if (!editor) return;
    const run = runs.find((r) => r.index === editor.runIndex && r.page === editor.page);
    if (!run) return;
    const pending = pendingTextEditFor(run);
    const overrideChanged =
      editor.familyTouched || editor.bold !== run.bold || editor.italic !== run.italic || editor.size !== run.size;
    const textChanged = editor.text !== run.text;
    // Nothing pending and nothing changed from the run's own detected
    // text/font — the user opened the editor and closed it without editing
    // anything. Skip queuing a no-op text_edit so merely looking at a run
    // doesn't clutter `elements`/undo history. An empty text IS a real
    // change whenever the run originally had text (textChanged catches
    // this), and is deliberately committed as an erase per this
    // sub-project's design — never treated as "nothing to do".
    if (!pending && !textChanged && !overrideChanged) return;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editor.page,
      run_index: editor.runIndex,
      text: editor.text,
      font_override: overrideChanged ? { family: editor.family, bold: editor.bold, italic: editor.italic, size: editor.size } : null,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }
```

Replace with:

```jsx
  // Only ever called while phase === "type" (see handleRunEditorBlur) — in
  // phase "style", every restyle action already commits immediately
  // (Task 3's applySelectionStyle), so there is nothing left to commit on
  // blur there.
  function commitRunEditor() {
    const editor = runEditor;
    setRunEditor(null);
    if (!editor) return;
    const run = runs.find((r) => r.index === editor.runIndex && r.page === editor.page);
    if (!run) return;
    const pending = pendingTextEditFor(run);
    const seg = editor.segments[0];
    const isDefaultStyle =
      seg.family === closestBase14Family(run.font) && seg.bold === run.bold && seg.italic === run.italic && seg.size === run.size;
    const textChanged = seg.text !== run.text;
    // Nothing pending and nothing changed from the run's own detected
    // text/default style — the user opened the editor and closed it without
    // editing anything. Skip queuing a no-op text_edit so merely looking at
    // a run doesn't clutter `elements`/undo history. An empty text IS a
    // real change whenever the run originally had text (textChanged catches
    // this), and is deliberately committed as an erase per this
    // sub-project's design — never treated as "nothing to do".
    if (!pending && !textChanged && isDefaultStyle) return;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editor.page,
      run_index: editor.runIndex,
      segments: [{ text: seg.text, family: seg.family, bold: seg.bold, italic: seg.italic, size: seg.size }],
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }
```

- [ ] **Step 4: Update `revertRunEditor` and `handleRunEditorBlur`**

Find (around line 828-841):

```jsx
  function revertRunEditor(run) {
    const pending = pendingTextEditFor(run);
    if (pending) commitElements(elements.filter((el) => el.id !== pending.id));
    // Reset the still-open editor's fields back to the run's own detected
    // text/font so the input reflects the original immediately — no need to
    // close and reopen it to see the un-edited state.
    setRunEditor((e) => ({ ...e, text: run.text, family: "helvetica", bold: run.bold, italic: run.italic, size: run.size, familyTouched: false }));
  }

  function handleRunEditorBlur(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) {
      commitRunEditor();
    }
  }
```

Replace with:

```jsx
  function revertRunEditor(run) {
    const pending = pendingTextEditFor(run);
    if (pending) commitElements(elements.filter((el) => el.id !== pending.id));
    // Reset the still-open editor back to phase "type" showing the run's own
    // detected text/font — nothing styled remains once reverted, so there is
    // nothing left to show in phase "style".
    setRunEditor((e) => ({
      ...e,
      phase: "type",
      segments: [{ text: run.text, family: closestBase14Family(run.font), bold: run.bold, italic: run.italic, size: run.size }],
      selection: null,
    }));
  }

  function handleRunEditorBlur(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) {
      if (runEditor?.phase === "type") commitRunEditor();
      else setRunEditor(null);
    }
  }
```

- [ ] **Step 5: Update `renderRunEditorOverlay`'s phase-`"type"` rendering to read/write `segments[0]`**

Find the current `renderRunEditorOverlay` function (around line 1237-1305) — it currently reads `runEditor.text`/`runEditor.family`/`runEditor.bold`/`runEditor.italic`/`runEditor.size` directly and writes them via `setRunEditor((r) => ({...r, text: ...}))` etc. Replace every one of those reads/writes so they go through `runEditor.segments[0]` instead, keeping the exact same JSX structure, controls, and CSS classes — only the state paths change. The full function becomes:

```jsx
  function renderRunEditorOverlay(run) {
    if (runEditor.phase === "style") {
      return renderRunStyleOverlay(run); // Task 3
    }
    const seg = runEditor.segments[0];
    function updateSeg(patch) {
      setRunEditor((r) => ({ ...r, segments: [{ ...r.segments[0], ...patch }] }));
    }
    return (
      <div
        key={run.index}
        className="edit-pdf-canvas__run-editor-inline"
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onBlur={handleRunEditorBlur}
      >
        <input
          ref={runEditorInputRef}
          type="text"
          className="edit-pdf-canvas__run-editor-input"
          value={seg.text}
          onChange={(e) => updateSeg({ text: e.target.value })}
          style={{
            fontFamily: newTextFontFamilyCss(seg.family),
            fontWeight: seg.bold ? "bold" : "normal",
            fontStyle: seg.italic ? "italic" : "normal",
            fontSize: `${seg.size}px`,
          }}
        />
        <div className="edit-pdf-canvas__new-text-style-bar">
          <select value={seg.family} onChange={(e) => updateSeg({ family: e.target.value })}>
            {FAMILY_OPTIONS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <input type="number" min={1} value={seg.size} onChange={(e) => updateSeg({ size: Number(e.target.value) })} />
          <button
            type="button"
            className={seg.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
            onClick={() => updateSeg({ bold: !seg.bold })}
            aria-label="Bold"
          >
            <TextB size={14} weight="bold" />
          </button>
          <button
            type="button"
            className={seg.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
            onClick={() => updateSeg({ italic: !seg.italic })}
            aria-label="Italic"
          >
            <TextItalic size={14} weight="bold" />
          </button>
          {pendingTextEditFor(run) && (
            <button
              type="button"
              className="edit-pdf-canvas__width-button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => revertRunEditor(run)}
            >
              Revert
            </button>
          )}
        </div>
      </div>
    );
  }
```

`renderRunStyleOverlay` doesn't exist yet — Task 3 adds it. Add a temporary stub right above `renderRunEditorOverlay` so the file compiles between this task and Task 3:

```jsx
  function renderRunStyleOverlay(run) {
    return null; // replaced in the next task
  }
```

(Since `openRunEditor` only ever sets `phase: "style"` when `pendingTextEditFor(run)` is truthy — i.e., only for a run that ALREADY has a committed edit from a *previous* session/reload — this stub is unreachable in this task's own manual testing unless you manually queue an edit and then reload; that's fine, Task 3 replaces it before shipping.)

- [ ] **Step 6: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 7: Manual browser check**

Confirm every one of Sub-project 4's original behaviors still works, now producing `segments` under the hood:

- Double-click a never-edited run, type text, click away — commits. Re-open: shows the typed text (phase "type", since re-checking `pendingTextEditFor` after a fresh page load would show phase "style" — for THIS manual check, re-opening in the *same session* without a reload still triggers `pending` to exist, so it opens into the stub's `null` — this is expected per Step 5's note; to verify the commit actually reflects the segment correctly, inspect via `elements` state in devtools or by running the tool, not by re-opening the editor in this task's own testing).
- Run the tool with a plain single-segment edit; confirm the downloaded PDF shows the new text.
- Clear a run's text and click away; run the tool; confirm the text is genuinely erased from the output (unchanged from Sub-project 4).
- Change family/bold/italic/size in phase "type" and click away; run the tool; confirm the override applies (font/flags/size visible via `page.get_text("dict")` on the output, same verification method Sub-project 4's own report used).
- A freshly-opened run whose detected font is a serif or monospace font (if you have a suitable test PDF) defaults its family to "times"/"courier" respectively, not always "helvetica" — confirms `closestBase14Family` is wired in.
- Undo/redo still works for a committed text edit.
- Opening a run's editor and closing it with NO changes still doesn't queue a no-op edit.

- [ ] **Step 8: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx
git commit -m "feat: migrate the run editor's commit path to the new segments shape"
```

No `Co-Authored-By` trailer.

---

### Task 3: Frontend — selection-driven partial restyling

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: Task 2's `runEditor` shape (`{page, runIndex, phase, segments, selection}`), `pendingTextEditFor`, `commitElements`, `elements`, `newElementId`, `newTextFontFamilyCss`, `FAMILY_OPTIONS`, `revertRunEditor`.
- Produces: `renderRunStyleOverlay(run)` (replacing Task 2's stub), `handleStyleSelectionChange(run)`, `applySelectionStyle(run, patch)`, `splitAndRestyleSegments(segments, start, end, patch)`, `mergeAdjacentSegments(segments)`, `segmentsEqualStyle(a, b)`, `segmentStyleForRange(segments, selection)`.

- [ ] **Step 1: Add the pure segment-splitting helpers**

Add near `estimateMinTextBoxSize` (or any other pure helper function) in `web/frontend/src/components/EditPdfCanvas.jsx`:

```jsx
function segmentsEqualStyle(a, b) {
  return a.family === b.family && a.bold === b.bold && a.italic === b.italic && a.size === b.size;
}

// Merges adjacent segments that ended up with identical style after a split
// — keeps the list from growing unboundedly across repeated restyles of
// overlapping ranges (e.g. styling the same word bold twice in a row should
// not leave two separate bold segments sitting next to each other).
function mergeAdjacentSegments(segments) {
  const merged = [];
  for (const seg of segments) {
    const last = merged[merged.length - 1];
    if (last && segmentsEqualStyle(last, seg)) {
      last.text += seg.text;
    } else {
      merged.push({ ...seg });
    }
  }
  return merged;
}

// Splits whichever segment(s) the [start, end) character range (0-indexed,
// into the CONCATENATED text of all segments in order) overlaps, at the
// exact character boundary, and applies `patch` (e.g. {bold: true}) only to
// the newly-split piece(s) covering the selected text. Every segment fully
// outside the range is returned unchanged.
function splitAndRestyleSegments(segments, start, end, patch) {
  const result = [];
  let offset = 0;
  for (const seg of segments) {
    const segStart = offset;
    const segEnd = offset + seg.text.length;
    offset = segEnd;
    const overlapStart = Math.max(start, segStart);
    const overlapEnd = Math.min(end, segEnd);
    if (overlapStart >= overlapEnd) {
      result.push(seg);
      continue;
    }
    const beforeText = seg.text.slice(0, overlapStart - segStart);
    const insideText = seg.text.slice(overlapStart - segStart, overlapEnd - segStart);
    const afterText = seg.text.slice(overlapEnd - segStart);
    if (beforeText) result.push({ ...seg, text: beforeText });
    result.push({ ...seg, ...patch, text: insideText });
    if (afterText) result.push({ ...seg, text: afterText });
  }
  return mergeAdjacentSegments(result);
}

// The style to pre-fill the popover's controls with: the FIRST segment the
// selection overlaps. If the selection spans multiple differently-styled
// segments, this is a reasonable single representative rather than an
// attempt to show a "mixed" state — consistent with this file's existing
// "first segment wins" default pattern (see openRunEditor's family default).
function segmentStyleForRange(segments, selection) {
  let offset = 0;
  for (const seg of segments) {
    const segEnd = offset + seg.text.length;
    if (selection.start < segEnd && selection.end > offset) {
      return { family: seg.family, bold: seg.bold, italic: seg.italic, size: seg.size };
    }
    offset = segEnd;
  }
  return { family: "helvetica", bold: false, italic: false, size: 14 };
}
```

- [ ] **Step 2: Add the selection handler and the apply-style action**

Add near `revertRunEditor`:

```jsx
  // Only ever called from the styled-text view's onMouseUp (phase "style").
  // Deliberately the ONLY place `runEditor.selection` is ever written — see
  // this plan's Global Constraints on why it must never be cleared
  // reactively by native-selection-collapse or a global selectionchange
  // listener (doing so would let the popover unmount itself mid-click on
  // its own controls, the exact bug class Sub-project 4's fix wave found).
  function handleStyleSelectionChange(run) {
    const sel = window.getSelection();
    const container = document.querySelector(`[data-run-style-text="${runEditor.page}-${run.index}"]`);
    if (!sel || sel.isCollapsed || sel.rangeCount === 0 || !container || !container.contains(sel.anchorNode) || !container.contains(sel.focusNode)) {
      setRunEditor((r) => (r ? { ...r, selection: null } : r));
      return;
    }
    const anchorSpan = sel.anchorNode.nodeType === Node.TEXT_NODE ? sel.anchorNode.parentElement : sel.anchorNode;
    const focusSpan = sel.focusNode.nodeType === Node.TEXT_NODE ? sel.focusNode.parentElement : sel.focusNode;
    const anchorGlobal = Number(anchorSpan.dataset.segStart) + sel.anchorOffset;
    const focusGlobal = Number(focusSpan.dataset.segStart) + sel.focusOffset;
    const start = Math.min(anchorGlobal, focusGlobal);
    const end = Math.max(anchorGlobal, focusGlobal);
    setRunEditor((r) => (r ? { ...r, selection: start === end ? null : { start, end } } : r));
  }

  function applySelectionStyle(run, patch) {
    if (!runEditor || !runEditor.selection) return;
    const { start, end } = runEditor.selection;
    const newSegments = splitAndRestyleSegments(runEditor.segments, start, end, patch);
    setRunEditor((r) => ({ ...r, segments: newSegments }));
    const pending = pendingTextEditFor(run);
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: runEditor.page,
      run_index: runEditor.runIndex,
      segments: newSegments,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }
```

- [ ] **Step 3: Replace the Task 2 stub with the real `renderRunStyleOverlay`**

Find the stub added in Task 2:

```jsx
  function renderRunStyleOverlay(run) {
    return null; // replaced in the next task
  }
```

Replace with:

```jsx
  function renderRunStyleOverlay(run) {
    let offset = 0;
    const spanEls = runEditor.segments.map((seg, i) => {
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
    return (
      <div
        key={run.index}
        className="edit-pdf-canvas__run-editor-inline"
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onBlur={handleRunEditorBlur}
      >
        <div
          className="edit-pdf-canvas__run-style-text"
          data-run-style-text={`${runEditor.page}-${run.index}`}
          onMouseUp={() => handleStyleSelectionChange(run)}
        >
          {spanEls}
        </div>
        <div className="edit-pdf-canvas__new-text-style-bar">
          <button
            type="button"
            className="edit-pdf-canvas__width-button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setRunEditor((r) => ({ ...r, phase: "type", segments: [flattenSegmentsForTyping(r.segments)], selection: null }))}
          >
            Edit text
          </button>
          {pendingTextEditFor(run) && (
            <button
              type="button"
              className="edit-pdf-canvas__width-button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => revertRunEditor(run)}
            >
              Revert
            </button>
          )}
        </div>
        {runEditor.selection && renderStylePopover(run)}
      </div>
    );
  }
```

`flattenSegmentsForTyping` returns a single segment OBJECT (not an array) — the call site above wraps it in an array itself (`[flattenSegmentsForTyping(...)]`) to produce the one-element `segments` list phase `"type"` expects. Add it next to the other helpers from Step 1:

```jsx
  // Collapses a multi-segment styled line back into ONE segment for phase
  // "type" — concatenates every segment's TEXT (so no characters are lost),
  // using the FIRST segment's style as phase "type"'s single style. This is
  // a deliberate, spec-consistent trade-off: phase "type" is a single-style
  // input by design, so re-entering it to retype necessarily discards any
  // partial styling that existed before — you can't "type into" a
  // multi-styled line while preserving per-character styles without
  // reintroducing the hard live-sync problem this two-phase design exists
  // to avoid.
  function flattenSegmentsForTyping(segments) {
    const text = segments.map((s) => s.text).join("");
    const first = segments[0];
    return { text, family: first.family, bold: first.bold, italic: first.italic, size: first.size };
  }
```

- [ ] **Step 4: Add `renderStylePopover`**

Add near `renderRunStyleOverlay`:

```jsx
  function renderStylePopover(run) {
    const style = segmentStyleForRange(runEditor.segments, runEditor.selection);
    return (
      <div className="edit-pdf-canvas__style-popover">
        <select
          value={style.family}
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => applySelectionStyle(run, { family: e.target.value })}
        >
          {FAMILY_OPTIONS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={1}
          value={style.size}
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => applySelectionStyle(run, { size: Number(e.target.value) })}
        />
        <button
          type="button"
          className={style.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => applySelectionStyle(run, { bold: !style.bold })}
          aria-label="Bold selection"
        >
          <TextB size={14} weight="bold" />
        </button>
        <button
          type="button"
          className={style.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => applySelectionStyle(run, { italic: !style.italic })}
          aria-label="Italicize selection"
        >
          <TextItalic size={14} weight="bold" />
        </button>
      </div>
    );
  }
```

(The family `<select>` and size `<input type="number">` use `onMouseDown={(e) => e.stopPropagation()}`, not `preventDefault()` — they genuinely need the browser's normal focus/click behavior to work as inputs, per this plan's Global Constraints note on why `runEditor.selection` is decoupled from live native-selection state: applying a style always uses the *stored* `runEditor.selection` range, never re-reading `window.getSelection()` at apply-time, so it doesn't matter if clicking into these two controls happens to collapse the native selection. `stopPropagation()` here only prevents the click from bubbling to the wrapper's own `onMouseDown={(e) => e.stopPropagation()}` in a way that could interfere with the input gaining focus normally — the Bold/Italic buttons use `preventDefault()` instead since they don't need focus themselves and this additionally keeps the visual text-selection highlight visible while toggling, matching how established rich-text editors handle their own formatting toolbars.)

- [ ] **Step 5: Add CSS**

In `web/frontend/src/index.css`:

```css
.edit-pdf-canvas__run-style-text {
  width: 100%;
  height: 100%;
  overflow: hidden;
  white-space: nowrap;
  /* .edit-pdf-canvas__stage sets user-select: none to stop accidental text
     selection during this tool's many drag interactions — this is a
     deliberate, narrow exception, since native drag-to-select IS the
     interaction this view exists for. */
  user-select: text;
  cursor: text;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid var(--color-accent);
  border-radius: 2px;
  padding: 2px 4px;
  box-sizing: border-box;
  line-height: 1.2;
}

.edit-pdf-canvas__style-popover {
  position: absolute;
  bottom: 100%;
  left: 0;
  margin-bottom: var(--space-1);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  z-index: 4;
}

.edit-pdf-canvas__style-popover select,
.edit-pdf-canvas__style-popover input[type="number"] {
  font-size: 12px;
  padding: 2px 4px;
}

.edit-pdf-canvas__style-popover input[type="number"] {
  width: 48px;
}
```

(The popover is positioned `bottom: 100%` — directly above the run, opposite the persistent `"Edit text"`/`"Revert"` toolbar which sits at `top: 100%` via the existing `.edit-pdf-canvas__new-text-style-bar` class — so the two never overlap.)

- [ ] **Step 6: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 7: Manual browser check**

- Type text into a run, click away to commit (phase "type", unchanged). Double-click the now-queued run again — it opens into phase "style", showing the committed text as read-only styled spans (all one style initially, since it's still a single segment).
- Drag-select part of the text (e.g. one word, or a few characters mid-word — confirming character-level, not word-level, precision) — a floating popover appears above the run.
- Click Bold in the popover — only the selected characters become bold; the rest of the line is visually unchanged. The popover stays open (does not disappear) after the click.
- Drag-select a DIFFERENT range and apply Italic — confirm the FIRST styled range keeps its bold styling, untouched, while the new range gets italic.
- Select a range that exactly matches an already-differently-styled segment's boundaries and apply the SAME style it already has — confirm adjacent segments merge back together (no visible seam), inspectable via the committed `elements` in devtools (`segments.length` should not keep growing from redundant restyles).
- Click "Edit text" — switches back to phase "type", showing a plain input pre-filled with the FULL concatenated text (all characters preserved, styling flattened to the first segment's style). Click away — recommits as a single segment (multi-styling from before is now gone, by design).
- Reopen the run (now single-segment again after the previous step) — click "Revert" — the queued edit is removed and the editor resets to phase "type" showing the run's original detected text.
- Type a long multi-styled line (via repeated select-and-style) whose combined segments overflow the run's original width — run the tool, download the output, and inspect it with a small PyMuPDF script (`get_text("dict")`) to confirm every segment's size shrank by the same visual proportion (compare the ratio between two differently-sized segments' output sizes against their ratio before shrinking) and that the downloaded output's text/styling matches what the editor's read-only view showed.
- Confirm Ctrl+Z/Escape and other keyboard shortcuts still work normally in the rest of the tool after opening, styling, and closing a run's editor in phase "style" — this is the specific regression class Sub-project 4's fix wave found; re-verify it wasn't reintroduced by the popover.

- [ ] **Step 8: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add drag-to-select partial restyling for committed text edits"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (187).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (3 total, following the `docs:` plan commit), in order, none carrying a `Co-Authored-By` trailer (all are `feat:`).
- [ ] Confirm no remaining reference anywhere in `app/core/pdf_ops.py`, `web/backend/routes/tools.py`, or `web/frontend/src/components/EditPdfCanvas.jsx` to `font_override`, `_extract_embedded_font`, `_SUBSET_PREFIX_RE`, `FontOverride`, `familyTouched`, or a `text_edit` element's flat `text` field (a plain text search for each should return nothing outside historical comments explaining their removal).
- [ ] This is the fifth and final sub-project of the original feedback batch — once this plan's final whole-branch review is clean and shipped, every item from the user's original feedback (Watermark size/rotation, and all nine numbered Edit PDF issues) has been addressed.

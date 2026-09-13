# Edit PDF: Movable In-Place Text Edits — Design

**Status:** Approved by user 2026-09-13.

## Context

Queued earlier this session: editing existing PDF text in Edit PDF (double-click a run to open
the inline editor) redacts the original text at its exact position and draws the replacement
starting from that same position — there's no way to move the replacement elsewhere. If the new
text is longer than the original, it visually extends rightward, which can look misaligned. The
user's existing workaround (a filled white shape covering the old text, plus a fully-movable
"Add Text" box on top) already solves the same problem, but takes two elements and two steps
instead of one.

Investigated before proposing anything (verified against the current codebase this session, not
assumed from memory):

- **Backend** (`app/core/pdf_ops.py`): `_apply_text_edit(page, span, segments)` redacts at
  `raw_bbox = fitz.Rect(span["bbox"])` and inserts the replacement starting at
  `x = raw_bbox.x0`, `y = span["origin"][1]` — position and redaction share the same source
  purely because nothing else was ever needed, not from any deeper coupling. The font-size
  auto-shrink math compares the replacement text's measured width against `raw_bbox.width` (the
  *original* run's width) — this is independent of where the text is eventually drawn, so it
  doesn't need to change if only position becomes overridable. `TextEditElement`'s Pydantic model
  (`web/backend/routes/tools.py`) currently has only `type, page, run_index, segments` — no
  position fields at all.
- **Frontend** (`web/frontend/src/components/EditPdfCanvas.jsx`): `text_edit` elements are
  currently excluded entirely from the generalized move/select/drag/z-order system every other
  element type already has (`el.type !== "text_edit"` in the per-page element filter;
  `renderElement`'s dispatcher has no case for it). They're instead rendered through a completely
  separate mechanism — `runs`/`runEditor` state, positioned via the *original* PDF text run's own
  detected bbox (`run.bbox`, from `fetchTextRuns`), never via anything stored on the `text_edit`
  element itself.
- A directly relevant, already-working precedent exists for the interaction split this needs:
  `new_text` elements (Add Text) already support single-click-to-select-and-drag vs.
  double-click-to-reopen-the-content-editor on the same element (`renderNewTextElement`).

## Scope decisions (from brainstorming)

- **Move only, not resize.** A `text_edit` element's box keeps the exact width/height the
  original run always had — dragging changes only where that box sits, never its size. This
  keeps the change additive: the existing font-auto-shrink-to-original-run-width behavior is
  completely untouched.
- **The double-click-to-edit target moves with the element.** Before any edit exists, double-
  clicking the original PDF text opens the editor there, unchanged from today. Once an edit
  exists (whether or not it's been moved), the original spot is genuinely blank (the old text
  was redacted) and stops being interactive — double-click access transfers entirely to the
  `text_edit` element's own current position, exactly mirroring how "Add Text" boxes work: there
  is always exactly one interactive target, wherever the element currently sits.
- **Revert restores position too.** The existing "Revert" action (which already restores the
  original text/style) also resets position back to the original run's location if the element
  had been moved — revert means "undo everything I did to this text," not just its content.
- **Full per-segment styling is shown even when not actively editing.** A `text_edit` element
  rendered as a static, draggable box (selected but not mid-edit) shows its real segment-level
  styling (bold/italic/size mixes from partial restyling), not a simplified single-style preview
  — the rendering logic for this already exists (`renderRunStyleOverlay`'s span-based approach)
  and is reused, not reinvented.

## Architecture

### Backend

`_apply_text_edit` gains an optional `override_origin: tuple[float, float] | None = None`
parameter. When provided (as absolute PDF point coordinates, already converted from the page-
fraction values the frontend sends), it's used as `(x, y)` instead of
`(raw_bbox.x0, span["origin"][1])` for the replacement text's insertion point. The redaction
itself — `page.add_redact_annot(raw_bbox, fill=(1, 1, 1))` — is completely unchanged; the
original text always disappears from its own original spot regardless of where the replacement
ends up.

`TextEditElement` (`web/backend/routes/tools.py`) gains two optional fields:
```python
class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    segments: list[TextSegment] = Field(min_length=1)
    x: float | None = None
    y: float | None = None
```
`edit_pdf`'s existing call site converts `x`/`y` (page fractions, 0-1, matching every other
element type's convention) into absolute point coordinates using the page's own rect (the same
conversion already used elsewhere in this file for fraction-based positioning) before passing
them to `_apply_text_edit` as `override_origin`. When `x`/`y` are absent (`None`), behavior is
byte-identical to today.

### Frontend

The per-page element filter's `el.type !== "text_edit"` exclusion is removed — `text_edit`
elements now flow through the same interleaved z-order rendering every other element type uses.
A new `renderTextEditElement(el, pageRef)` function (modeled directly on `renderNewTextElement`)
renders the element's segments with their real per-segment styling (reusing the span-rendering
approach from `renderRunStyleOverlay`) inside a box positioned at `el.x`/`el.y` (falling back to
the original run's own bbox position when the element has never been moved — i.e. `x`/`y` are
absent) with the *original run's* width/height (computed once, at creation time, from the run's
own bbox — never recomputed or user-resizable). Its `onMouseDown` starts a drag via the existing
`startElementDrag`/`moveElement` machinery (unchanged — `text_edit` just becomes one more
coordinate shape those functions handle, using the same `x`/`y`/`width`/`height` convention
`image`/`new_text` already use); its `onDoubleClick` reopens the run-style/type editor at the
element's *current* position (not the original run's).

`renderTextRun`'s own double-click handler and hit-area only render for a run when
`pendingTextEditFor(run)` returns nothing — once an edit exists (moved or not), the original
run's overlay stops being interactive entirely, since `renderTextEditElement` is now the sole
entry point back into editing that text.

`commitRunEditor`/`applySelectionStyle` (which create/update the `text_edit` element) preserve
whatever `x`/`y` the element already had (if it had been moved before this content/style change)
rather than resetting them — editing the text content or style is independent from where it's
positioned. `revertRunEditor` explicitly clears `x`/`y` back to absent (alongside its existing
reset of text/style) when it deletes the pending edit, so a subsequent re-edit starts fresh at
the original run's position, matching the "revert restores position too" scope decision.

## Testing

Backend: a new test in `tests/test_pdf_ops.py` confirming `edit_pdf` draws replacement text at
an overridden `x`/`y` position instead of the original run's position when a `text_edit` element
specifies one, alongside the existing tests confirming the no-override case remains byte-
identical. No changes needed to the font-auto-shrink tests (that logic is untouched).

Frontend: no automated tests (established convention for this project's frontend work) — a
manual checklist: edit an existing text run, confirm dragging the result moves it independent of
the original text's spot; confirm double-clicking the moved text reopens the editor at its
*current* location; confirm the original (now-blank) spot is no longer double-click-able once an
edit exists; confirm Revert restores both content/style and position together; confirm a
`text_edit` element's real per-segment styling (from a partial bold/italic restyle) renders
correctly while just sitting there selected, not only while actively editing it; confirm the
exported PDF's final result matches on-screen — the redacted original text is genuinely gone
from its old spot, and the replacement appears correctly at its new one.

## Out of scope

- Independent resizing of a `text_edit` element's box — its width/height always matches the
  original run's own dimensions, per the "move only" scope decision.
- Any change to the font-size auto-shrink logic — it continues to measure against the original
  run's width regardless of where the text is drawn.
- Multi-element selection or any change to how `text_edit` elements are created in the first
  place (double-clicking untouched PDF text still works exactly as it does today) — this spec
  only changes what happens to a `text_edit` element *after* it exists.

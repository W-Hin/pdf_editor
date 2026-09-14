# Edit PDF: Arrow-Key Nudge for Moved Text Edits + Rotated-Page Box Shape — Design

**Status:** Approved by user 2026-09-14.

## Context

Two items were parked (not fixed) during the final whole-branch review of the
"movable in-place text edits" plan (shipped earlier this session, commits
`b04ee2e`/`2b95933`/`829836a` — see
`docs/superpowers/specs/2026-09-13-pdf-editor-edit-pdf-movable-text-edit-design.md`
and its plan for how `text_edit` elements currently work) because the reviewer
judged both needed a real design decision rather than a quick patch:

1. Arrow-key nudge still excludes `text_edit` elements — a leftover exclusion
   from before this session's movable-text-edit work, back when `text_edit`
   couldn't be dragged at all. Naively removing it would be a live bug: a
   stored `text_edit` element never has `width`/`height` fields (deliberately —
   its box size always comes from its own run, never persisted), so
   `moveElement`'s `text_edit` branch would read `undefined`, propagate `NaN`
   into `x`/`y`, and the export would silently snap back to the original
   position with no error shown.

2. On a rotated page, a `text_edit` element's draggable box always mirrors the
   *original* run's own displayed-bbox dimensions, but the *moved* replacement
   text is drawn with `rotate=page.rotation` (`app/core/pdf_ops.py`'s
   `_apply_text_edit` override path) specifically so it reads upright to the
   viewer — meaning the box's shape can visually diverge from the exported
   text's actual extent.

Before proposing anything, item 2's actual real-world severity was checked
empirically (not assumed) against this app's own realistic rotated-and-OCR'd
fixture (the same one `tests/test_pdf_ops.py`'s `_build_rotated_ocr_pdf` uses
elsewhere): the found runs came out wide-short (~24pt × ~12pt, normal
horizontal orientation) in displayed space, matching how replacement text
also gets drawn — no mismatch in that realistic case. The mismatch only
occurs when a PDF's raw content is "uncompensated" relative to its own
`/Rotate` flag (genuinely sideways raw text under a rotation tag) — not
produced by normal PDF authoring tools or by this app's own OCR feature. A
real but rare case, not the common path.

**A third, more severe, previously-unknown bug was found during this same
empirical check** and shipped separately, ahead of this spec, as its own fix
(commit `8d2d2c0`, not part of this plan): `_page_text_spans` used PyMuPDF's
default text-extraction clip, which returned **zero spans** on any
rotated-and-OCR'd page — the exact same clipping bug already fixed this
session for Compare PDF and PDF-to-PowerPoint, just never applied to Edit
PDF. That meant a user literally could not double-click any text on such a
page at all. Already fixed and merged; mentioned here only for context, since
it's what made item 2's realistic-severity check possible in the first place.

## Scope decisions (from brainstorming)

- **Nudge is enabled for `text_edit` elements**, for consistency with every
  other draggable element type — the only reason it was ever excluded
  (couldn't be dragged at all) no longer applies.
- **The rotated-page box shape gets a targeted fix, not full dynamic sizing.**
  On a 90/270-rotated page, once a `text_edit` element has actually been
  moved, its box's width and height are transposed to match the orientation
  the replacement text is actually drawn in — same area/proportions as the
  original run, just rotated 90° to match. The box does **not** resize based
  on the actual length of the replacement content (a longer or shorter edit
  doesn't grow or shrink the box) — that remains exactly the same accepted
  limitation the "move only" design already has today for non-rotated pages,
  now applied consistently to rotated ones too.
- **A narrow, self-correcting edge case is accepted, not closed:** the very
  first drag of a `text_edit` element on a rotated page uses the pre-swap
  dimensions for its clamp bound (fixed once at drag-start, before the swap
  becomes active), so dropping it very close to a page edge on that first
  drag can show a small overflow past that edge. Dragging it again uses the
  now-current (already-swapped) dimensions and is correctly bounded. Closing
  this fully would mean reconciling two different clamp bases mid-gesture —
  real complexity for a cosmetic, self-fixing edge of an edge case.

## Architecture

### Item 1: nudge

`handleKeyDown`'s arrow-key branch (`web/frontend/src/components/EditPdfCanvas.jsx`,
currently around line 465) drops its `el.type !== "text_edit"` guard. For a
`text_edit` element specifically, before calling `moveElement`, the handler
looks up the matching run (`runs.find(r => r.page === el.page && r.index ===
el.run_index)`) and builds the same `positioned` object (`{...el, x, y,
width, height}`, via `textEditBoxRect`) that `renderTextEditElement`'s drag
start already builds — giving `moveElement`'s `text_edit` branch real
dimensions to clamp against instead of `undefined`. If the run isn't found
(the eager `runs` load hasn't resolved yet — not reachable in practice since
`runs` load before any element could exist, but a real possibility to guard
rather than assume away), that keystroke is a no-op rather than a crash.

### Item 2: rotated-page box shape

**Backend:** a new `get_page_rotation(path: str, page_number: int) -> int`
in `app/core/pdf_ops.py`, mirroring the existing `get_page_count`'s pattern
(open, read one property, close) — kept fully separate from
`extract_text_runs` rather than folding rotation into its return value, so
every existing call site and test of `extract_text_runs` (which expects a
plain list) is untouched. The route (`web/backend/routes/files.py`'s
`get_text_runs`) calls both and returns `{"runs": [...], "rotation": <int>}`.

**Frontend:** a new `pageRotations` state (an object keyed by page number),
populated in the same effect that already loads `runs`
(`web/frontend/src/components/EditPdfCanvas.jsx`'s `loadRuns`, around line
379) — each page's fetch now captures `data.rotation` alongside
`data.runs`, and a failed fetch defaults that page's rotation to `0` (same
fallback its `runs` array already gets).

`textEditBoxRect(run, pending, pageRotations)` gains the `pageRotations`
parameter and this logic:
```javascript
function textEditBoxRect(run, pending, pageRotations) {
  let width = 1 - run.bbox.left - run.bbox.right;
  let height = 1 - run.bbox.top - run.bbox.bottom;
  const moved = pending?.x !== undefined && pending?.y !== undefined;
  const rotation = pageRotations[run.page] ?? 0;
  if (moved && (rotation === 90 || rotation === 270)) {
    [width, height] = [height, width];
  }
  const left = pending?.x ?? run.bbox.left;
  const top = pending?.y ?? run.bbox.top;
  return { left, top, width, height };
}
```
The swap is conditioned on `moved` because that's exactly when the backend
itself switches to the rotate-aware drawing path (`_apply_text_edit`'s
`override_xy is not None` branch) — an un-moved element still draws (and
must still be shown) in the original run's own orientation, unchanged.

All three existing call sites (`renderRunEditorOverlay`,
`renderRunStyleOverlay`, `renderTextEditElement`) pass `pageRotations`
through — each already has `run` and `pending`/`el` in scope, so this is a
one-argument addition at each site, not a restructuring.

Item 1's nudge fix automatically benefits from this too: since it builds its
`positioned` object via the same `textEditBoxRect` call, a nudge on an
already-moved `text_edit` element on a rotated page nudges using the correct
(already-swapped) dimensions with no separate work needed.

## Testing

Backend: a new test for `get_page_rotation` in `tests/test_pdf_ops.py` (a
rotated and a non-rotated fixture, matching this file's existing
rotation-test conventions) and an update to
`tests/web/test_tools_edit_convert.py`'s existing
`test_get_text_runs_returns_runs` confirming the response now includes
`rotation` (that file already has a working non-rotated fixture this test
can extend — no new rotated fixture needed at the route level, since
`get_page_rotation` itself is covered directly by the `pdf_ops` test).

Frontend: no automated tests (established convention) — manual checklist:
arrow-key nudge moves a selected `text_edit` element in the correct
direction on both a rotated and a non-rotated page, and does nothing
destructive if attempted before `runs` has loaded; on a 90°-rotated page, a
freshly-edited (never-moved) `text_edit` box still shows in the original
run's own orientation/position; after dragging it once, the box visibly
transposes to match the replacement text's actual (readable) orientation;
exporting after a move confirms the on-screen box's proportions match the
exported text's real extent (via a PyMuPDF check on the downloaded file, not
just eyeballing the preview).

## Out of scope

- Dynamic box sizing based on the actual measured length of the replacement
  content (considered and explicitly declined in favor of the simpler
  axis-swap approach).
- Closing the narrow first-drag-near-edge overflow edge case described above.
- Any change to when the backend's `override_xy` path activates (still only
  once an element has actually been dragged) — this spec only changes how
  the box is *sized* for display, not the existing position-override
  contract between frontend and backend.

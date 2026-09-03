# Phase 2, Group C2: Edit PDF — Design

**Status:** Approved by user 2026-09-03.

## Context

This is a sub-project of Phase 2 (see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s
roadmap). The roadmap originally scoped this item narrowly as "direct in-PDF text editing
(find/replace a text run in place — pixel-perfect alignment, not a word processor)," split off
from Redact (which shipped first — see
`docs/superpowers/specs/2026-09-02-pdf-editor-phase2-redact-design.md`) because it needs font
detection/matching and text-run-level editing rather than region removal.

During brainstorming, the user expanded the scope: rather than a standalone text-editing tool,
this ships as one unified **"Edit PDF"** tool with a mode switcher — Edit Text, Draw (freehand),
Shapes, Highlight, and Insert Image — all operating on the same page canvas, queued together, and
applied in a single Run. Text editing keeps its original design (redact-and-reinsert with font
matching) as one mode among five; the other four modes are new "add a mark on top of the page"
capabilities that share a common technical pattern (a drawing/annotation overlay) distinct from
text editing's redact-and-reinsert mechanism, but are unified here into one tool per the user's
explicit choice to fold everything into one bigger "Edit PDF" tool now rather than sequencing them
as separate Groups.

## Key technical findings (verified empirically before finalizing this design)

All verified directly against this project's actual PyMuPDF version (1.28.2) via throwaway scripts
before writing this spec, not assumed from documentation:

1. **Text run extraction and coordinate space:** `page.get_text("dict")` returns per-span text,
   font name, size, and a `flags` bitmask (bit 4 = bold, bit 1 = italic — confirmed against a span
   inserted with `fontname="hebo"`, Helvetica-Bold). Each span's `bbox` is in **unrotated mediabox
   space** — the same space `add_redact_annot`/`insert_text` expect — so no derotation multiply is
   needed when using a span's bbox directly for the edit itself. This is the *opposite* of what
   Crop/Redact needed (their boxes start in *displayed* space and must be multiplied by
   `page.derotation_matrix` before use).
2. **Displaying run bboxes on a rotated page's rendered preview requires the inverse mapping:**
   `raw_bbox * page.rotation_matrix` correctly maps a raw span bbox into displayed-page
   coordinates — confirmed on a 90°-rotated page, where the mapped rect fell correctly within the
   displayed `page.rect` bounds. Backend endpoints that expose run positions to the frontend must
   apply this so click targets land in the right place on a rotated page's preview.
3. **Redact-and-reinsert genuinely replaces text in place:** queuing `add_redact_annot()` over a
   span's bbox (white fill) then `apply_redactions()` then `insert_text()` at the original origin
   replaces the text — verified by extracting text before/after and confirming the old string is
   gone, the new string is present, and an unrelated second line of text on the same page is
   untouched.
4. **Width measurement for auto-shrink-to-fit:** `fitz.get_text_length(text, fontname, fontsize)`
   accurately measures a candidate replacement string's width, letting the shrink factor be
   computed as `original_run_width / measured_width * original_size` when the replacement would
   overflow.
5. **Font extraction:** `doc.get_page_fonts(page_number)` lists fonts actually used on a page;
   `doc.extract_font(xref)` returns real font-file bytes for embedded fonts (common in
   Word/LaTeX-exported PDFs) for reuse via `page.insert_font(fontbuffer=...)`. Base-14 fonts
   (Helvetica, Times, Courier and their bold/italic variants) have no extractable file — the
   fallback there is PyMuPDF's built-in base-14 aliases, matched by the span's bold/italic flags.
6. **Ink annotations, shape drawing, and translucent fills all work without error:**
   `page.add_ink_annot([[points...]])` for freehand strokes; `page.new_shape()` with
   `draw_rect`/`draw_oval`/`draw_line` plus `.finish(color=..., width=..., fill=..., fill_opacity=...)`
   for shapes and for highlight (a translucent filled rect, not `add_highlight_annot` — that API
   expects real text quads and would behave oddly over an arbitrary freeform box).

## Scope decisions (from brainstorming)

- **One unified tool, five modes**, not five separate tools — a single mode-switcher toolbar
  (Edit Text | Draw | Shapes ▾ | Highlight | Insert Image) above one shared page canvas.
- **Edit Text:** click-to-select an existing text run (not a hand-drawn box) — the app detects
  run boundaries via `get_text`, true to "find/replace a text run in place."
- **Font matching:** automatic (embedded font reused when present, else closest base-14 alias by
  bold/italic), with a manual override (font family + bold/italic + size).
- **Width mismatch:** auto-shrink font size to fit the original run's width, down to a floor of
  `max(6, original_size * 0.5)` pt, beyond which the text is left to overflow rather than shrink to
  unreadable size.
- **Edit flow:** queue-then-apply, matching this project's universal convention (pick file →
  configure → Run → new output file, original untouched) — not a live-apply editor.
- **Element removal:** click the element (on canvas, in any mode) + a small × button at its
  bounding box — including freehand strokes, whose bounding box is the min/max of their captured
  points. One consistent removal gesture across all five element types; no separate side-panel
  list.
- **Shapes:** Rectangle, Ellipse, Line, Arrow (the standard set most PDF markup tools offer).
- **Styling:** a shared color picker + stroke width (thin/medium/thick) across Draw and Shapes.
  Rectangle/Ellipse additionally get a Fill on/off toggle (off by default); Line/Arrow have no fill
  option since it doesn't apply to them.
- **Highlight:** freeform drag-a-box (same mechanic as Crop/Redact/Shapes), rendered as a 40%-opacity
  color overlay — not text-run-range selection, keeping one consistent drag interaction across
  every mode in this tool.
- **Insert Image:** upload a file, then click to drop it at a default size (25% of page width,
  native aspect ratio) with corner resize handles (aspect-ratio locked) and body-drag to reposition.
  No explicit "commit" step — placing it adds the element immediately, and handle drags update that
  same element in place.
- **Selection, clipboard, undo/redo:** clicking an element's body (not its × corner) selects it —
  shown via a highlight outline — enabling copy/cut; `text_edit` elements aren't selectable this
  way (clicking one keeps reopening it for re-editing, since copying a text edit to another
  position doesn't make sense). Ctrl+C/Ctrl+X/Ctrl+V copy, cut, and paste the selected
  stroke/shape/highlight/image element (paste lands on the currently-viewed page, offset +3%
  x/y). Ctrl+Z/Ctrl+Y undo/redo the whole `elements` array via a snapshot history, one gesture
  (a full drag, not each mousemove) per undo step; Undo/Redo also get toolbar buttons (disabled
  when their stack is empty), but copy/cut/paste stay keyboard-only. All five shortcuts are
  scoped to the canvas being mounted and focus not being inside a text input, so they don't
  hijack native copy/paste in the Edit Text inline box or elsewhere in the app.

## Architecture

### Unified element model

One flat array `elements` for the whole document (page + navigation conventions identical to
Redact — Previous/Next buttons, "Page X of N (K pages have elements)"), each entry tagged by
`type` and carrying a stable `id` (a frontend-generated identifier, not the array index, so
selection/undo/copy stay correct across removals and reorders — never sent to the backend), all
position/size fields as fractions of the page's own displayed dimensions (matching Crop/Redact's
existing convention):

```js
{id, type: "text_edit", page, run_index, text, font_override}  // font_override: {family, bold, italic, size} | null
{id, type: "stroke",    page, points: [{x, y}, ...], color, width}
{id, type: "shape",     page, shape: "rectangle" | "ellipse" | "line" | "arrow", x0, y0, x1, y1, color, width, filled}
{id, type: "highlight", page, top, left, right, bottom, color}
{id, type: "image",     page, file_id, x, y, width, height}
```

`id` is stripped before the array is serialized into the `POST /tools/edit-pdf` request body —
the backend never sees it, since element identity only matters for frontend interaction state.

### Backend

`app/core/pdf_ops.py` gets two new functions:

```python
def extract_text_runs(input_path: str, page_number: int) -> list[dict]
```
Walks `page.get_text("dict")` for the given page in document order (blocks → lines → spans),
skipping whitespace-only spans, returning each as
`{"index": int, "text": str, "font": str, "size": float, "bold": bool, "italic": bool, "bbox": {"top", "left", "right", "bottom"}}`
— `bold`/`italic` from the span's `flags` bitmask, `bbox` computed as
`span["bbox"] * page.rotation_matrix` converted to fractions of the displayed `page.rect` (finding
#2 above). `index` is the run's position in this page's walk order.

```python
def edit_pdf(input_path: str, output_path: str, elements: list[dict], image_paths: dict[str, str]) -> None
```
`image_paths` maps each `image`-element `file_id` to its resolved file path (resolved by the route
before calling in, keeping this function framework-agnostic like every other `core/` function).
Processing, per page with ≥1 element:
1. Validate every element up front, before any page is touched: `page` numbers in range; every
   `text_edit`'s `run_index` valid against a fresh `extract_text_runs` call on that page (reusing
   the *exact same* span-walk function the GET endpoint uses — not a re-implementation, so indices
   are guaranteed to correspond, the same lesson the derotation-matrix bug taught: "conceptually
   the same" must mean "literally the same function"); every box/stroke/shape fraction within
   Crop/Redact's existing bound; every `image` element's `file_id` present in `image_paths`.
2. **Text edits apply first**, settling the page's content stream before anything is layered on
   top: for each `text_edit`, redact the original span's raw bbox (white fill) and
   `apply_redactions()`, then `insert_text()` the replacement at the original baseline origin,
   using the extracted embedded font when available (else closest base-14 alias by bold/italic),
   or the `font_override` when given; auto-shrink per the scope decision above when the
   replacement would overflow the original run's width (measured via `fitz.get_text_length()`).
3. **Then strokes, shapes, highlights, and images layer on top**, in the order the user created
   them: strokes via `add_ink_annot()`; shapes via `page.new_shape()` (`draw_rect`/`draw_oval` for
   Rectangle/Ellipse, `draw_line` for Line, `draw_line` plus a small filled triangle polygon at the
   endpoint — computed from the line's direction vector — for Arrow), filled per the `filled` flag
   on Rectangle/Ellipse only; highlights via a translucent filled rect
   (`.finish(fill=color, fill_opacity=0.4, color=None)`); images via `insert_image()` into the
   element's placed rect (same fit mechanics as `images_to_pdf`).
4. Save.

`web/backend/routes/tools.py` gets two new routes:
- `GET /files/{file_id}/pages/{page_number}/text-runs` — thin wrapper over `extract_text_runs`,
  sibling to the existing thumbnail route.
- `POST /tools/edit-pdf` — resolves `file_id` and every referenced image `file_id` via
  `storage.resolve_file()` into a path dict, converts the validated Pydantic elements list to
  plain dicts, calls `edit_pdf()`, returns via `_output_response()`. Image elements reuse the
  existing `POST /files` upload endpoint — no new upload path.

### Frontend

`EditPdfCanvas.jsx` (new component) owns `currentPage`, `elements`, and `activeMode`, rendered
over the same ~700px `thumbnailUrl` preview Crop/Redact use, `key={primaryFile.id}` from the start
(the exact remount fix Redact needed after shipping without it).

- **Mode switcher:** a toolbar above the canvas — Edit Text | Draw | Shapes ▾ | Highlight | Insert
  Image — changes what a drag/click does; every already-queued element from any mode stays visible
  (with its × button) regardless of the active mode.
- **Edit Text mode:** fetches `GET .../text-runs` on page change; hovering a run outlines it;
  clicking opens an inline edit box (current text, detected font/size/bold/italic as labels, plus
  override controls: family dropdown, bold/italic checkboxes, size field) and submitting
  adds/updates a `text_edit` element. An already-queued run renders with a distinct highlight and
  reopens pre-filled with the *pending* text when clicked again.
- **Draw mode:** mousedown starts capturing points on mousemove (throttled, e.g. one point per
  animation frame), mouseup commits a `stroke` element. A mode-specific toolbar strip offers the
  shared color picker and thin/medium/thick width choice.
- **Shapes mode:** a shape sub-selector (Rectangle/Ellipse/Line/Arrow) plus the shared color/width
  controls, plus a Fill toggle shown only for Rectangle/Ellipse. Rectangle/Ellipse drag
  corner-to-corner (like Crop); Line/Arrow drag endpoint-to-endpoint with a live guide line.
- **Highlight mode:** drag-a-box like Crop/Redact, rendered at 40% opacity in the chosen color
  both while dragging and after commit.
- **Insert Image mode:** click opens a file picker; on selection the image uploads immediately via
  the existing upload flow and appears at a default size/position with four corner resize handles
  (aspect-ratio locked) and body-drag to reposition; the `image` element is added on placement and
  updated in place by further handle drags.
- **Removal:** every rendered element (strokes via their point-array bounding box) shows a small ×
  at its bounding box corner in any mode; clicking it removes that entry from `elements`.
- **Selection, clipboard, undo/redo:** clicking an element's body (any type except `text_edit`)
  toggles it selected, rendered with a distinct outline; clicking empty canvas or pressing Escape
  deselects. A `history` ref holds `{undoStack, redoStack}` (arrays of full `elements` snapshots);
  every mutation (add/remove/edit/paste, and drag-based edits captured once at gesture-start, not
  per mousemove) pushes the pre-mutation snapshot onto `undoStack` and clears `redoStack`. A
  document-level keydown listener (active only while this canvas is mounted, ignored when
  `document.activeElement` is a text input) handles Ctrl+C/X/V against the selected element and
  Ctrl+Z/Y against the history stacks; the toolbar's Undo/Redo buttons call the same handlers and
  are disabled when their stack is empty.
- **Run button:** disabled until `elements.length > 0`, following the same inline
  `config.preview === "edit-pdf" && elements.length === 0` gate pattern already established in
  `ToolView.jsx`'s shared `handleRun`/disabled-clause by Crop and Redact — no other tool's behavior
  changes. The request body serializes `elements` plus the distinct set of image `file_id`s
  referenced within it.

`toolConfigs.js` gets one `edit-pdf` entry: category `"Edit"`, `multiFile: false`,
`preview: "edit-pdf"`, `endpoint: "edit-pdf"`, `fields: []`.

## Error handling

- `edit_pdf`: every element validated (page range, `run_index` against a fresh extraction, box/
  stroke/shape fractions against Crop/Redact's existing bound, image `file_id` presence) before
  any page is modified — a `PDFError` on any invalid element leaves no partially-edited output.
- A corrupt/unreadable input PDF raises `PDFError` via the existing `open_pdf()` path.
- The route reuses `storage.resolve_file()` for both the input file and every referenced image
  `file_id` — an unknown one 404s via the existing app-level handler, identical to every other
  tool.
- Frontend: Run stays disabled until at least one element exists anywhere in the document. Image
  upload failures surface via the existing upload-flow error banner (same `POST /files` call every
  other tool already uses) — no new error UI needed.
- **Known limitation, stated explicitly:** text-edit's erase fill is solid white — correct for the
  common white/light-background case, a visible white patch on colored/textured backgrounds.
  Background-aware fill would help but adds real complexity (anti-aliased edge pixels, patterned
  fills) for a rare case; this ships as a documented ceiling, the same way PDF→Word's layout
  fidelity is a documented limitation rather than an open bug.

## Testing

- `app/core/pdf_ops.py` unit tests (`tests/test_pdf_ops.py`): `extract_text_runs` returns correct
  text/font/bold/italic/bbox for a known sample, including a rotated-page case verifying the
  rotation-matrix mapping; `edit_pdf` with a single `text_edit` replaces the text and leaves
  surrounding content intact (including on a rotated page, per finding #1); one test per remaining
  element type in isolation, each asserting the actual expected result (rendered pixmap color
  sampling or extracted content — not just "ran without error"); a page with one of each element
  type applied together, each landing correctly; auto-shrink-to-fit verified by asserting the
  actual inserted font size for a replacement string known to overflow; out-of-range `page`, bad
  `run_index`, unresolvable image `file_id`, and invalid box/stroke/shape fractions each rejected
  before any page is modified.
- `web/backend/routes/tools.py` route tests (`tests/web/test_tools_edit_convert.py`): success case
  with a mixed-type elements array, unknown `file_id` → 404, unknown image `file_id` referenced by
  an `image` element → 422.
- No new frontend test infrastructure — `EditPdfCanvas`'s per-mode add/remove/re-edit/navigate
  behavior verified via manual browser testing at the end of implementation, per this project's
  established convention, covering: each mode's interaction, cross-mode element visibility and
  removal, page navigation preserving per-page elements, the file-switch reset, and the
  selection/clipboard/undo/redo shortcuts (including that they don't fire while typing in the
  Edit Text inline box or the app's filename field).

## Out of scope (for this spec)

- Text-run range selection for Highlight (freeform box chosen instead, for one consistent drag
  interaction across the whole tool).
- Background-aware erase fill for text editing (documented limitation instead — see Error
  handling).
- Any additional shape types beyond Rectangle/Ellipse/Line/Arrow.
- Copy/cut/paste of `text_edit` elements (doesn't make sense — they're anchored to a specific
  existing run on a specific page, not a freeform position).
- Toolbar buttons for copy/cut/paste (keyboard-only, per explicit user choice — only Undo/Redo get
  buttons).
- Merging adjacent text runs into one editable unit — each click-to-edit targets exactly one
  `get_text` span, matching "text run," not a paragraph or sentence.

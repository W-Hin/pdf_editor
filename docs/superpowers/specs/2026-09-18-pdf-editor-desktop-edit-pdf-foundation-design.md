# Desktop App: Edit PDF, Phase 6A (Foundation + Text/Image) — Design

**Status:** Approved by user 2026-09-18.

## Context

Sub-project 6, the last of the 6 "hard" desktop tools identified while closing
the desktop app's tool gap (sub-projects 1-5 all shipped and released, most
recently v0.12.0 for Compare PDF + the Crop/Redact/Sign continuous-scroll
retrofit). This is by far the largest remaining piece — reading
`web/frontend/src/components/EditPdfCanvas.jsx` (2035 lines) in full
confirms Edit PDF supports 6 element types (`new_text`, `image`, `shape`,
`highlight`, `stroke`, `text_edit`), a coarse undo/redo stack, a clipboard,
keyboard nudge, and z-order reordering — none of which exist anywhere in
this codebase today. `app/core/pdf_ops.py`'s `edit_pdf` and every one of its
six `_apply_*`/`_validate_*` helpers are already fully implemented and
battle-tested (confirmed by reading all of `edit_pdf` and its helpers in
full) — this remains, like every prior sub-project, a pure desktop-UI build
with zero core changes needed.

Given the size, this was split into 3 phases rather than one plan (user's
explicit choice over a single monolithic design):

- **6A (this spec):** shared canvas foundation, proven against the two
  cheapest element types (`new_text`, `image`) — both generalize closely
  from `ImagePlacementWidget`'s already-proven patterns.
- **6B (future):** `shape`/`stroke`/`highlight` — genuinely new `QPainter`
  vector rendering, but reusing 6A's shared selection/hit-test/undo/clipboard
  framework as-is.
- **6C (future):** `text_edit` (in-place editing of existing PDF text) — the
  hardest piece, with zero existing scaffolding to build from (a two-phase
  "retype" vs "restyle" editor, run detection, character-range selection
  without a browser DOM to lean on). Deliberately last.

Two scope decisions from brainstorming: undo/redo, clipboard, keyboard
nudge, and z-order reordering are ALL in scope for 6A (not deferred to a
later phase) — they're framework-level features that apply identically to
every element type present or future, so building them once now avoids
re-touching the canvas architecture in 6B/6C. And `new_text` editing uses a
real, temporary `QTextEdit` overlay while actively being typed into,
committing to plain `QPainter`-drawn text once you click away — so the
canvas only ever has one live input widget at a time, and every element
(including an at-rest `new_text`) shares one uniform paint/hit-test/
selection framework.

## Architecture

### `EditElementsModel` (new, plain Python, no Qt dependency)

Owns the state that must be shared *across* every page — unlike Redact/
Sign's fully independent per-page widgets, Edit PDF genuinely needs one
selection, one undo/redo stack, and one clipboard slot spanning the whole
document, matching the web app's single flat `elements` array exactly
(elements are never bucketed per page internally — each element dict simply
carries its own `page` field).

- `elements: list[dict]` — flat, array-order = z-order (matching the web's
  own implicit-z-order-via-array-position convention exactly).
- `selected_id: str | None`.
- `_undo_stack: list[list[dict]]` / `_redo_stack: list[list[dict]]` — coarse
  whole-array snapshots, not per-field diffs, matching the web's own
  `historyRef` exactly. A whole drag/resize gesture is ONE undo step
  (snapshotted at drag-start, pushed at drag-end), not one per mouse-move.
- `_clipboard: dict | None` — single slot, holding one full element dict
  (minus its id).
- `on_change: list[Callable[[], None]]` — every `EditPageWidget` registers a
  callback here; any mutation notifies all of them so a change made via one
  page's widget (or a keyboard shortcut with no page-specific target) can
  make every affected page's widget repaint.

Methods: `add(element) -> str` (assigns a fresh id, commits), `update(id,
**changes)` (used both for live drag feedback — no commit — and for a
drag-end's own commit, via a separate `commit()` call the dialog invokes
explicitly), `remove(id)`, `select(id_or_None)`, `elements_for_page(page) ->
list[dict]`, `commit()` (push current state to undo, clear redo),
`undo()`/`redo()`, `copy()`/`cut()`/`paste()` (per-type paste-offset math,
identical to the web's `shift()` helper — see Shared Interaction below),
`reorder(id, direction)` (`"front"|"back"|"forward"|"backward"`, same
nearest-same-page-neighbor array-splice logic the web uses), `nudge(id, dx,
dy)`.

### `EditPageWidget` (new, one instance per page)

A thin view, not a state owner: given a reference to the shared
`EditElementsModel`, its own page number, and that page's rendered
`QPixmap`, it paints that page's own filtered elements (`model.
elements_for_page(self.page_number)`) via `QPainter`, dispatching by
`element["type"]`, and translates mouse events into model calls.

**Hit-test order** (topmost-first — reversed list, matching
`ImagePlacementWidget`'s proven convention exactly): for every element on
this page, marker (delete, top-right) → handle(s) (resize, bottom-right for
`new_text`'s single handle; three independent handles for `image` — a
corner for uniform scale, plus width-only and height-only, matching the web
exactly) → body (move). Only if NONE of that hits does the click fall
through to creation — gated by whichever "active creation mode" (`new_text`
or `image`, a two-way toggle in the dialog for this phase) is currently
selected. This mirrors the web precisely: **existing elements of any type
remain selectable/movable/resizable/deletable regardless of which creation
mode is active** — the mode only gates what an empty-space click does.

N instances live inside one `QScrollArea` in `EditPdfDialog`, continuous
scroll, matching every retrofitted dialog's now-established convention.

### `EditPdfDialog` (`app/ui/dialogs/edit_dialogs.py`)

Owns the single `EditElementsModel` instance and builds the N
`EditPageWidget`s on file load. A small mode-toggle row ("New Text" /
"Insert Image", exactly one active) plus toolbar buttons for Undo/Redo/
Copy/Cut/Paste/Bring-to-front/Send-to-back/Forward/Backward/Delete —
buttons rather than inventing new keyboard shortcuts for reorder (this app
has no established shortcut scheme yet for that), but Undo/Redo (Ctrl+Z/Y),
Copy/Cut/Paste (Ctrl+C/X/V), nudge (arrow keys, Shift for the bigger step),
and Delete/Backspace are wired as real keyboard shortcuts at the dialog
level (an event filter installed once, not per-page-widget), so they work
regardless of which page widget currently has focus — matching the web's
own document-level key handling, and necessary since "whichever element is
selected" is a dialog-wide (model-level) concept, not a per-widget one.
Arrow-key nudge/Delete are suppressed while the `QTextEdit` overlay (for
creating/editing a `new_text` box) has focus, exactly matching the web's own
"any text-input-like element has focus" suppression.

`gather_params` snapshots `model.elements` (a plain list of dicts, already
`.model_dump()`-shaped identically to the web's own element shapes) plus the
set of local image file paths referenced by any `image` element's
`file_id`. `run_operation` calls the existing, unchanged `edit_pdf
(input_path, out_path, elements, image_paths)`.

### `new_text` element

`{page, x, y, width, height, text, family, bold, italic, underline, size,
color, align}` — identical to the web's `NewTextElement`. An empty-space
click in "New Text" mode opens a real `QTextEdit` overlay (per the
brainstorming decision above) at a default size (`width=0.25`,
`height=0.08` page-fraction, centered on the click point, clamped on-page),
with a small Qt-native style toolbar (family combo, size spinbox, bold/
italic/underline toggle buttons, color swatches, alignment buttons).
Clicking away commits: an empty/whitespace-only draft is discarded (never
becomes an element, matching the web); otherwise it becomes a plain
`QPainter`-drawn element via `drawText`, honoring every style field.
Double-clicking a committed `new_text` element reopens the same overlay,
pre-filled — one shared creation/edit code path, matching
`openTextDraftForEdit`. One resize handle (free resize, no aspect lock),
floored at a minimum size so the box can't shrink below what the text
needs — computed via Qt's own `QFontMetrics` real text-extent measurement
(more accurate than the web's necessarily-approximate char-width heuristic,
since the web frontend has no way to ask for a PDF's true point dimensions
and has to estimate through a rasterized thumbnail; the desktop app can
measure the real rendered text directly). Commits via the existing,
unchanged `_apply_new_text` (`app/core/pdf_ops.py:816`, real greedy
word-wrap via `_wrap_text_lines` at line 792, alignment, underline, silent
bottom-overflow truncation) — validated first by the existing, unchanged
`_validate_new_text` (line 776).

### `image` element

`{page, file_id, x, y, width, height}` — identical to Sign PDF's
`ImageElement` shape; `file_id` is simply the local signature/image file's
own path, the same convention Sign PDF already established (no upload/
storage server to route through on the desktop app). An empty-space click in
"Insert Image" mode opens a file picker; on selection, default sizing
centers a `width=0.25` box on the click point, with height derived from the
image's own aspect ratio (capped at `0.9`), clamped on-page — the exact
`ImagePlacementWidget` formula, reused verbatim. Gets the web's three
independent resize handles (corner = uniform scale; width-only; height-only,
deliberately allowing aspect distortion) rather than `ImagePlacementWidget`'s
single aspect-locked handle — a new handle *set* for this element type, but
built on the same underlying hit-test/drag-state machinery
(`{"mode": "move"|"resize-corner"|"resize-width"|"resize-height", "index",
"start", "start_element"}`, directly generalizing `ImagePlacementWidget`'s
existing drag-state dict shape). Commits via the existing, unchanged
`_apply_image` (`app/core/pdf_ops.py:743`, `keep_proportion=False`,
deliberately trusting the editor's box exactly) — validated first by the
existing, unchanged `_validate_image_element` (line 587).

## Shared interaction (undo/redo, clipboard, nudge, reorder, delete)

All implemented once on `EditElementsModel`, generalizing the web's exact
mechanics rather than reinventing them:

- **Undo/redo:** coarse whole-array snapshots. `commit()` pushes the
  *previous* state before a mutation takes effect and clears the redo
  stack — called once per discrete action (an add, a delete, a completed
  drag/resize gesture, a paste), never per intermediate mouse-move during a
  drag (live drag feedback calls `update()` without committing; the commit
  happens once at drag-end using the drag-start snapshot).
- **Clipboard:** single-slot copy of the currently-selected element (minus
  its id); cut additionally removes the source and clears selection; paste
  applies the same `0.03` page-fraction diagonal offset the web uses,
  computed per element-type's own coordinate convention (`x/y/width/height`
  for both `new_text` and `image` in this phase) and clamped per-axis to
  whatever room remains before the page edge — the same `shift()` logic the
  web uses, generalized to whichever element-type shapes exist at the time
  (6B/6C add their own type branches to this same function later, nothing
  in 6A's version needs revisiting when they do, since each type's shift
  logic is independent).
- **Keyboard nudge:** arrow keys nudge the selected element by `0.004`
  page-fraction, or `0.02` with Shift held — identical to the web's
  `NUDGE_SMALL_STEP`/`NUDGE_BIG_STEP`. Delete/Backspace removes the selected
  element. Both suppressed while the `new_text` creation/edit overlay has
  focus.
- **Z-order reorder:** "bring to front" / "send to back" / "forward" /
  "backward", exposed as toolbar buttons. "Forward"/"backward" specifically
  hunt for the nearest *same-page* neighbor in the flat array (skipping over
  other pages' elements that happen to sit between them), matching the
  web's `reorderSelected` exactly — otherwise "forward" on a page with only
  2 elements could silently do nothing if another page's element happened
  to sit between them in the array.

## Testing

Following the established convention (real `PySide6.QtTest`-driven pytest
tests, appended to `tests/test_ui_desktop.py`): `EditElementsModel` gets
direct tests with no Qt dependency at all (undo/redo stack behavior across
several mutations, clipboard offset math for both element types including
the near-edge clamping case, nudge, and reorder including the "skip
other-page neighbors" case). `EditPageWidget` gets synthetic-mouse-event
tests covering: creating a `new_text` box and typing into its `QTextEdit`
overlay, creating an image placement, moving/resizing/deleting each type,
and the cross-type hit-test priority (an existing element remains
selectable regardless of which creation mode is currently active — the
exact web behavior this phase must preserve). `EditPdfDialog` gets a full
end-to-end test: build a real multi-page fixture, place a `new_text` and an
`image` element (on different pages), undo one, redo it back, copy/paste
the other, export, and verify via `fitz` that the resulting real output PDF
has the expected text and image content in the expected positions.

## Out of scope

- `shape`, `stroke`, `highlight` element types (Phase 6B) and `text_edit`
  in-place editing (Phase 6C) — each gets its own future brainstorm.
- Any change to `app/core/pdf_ops.py`'s `edit_pdf` or any of its six
  `_apply_*`/`_validate_*` helpers, or to the web app's own
  `EditPdfCanvas.jsx`/`edit-pdf` route — all already exist, already tested,
  and need no changes.
- Multi-select (selecting/moving several elements at once) — the web app
  itself doesn't support this (`selectedId` is a single id, not a set), so
  there is no parity gap to close here.

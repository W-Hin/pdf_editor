# Desktop App: Edit PDF, Phase 6C (In-Place Text-Run Editing) — Design

**Status:** Approved by user 2026-09-18.

## Context

Phase 6C of Edit PDF, the final phase of sub-project 6 (the last of the 6
"hard" desktop tools). Builds on Phase 6A's `EditElementsModel`/
`EditPageWidget` canvas foundation and Phase 6B's vector-element dispatch —
this phase adds the `text_edit` element type, letting the user click into
an *existing* piece of text on the page and edit it in place, rather than
only ever placing brand-new content on top. Deliberately last: reading
`web/frontend/src/components/EditPdfCanvas.jsx`'s two-phase run-editor
mechanic in full confirmed it's the one piece with zero existing
scaffolding anywhere in this codebase to build from.

**A genuine simplification over the web's design, confirmed during
brainstorming and the user's explicit choice:** the web's forced two-phase
split — phase "type" (single-style retype from scratch) vs. phase "style"
(character-range restyling via a hand-rolled DOM-selection-to-segment-array
mapping, with an explicit, lossy "flatten and retype" escape hatch back to
phase "type") — exists *only* because a browser has no native rich-text
editing primitive to reach for over an absolutely-positioned overlay. Qt's
`QTextEdit` has exactly that primitive: `QTextCursor`/`QTextCharFormat`
apply per-character-range formatting natively, and a `QTextDocument`'s own
internal fragment model (contiguous runs of identical formatting) already
**is** the `segments` representation the backend expects — walking it at
commit time produces the segments list directly, no custom split/merge
logic needed. This phase therefore uses **one unified rich-text editor**
instead of porting the web's phase state machine: type to edit text,
select a range and click a toolbar button to restyle just that range, with
no mode-switching and no lossy flatten-then-retype step, since you can
always keep typing and styling within the same widget. Same `segments`
data shape at commit time, same PDF output via the same unchanged core
function — only the *interaction model* is simpler.

## Architecture

### Run detection and the "Edit Text" mode

On file load, `EditPdfDialog` calls the existing, unchanged
`extract_text_runs(input_path, page_number)` (`app/core/pdf_ops.py:484`,
already rotation-aware via `page.rotation_matrix`, already extracting
bold/italic from font flag bits) once per page, caching each page's
detected run list. The toolbar's active-creation-mode selector (a 2-way
choice in 6A, 5-way after 6B) gains a 6th option, "Edit Text" — while
active, double-clicking inside a detected run's bbox on any
`EditPageWidget` opens the editor for that run; every other mode's
empty-space creation gesture is unaffected, and — matching the web
precisely — an *existing* element of any type (from any phase) remains
selectable/movable/resizable/deletable no matter which mode is currently
active. "Edit Text" only gates the double-click-on-a-run gesture itself.

### The unified rich-text editor

A `QTextEdit` overlay positioned over the run's own displayed bbox (using
the same rotation-aware, displayed-space coordinates `extract_text_runs`
already reports). Opening it:
- If no `text_edit` element exists yet for this run: seeds the editor with
  the run's own detected text, in the run's own detected style — family
  snapped to the closest of the three base-14 families
  (`closestBase14Family`, ported directly from the web's own identical
  logic, matching `app/core/pdf_ops.py`'s `_closest_base14_family` the web
  itself already mirrors), size/bold/italic from the run's own detected
  values.
- If a `text_edit` already exists for this run: seeds the editor by
  rebuilding its rich-text content directly from that element's own
  `segments` list (one `QTextCursor.insertText(seg["text"], format)` per
  segment, walking them in order) — so reopening an already-edited run
  shows exactly what was there before, styling included.

A small toolbar (family combo, size spinbox, bold/italic toggle buttons)
applies to the current text selection via `QTextCursor.mergeCharFormat`
when something is selected, or sets the cursor's own current-format state
(affecting whatever gets typed next) when nothing is. "Revert" discards
any pending `text_edit` for this run and reopens fresh from the run's own
original detected text/style.

### Committing

On the `QTextEdit` losing focus: walk the underlying `QTextDocument`
block-by-block, fragment-by-fragment (`QTextBlock.begin()`'s
`QTextFragment` iterator — each fragment is already a maximal run of
uniform character formatting) into `{text, family, bold, italic, size}`
segment dicts, in order. If the resulting segments are identical — as a
whole — to a single segment holding the run's own original text and
default style, **and** no `text_edit` already existed for this run before
this edit session, this is a no-op: no element is added, matching the
web's own "opening and closing without touching it must not pollute undo
history" behavior. Otherwise: `EditElementsModel.add()` (fresh edit) or
`.update()` (already-pending edit, replacing its segments) is called with
`{type: "text_edit", page, run_index, segments}` — `run_index` references
the run's own stable index from `extract_text_runs`/`_page_text_spans`
(the same shared span-order source of truth the backend's own validation
and application both already use, guaranteeing index stability between
what the desktop app saw and what `edit_pdf` applies). An intentionally
emptied run (all text deleted, `QTextEdit` left blank) still commits as a
real erase — matching the web, which only special-cases "identical to
original," never "empty."

### Moving a `text_edit` element

`text_edit` elements never persist `width`/`height` — their box is always
derived live from the original run's own detected bbox. A move (drag or
keyboard nudge) reconstructs a synthetic `{x, y, width, height}` from the
run's own current bbox just for the duration of the gesture, and strips
`width`/`height` back out before the final `update()`/`commit()` — so a
moved `text_edit` element in `model.elements` still only ever carries
`{id, type, page, run_index, segments, x, y}`, matching the web's own
`moveElement`-time reconstruction trick exactly.

### Clipboard exclusion

`text_edit` elements are excluded from copy/cut entirely (attempting to
copy the currently-selected element when it's a `text_edit` is simply a
no-op) — a `run_index` is only ever meaningful tied to its own original
run on its own original page, so "pasting" one anywhere would be
nonsensical. Matches the web's own `copySelected` behavior (returns `null`
for this type).

## Testing

Following the same convention: a direct test confirming the
fragment-walking commit logic produces the exact expected `segments` shape
for a `QTextEdit` with mixed formatting applied via `QTextCursor`
(building the rich text programmatically in the test, mirroring how every
other synthetic-interaction test in this suite drives real Qt objects
rather than mocking); a test confirming the "unchanged from original,
no prior edit" no-op case genuinely adds nothing to `model.elements`;
a test confirming re-opening an already-edited run's editor correctly
rebuilds its rich content from the stored segments; a test confirming
`text_edit` is excluded from copy/cut; an end-to-end `EditPdfDialog` test
building a real fixture PDF with real detected text, editing a run with
mixed bold/italic styling via synthetic `QTextCursor` operations,
exporting, and confirming via `fitz` (re-extracting the output page's text
and comparing rendered styling where checkable, e.g. bold via font-flag
inspection) that the edit genuinely landed as intended — matching the
core-level rigor `tests/test_pdf_ops.py`'s own existing `_apply_text_edit`
tests already establish.

## Out of scope

- Any change to `app/core/pdf_ops.py`'s `extract_text_runs`,
  `_page_text_spans`, or `_apply_text_edit` (`app/core/pdf_ops.py:598`), or
  to the web app's own `EditPdfCanvas.jsx`/`edit-pdf` route — all already
  exist, already tested, and need no changes. The desktop app's simpler
  unified-editor interaction model produces the identical `segments` data
  shape the backend already expects, so no backend/core work is implied by
  this phase's UX simplification.
- Mirroring the web's exact two-phase state machine, its
  `splitAndRestyleSegments`/`mergeAdjacentSegments` split/merge logic, or
  its lossy "flatten and retype" escape hatch — explicitly superseded by
  Qt's native rich-text model per the brainstorming decision above.

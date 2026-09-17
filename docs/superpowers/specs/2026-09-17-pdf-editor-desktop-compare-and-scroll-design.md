# Desktop App: Compare PDF + Continuous-Scroll Retrofit — Design

**Status:** Approved by user 2026-09-17.

## Context

Sub-project 5 of the 6 "hard" desktop tools identified while closing the
desktop app's tool gap (sub-projects 1-4 shipped: the 10 easy dialogs,
Crop+Redact, Sign PDF, PDF Forms — most recently released as v0.11.0).

This sub-project turned out to combine two pieces of work, both decided
during brainstorming:

1. **Compare PDF** (new) — reading `web/frontend/src/components/
   ComparePdfView.jsx`, `web/backend/routes/compare.py`, and
   `app/core/compare_pdf.py` in full confirms Compare is a genuinely
   different shape from every dialog built so far: it takes **two** input
   files, produces **no output PDF** (a pure read-only comparison, not an
   edit), and shows two kinds of diff per page — a cheap line-level text
   diff (`diff_page_text`, `difflib.SequenceMatcher` under the hood) and
   an expensive visual diff (`diff_page_visual`: two full-resolution page
   renders, a per-pixel tolerance comparison, and coarse-grid box
   clustering). All of this logic already exists in `app/core/
   compare_pdf.py`, unchanged and already used by the web app — this is a
   pure desktop-UI-consumption project, same as PDF Forms was for
   `extract_form_fields`/`fill_form`.
2. **Continuous-scroll retrofit** (changed) — while designing Compare's
   own page navigation, the user asked to also retrofit `CropDialog`,
   `RedactDialog`, and `SignDialog` (all shipped, released in v0.9.0/
   v0.10.0) from their current one-page-at-a-time spinner to continuous
   scroll of all pages, matching the convention `FillFormDialog` (v0.11.0)
   already established. Explicitly bundled into this same plan per the
   user's own choice, rather than split into a separate sub-project.
   `CompareDialog` itself is the one dialog that does **not** get
   continuous scroll — its visual diff is expensive enough per page that
   the existing page-spinner-plus-lazy-load pattern stays the right fit
   (see below).

## Architecture

### `CompareDialog` (`app/ui/dialogs/edit_dialogs.py`)

Reuses `ToolDialog`'s existing `allow_multiple_files = True` file list
(the same mechanism `MergeDialog` already uses for its own multi-file
input) rather than building dedicated two-file pickers — no changes to
shared dialog infrastructure. The first file added is treated as the
"original," the second as the "changed" version; a third+ file is a user
error caught explicitly (see below), since — unlike prior dialogs — there
is no core-level function that already enforces "exactly 2" for Compare
to lean on.

- `build_preview`: a page `QSpinBox` (mirroring `RedactDialog`'s existing
  wiring) above a text-diff panel (a read-only `QTextEdit`, HTML-formatted
  with colored spans: green background for inserted lines, red/strikethrough
  for deleted, default for unchanged — mirrors `ComparePdfView.jsx`'s
  `compare-pdf__diff-line--{op}` CSS classes) and, below that, two
  side-by-side `DiffPreviewWidget` instances (one per document) showing
  that page's rendered image with the computed diff boxes overlaid.
  A page whose counterpart doesn't exist (one document has fewer pages)
  shows a "Page added"/"Page removed" message instead of any diff.
- `on_files_changed`: requires the two files (see `run_operation`'s
  validation below for exactly where "not 2 files" is caught — this
  method degrades gracefully on 0/1/3+ files by just clearing state, same
  "let the user fix it before Run" pattern every other dialog uses).
  With exactly 2, calls `extract_page_texts` on both, computes
  `diff_page_text` for **every** page up front (cheap: pure Python string
  diffing, no rendering) and stores per-page `{"text_diff": [...],
  "has_counterpart": bool}` — mirrors `compare_route`'s own eager
  computation in `web/backend/routes/compare.py`. Sets the spinner's
  maximum to `max(page_count_a, page_count_b)`.
- `_load_current_page` (spinner `valueChanged` handler): renders the
  current page's text diff into the `QTextEdit` immediately (already
  computed). For the visual diff — the expensive part — calls
  `render_page_image` on both documents and `diff_page_visual` **only for
  this page**, lazily, matching `ComparePdfView.jsx`'s own lazy
  `fetchCompareVisual` (there, lazy-on-scroll-into-view via
  `IntersectionObserver`; here, lazy-on-spinner-change, since Qt has no
  scroll-visibility signal as convenient and the spinner already gates
  "which page is currently being looked at" exactly as needed). Skipped
  entirely for a page with no counterpart.
- `gather_params`/`run_operation`: `gather_params` returns
  `{"file_count": len(self.selected_files())}` (nothing else — there are
  no options to snapshot, and the diff state itself lives in already-computed
  per-page data, not something `run_operation` re-derives). `run_operation`
  raises `PDFError("Select exactly 2 files to compare.")` if
  `params["file_count"] != 2`, otherwise returns `([], f"Compared {page
  count} page(s).")` — an empty output-paths list, since Compare produces
  no file. `ToolDialog`'s "Show in folder" button stays visible (there is
  no hook to hide it from a subclass given `__init__`'s current widget
  creation order) but harmlessly no-ops when clicked, since
  `_open_output_folder` already guards on `self._output_paths` being
  non-empty.

### `DiffPreviewWidget` (new, in `app/ui/widgets.py`)

A small, single-purpose, **read-only** widget: paints a page `QPixmap`
plus a list of highlight boxes (fraction-space, same `{x0,y0,x1,y1}` shape
`RectangleOverlayWidget` already uses) in a translucent red rectangle —
visually similar to `RectangleOverlayWidget`'s own box painting, but with
**no mouse event handling at all**. This is deliberately not a reuse of
`RectangleOverlayWidget`: those boxes are the user's own draggable/
removable annotations; `DiffPreviewWidget`'s boxes are Compare's computed
output, never user-editable, so giving it click/drag semantics would be
actively wrong (a click could accidentally "remove" a diff finding that
isn't actually an annotation to remove). `set_pixmap(pixmap)`,
`set_boxes(boxes: list[dict])`.

### `RectangleOverlayWidget` additions (in `app/ui/widgets.py`, for `CropDialog` only)

Two small additions, used only by the Crop retrofit (Redact doesn't need
either):
- `interactive: bool = True` constructor parameter. When `False`,
  `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent` all become no-ops
  — the widget only ever displays a pixmap + externally-set boxes via
  `set_pixmap`/`set_boxes`, exactly like `DiffPreviewWidget` but reusing
  the existing box-painting code rather than duplicating it.
- `box_changed` (a `Signal()`, no payload) emitted at the end of
  `mouseReleaseEvent` whenever a drag actually produces a new box (i.e.
  the existing min-drag-fraction check passes) — the first Qt signal any
  widget in this file has needed, since every previous widget's mutated
  state was read by polling (`.boxes`/`.placements`) at `gather_params`
  time rather than reacted to live. Live reaction is required here
  because one page's drag must immediately update every *other* page's
  read-only mirror.

### `CropDialog` retrofit

Page 1's box selector stays exactly as it is today (one interactive
`RectangleOverlayWidget(multi=False)`, unchanged instruction text) — Crop
fundamentally applies **one shared rectangle to every page**, so there is
no per-page data to scroll through the way Redact/Sign have. What
changes: below the interactive widget, a `QScrollArea` now stacks a
read-only `RectangleOverlayWidget(multi=False, interactive=False)` for
every *other* page (2..N), each showing that page's own rendered content
with the **same shared box** mirrored on top — letting the user visually
confirm the one shared crop region actually looks right against every
page's real content, not just page 1's. `CropDialog` connects the
interactive widget's `box_changed` signal once, to a handler that calls
`.set_boxes([box])` on every mirror widget. `gather_params`/
`run_operation` are unchanged (`self.overlay.single_box()` still reads
from the one interactive widget — the mirrors are display-only,
contributing nothing to the operation itself).

### `RedactDialog` / `SignDialog` retrofit

Both currently hold ONE `RectangleOverlayWidget`/`ImagePlacementWidget`
plus a page `QSpinBox`, with `_flush_current_page`/`_load_current_page`
shuttling that page's boxes/placements into a shared
`self._all_redactions`/`self._all_placements` list every time the spinner
changes (the exact pattern `FillFormDialog`'s own retrofit — from single
overlay to continuous scroll — already proved out one sub-project ago).
Retrofit: replace the spinner + single widget with a `QScrollArea`
stacking **one independent widget instance per page** (a `list[dict]`-per-page structure, same idea as
`FormFieldsWidget._field_widgets` keyed by `(page, index)` but here keyed
simply by page number since there's one overlay widget per page, not one
per field) — each permanently holding that page's own boxes/placements
for the dialog's whole lifetime, no flushing. `on_files_changed` builds N
widget instances up front (one `render_page_thumbnail` call per page,
matching `FillFormDialog`'s own eager-render-every-page approach — the
same accepted trade-off, not a new one). `gather_params` walks the list of
per-page widgets and reads `.boxes`/`.placements` directly from each,
tagging the result with that widget's own page number — replacing
`_flush_current_page` entirely, which is deleted along with
`_current_page`/`_load_current_page`. `SignDialog`'s two-phase structure
(source phase, then placement phase) is otherwise unchanged — only the
placement phase's page navigation changes shape; `use_signature_file`
still triggers building the N placement widgets once a signature is
chosen, the same moment `_load_current_page` used to fire.

## Testing

Following the established convention (real `PySide6.QtTest`-driven pytest
tests appended to `tests/test_ui_desktop.py`, not a manual checklist):

- **`CompareDialog`**: two real fixture PDFs with deliberately differing
  text on at least one shared page and at least one page only one
  document has, confirming `diff_page_text`'s ops render into the
  `QTextEdit` correctly, confirming the visual diff is genuinely NOT
  computed until the spinner reaches that page (a call-count assertion on
  a lightweight monkeypatch, or simpler: confirming `DiffPreviewWidget`
  instances only get their pixmaps/boxes set after `_load_current_page`
  runs for that page — not before), and confirming `run_operation` raises
  `PDFError("Select exactly 2 files to compare.")` for 1 or 3 files.
- **`DiffPreviewWidget`**: a direct test confirming `mousePressEvent`
  (etc.) genuinely does nothing — no `boxes`/interaction state exists on
  this widget at all, unlike confirming a flag's effect on an existing
  widget.
- **`RectangleOverlayWidget(interactive=False)`**: a direct test
  confirming a synthetic drag does NOT create a box when `interactive=False`,
  and confirming `box_changed` fires (captured via a connected Python
  callable) exactly once per successful drag when `interactive=True`
  (the default, unchanged for every existing caller).
- **`CropDialog`**: a test building a multi-page fixture, dragging a box
  on the interactive (page 1) widget, and confirming every mirror widget's
  displayed box now matches — replacing nothing (Crop had no page-switch
  test before, since it never had per-page state).
- **`RedactDialog`/`SignDialog`**: the existing page-switch/flush tests
  (`test_redact_dialog_page_switch_accumulates_and_restores_boxes`,
  `test_sign_dialog_page_switch_accumulates_and_restores_placements`) are
  **replaced** with simpler tests confirming N independent per-page
  widgets each hold their own boxes/placements without any switching step,
  and that `gather_params` correctly collects all of them tagged by page.

## Out of scope

- Any change to `app/core/compare_pdf.py`, `app/core/pdf_ops.py`, or the
  web app's own `ComparePdfView.jsx`/`compare` routes — all already exist,
  already tested, and need no changes.
- Changing Crop's fundamental "one rectangle applies to every page" model
  — only its *display* becomes multi-page; the operation itself is
  unchanged.
- Any attempt to make Compare's visual diff eager/continuous-scroll — the
  page-spinner-plus-lazy-load shape is deliberate given the per-page cost,
  not a stopgap.
- The remaining hard tool (Edit PDF, sub-project 6, the full canvas port)
  — still needs its own future brainstorm, deliberately last since it's
  the biggest.

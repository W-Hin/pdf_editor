# Desktop App: Sign PDF — Design

**Status:** Approved by user 2026-09-17.

## Context

Sub-project 3 of the 6 "hard" desktop tools identified while closing the
desktop app's tool gap (sub-project 1, the 10 easy dialogs, shipped as
v0.9.0; sub-project 2, Crop+Redact, shipped this session with a shared
`RectangleOverlayWidget` in `app/ui/widgets.py` and a `build_preview`
override hook added to `ToolDialog` in `app/ui/dialogs/base.py`).

Before designing anything, the actual scope question was resolved by
reading the current code, not assumed: `web/frontend/src/toolConfigs.js`'s
`sign` entry does point at the shared `edit-pdf` backend endpoint, but
`web/frontend/src/components/SignCanvas.jsx` is a **wholly self-contained**
component, structurally unrelated to `EditPdfCanvas.jsx`. It only ever
produces `image`-type elements (`web/backend/routes/tools.py`'s
`ImageElement`: `{type: "image", page, file_id, x, y, width, height}`) — a
signature is either hand-drawn on a small canvas pad or uploaded as a file,
then placed, resized, and removed like any other image, with the SAME
`edit_pdf(input_path, output_path, elements, image_paths)` core function
(`app/core/pdf_ops.py`) other Edit-category tools already use. It submits
through `edit-pdf` purely because that's the shared entry point for
element-based edits — the interaction itself doesn't touch anything else
Edit PDF does (no shapes, highlights, strokes, or in-place text editing).
**This means Sign PDF is genuinely separable and independently buildable —
not a slice of the full Edit PDF canvas port**, which was the open question
going in.

For the desktop app this is even simpler than the web version: there's no
upload/storage server to route through, so the signature PNG's own local
file path can serve directly as both the key and value in `image_paths`,
and as every placement element's `file_id` — no new plumbing needed for
that at all.

## Scope decisions (from brainstorming)

- **Multiple placements across any number of pages** — matching the web
  app exactly, reusing the same page-spinner + accumulated-list pattern
  `RedactDialog` already established (storing `{page, x, y, width,
  height}` dicts instead of inset dicts). Any number of placements are
  allowed on the same page too (the web app doesn't restrict this, and
  neither does this design).
- **A real freehand-drawing widget**, not upload-only — paints directly
  onto a `QImage` buffer as the mouse drags, matching the web pad's actual
  feel rather than being a placeholder.

## Architecture

### `SignaturePadWidget` (new, in `app/ui/widgets.py`)

A fixed-size (400×150, matching `SignCanvas.jsx`'s `PAD_WIDTH`/`PAD_HEIGHT`)
`QWidget` that paints black 2px strokes onto an internal white `QImage`
buffer:
- `mousePressEvent`: begins a new stroke (records the point, marks
  `has_drawing = True`).
- `mouseMoveEvent`: if a stroke is active, draws a line segment from the
  last recorded point to the current one directly onto the `QImage` via a
  `QPainter`, then calls `self.update()` to repaint.
- `mouseReleaseEvent`: ends the active stroke (no line drawn on release
  itself — the last segment was already drawn on the preceding move).
- `paintEvent`: blits the internal `QImage` onto the widget.
- `clear()`: repaints the buffer white and resets `has_drawing` to `False`.
- `has_drawing() -> bool`.
- `save_png(path: str) -> None`: saves the current buffer via
  `QImage.save(path, "PNG")`.

### `ImagePlacementWidget` (new, in `app/ui/widgets.py`)

Displays a page-preview `QPixmap` with the signature image placed at zero
or more independent positions — the most interaction-heavy widget either
desktop sub-project has needed so far, since (unlike `RectangleOverlayWidget`,
which only ever does one thing — drag to draw a rectangle) this one needs
four distinct interactions on the same click, tested in this priority order:

1. **Marker hit** (a small removable × on each existing placement, same
   `_marker_rect`-style approach `RectangleOverlayWidget` already
   established) — removes that placement.
2. **Resize-handle hit** (a small square at each placement's bottom-right
   corner) — starts an aspect-locked resize drag, using the exact same
   clamping formula `SignCanvas.jsx`'s `handleDragMove` already uses:
   ```
   aspect = height / width
   widthCap = min(1 - x, (1 - y) / aspect)
   width = min(max(0.05, width + dx), widthCap)
   height = width * aspect
   ```
3. **Body hit** (click lands inside an existing placement's rect, but
   outside its marker/handle) — starts a move drag (simple x/y translation,
   clamped to stay on the page, same as every other draggable element type
   in this app).
4. **Empty space** (none of the above) — creates a brand-new placement
   centered on the click point, using `SignCanvas.jsx`'s exact default
   sizing:
   ```
   width = 0.25
   height = min(0.9, width * (signature_natural_height / signature_natural_width))
   x = clamp(click_x - width / 2, 0, 1 - width)
   y = clamp(click_y - height / 2, 0, 1 - height)
   ```

`set_page_pixmap(pixmap)`, `set_signature_pixmap(pixmap)` (also used to read
the signature's natural width/height for new-placement sizing),
`set_placements(list[dict])` / `.placements` (each `{"x","y","width","height"}`,
no page tag — page tagging happens at the dialog level, mirroring
`RedactDialog`'s existing split between the widget's per-page view and the
dialog's cross-page accumulation).

### `SignDialog` (`app/ui/dialogs/edit_dialogs.py`)

Two phases, matching `SignCanvas.jsx`'s own `!signatureFileId` / has-a-signature
split:

**Source phase** (`build_preview`'s initial state): a "Draw new" button
toggling a `SignaturePadWidget` panel (with Clear/Save buttons — Save
requires `has_drawing()`, matching the web's "Draw a signature first."
guard) and an "Upload new" button (`QFileDialog.getOpenFileName` with an
image filter, matching `ImagesToPdfDialog`'s existing file-filter
convention). Either path ends with a concrete local PNG file path — for
"Draw new," `save_png` to a fresh temp file (`tempfile.NamedTemporaryFile`);
for "Upload new," the picked file's own path, used as-is (PyMuPDF already
opens JPG/PNG directly, confirmed by `images_to_pdf`'s existing use of the
same mechanism — no format conversion needed). The signature's natural
width/height (for new-placement aspect ratio) is read via `QPixmap(path).size()`.

**Placement phase** (once a signature path exists): a page-number
`QSpinBox` (identical wiring to `RedactDialog`'s) above one
`ImagePlacementWidget(multi=True)`-equivalent (this widget is always
multi — there's no single-placement mode to speak of, unlike
`RectangleOverlayWidget`), and a "Use a different signature" button that
clears the signature path and every accumulated placement, returning to
the source phase (matching `SignCanvas.jsx`'s `useDifferentSignature`).
Switching pages flushes the current page's placements into an accumulated
`self._all_placements: list[dict]` (page-tagged) before loading whichever
placements already exist for the newly-selected page — the identical
`_flush_current_page`/`_load_current_page` shape `RedactDialog` already
has, just carrying `{x,y,width,height}` instead of inset fields.

`gather_params` flushes the current page and returns
`{"signature_path": ..., "placements": [...]}`. `run_operation` builds one
`ImageElement`-shaped dict per placement (`{"type": "image", "page": p["page"],
"file_id": signature_path, "x": p["x"], "y": p["y"], "width": p["width"],
"height": p["height"]}`), an `image_paths = {signature_path: signature_path}`
dict, and calls `edit_pdf(input_path, out_path, elements, image_paths)`.
Output: `<stem>_signed.pdf` (no web route for Sign specifically exists to
mirror a suffix from, since it shares `edit-pdf`'s own generic
`_edited` — but `_signed` is clearer for this specific tool and doesn't
need to match anything, since the desktop app names its own outputs
independently of the web app's per-tool suffixes for the handful of tools
where the two truly diverge in shape, same as e.g. Images to PDF's
user-chosen filename already does).

`redact_pdf`'s core-level "at least one" validation has no equivalent for
Sign — placing zero signatures and clicking Run should raise a dialog-level
`PDFError("Place at least one signature before running.")`, mirroring
`CropDialog`'s own equivalent check for its "nothing drawn yet" case.

## Testing

Following the precedent set by the Crop/Redact plan (which added this
project's first real automated `app/ui/` tests, appending to the same
`tests/test_ui_desktop.py`): both new widgets and `SignDialog` get real
`PySide6.QtTest`-driven pytest tests, not a manual checklist — drawing a
stroke on `SignaturePadWidget` and confirming `has_drawing()` and a
non-blank saved PNG; creating, moving, resizing, and removing placements on
`ImagePlacementWidget` via synthetic mouse events, with exact expected
fractions to be empirically verified (not guessed) during the
writing-plans phase, the same way Crop/Redact's exact pixel/fraction
numbers were verified before being written into that plan; the full
`SignDialog` page-switch/accumulate flow end-to-end into a real exported
PDF, confirming the signature image genuinely appears at the expected
page(s)/position(s) via PyMuPDF's own image-extraction on the output file.

## Out of scope

- Any change to `edit_pdf`, `ImageElement`, or the web app's own
  `SignCanvas.jsx`/`edit-pdf` route — all already exist, already tested,
  and need no changes; this is a pure desktop-UI addition consuming them
  exactly as the web app does.
- Persisting a "saved signature" across dialog sessions the way the web
  app's `localStorage`-backed "Use saved signature" button does — the
  desktop app has no equivalent persistent-storage convention for this yet,
  and adding one is a separable concern from getting Sign PDF working at
  all. A user who wants to reuse a signature across runs can just pick the
  same uploaded file again, or keep the temp PNG from a drawn one — not as
  smooth as the web app's one-click reuse, but a reasonable v1 gap.
- The remaining 3 hard tools (PDF Forms, Compare, Edit PDF) — each still
  needs its own future brainstorm; Edit PDF in particular remains a
  substantial project on its own.

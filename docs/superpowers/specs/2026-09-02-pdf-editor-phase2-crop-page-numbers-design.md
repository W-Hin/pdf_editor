# Phase 2, Group A: Crop + Add Page Numbers — Design

**Status:** Approved by user 2026-09-02.

## Context

This is the first sub-project of Phase 2 (see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s
roadmap). Phase 2 as originally scoped bundles seven independent features (Crop, Add page
numbers, direct in-PDF text editing, Redact, PDF Forms, Sign, JPG→PDF, Scan to PDF); per the
brainstorming process, it's been decomposed into four sub-projects grouped by shared UI/technical
needs:

- **Group A (this spec):** Crop, Add page numbers — no new UI paradigm beyond a drag-to-select
  rectangle.
- **Group B (future):** JPG→PDF, Scan to PDF — mirrors the existing Merge/PDF-to-Image pattern.
- **Group C (future):** Direct in-PDF text editing, Redact — needs click-to-select-a-region UI,
  built on the same PDF-space-coordinate technique introduced here for Crop.
- **Group D (future):** PDF Forms, Sign — needs overlay-elements-on-a-page UI.

Each group gets its own spec → plan → implementation cycle. This spec covers Group A only.

## Goal

Add two new tools to the web app, following the existing "Organize / Edit / Optimize / Convert"
tool-grid pattern: **Crop** (trim a uniform margin off every page) and **Add page numbers**
(stamp a page number onto every page in a chosen corner and format).

## Scope decisions (from brainstorming)

- **Crop input:** the user drags a rectangle directly on a rendered page preview — not numeric
  margin fields. This is a deliberate choice to build the click/drag-on-a-page-image UI
  capability now, since Group C (direct text editing, redact) will need the same underlying
  technique (screen-space rectangle → normalized page-space rectangle) later.
- **Crop scope:** one rectangle, drawn once against page 1's preview, applied identically (as a
  0–1 fraction of each page's own width/height) to every page in the document. Not a per-page
  crop editor.
- **Crop interaction:** click-and-drag draws a new rectangle; dragging again replaces the
  previous one. No resize handles — redraw-to-adjust is the whole interaction model for v1.
- **Page number position:** a fixed dropdown of six common positions (bottom-center,
  bottom-right, bottom-left, top-center, top-right, top-left) — not click-to-place.
- **Page number format:** a dropdown of a few presets ("3", "3 / 12", "Page 3 of 12") — not a
  free-text template.

## Architecture

### Crop — backend technique

Uses PyMuPDF's `page.set_cropbox()` to set each page's CropBox metadata, rather than rasterizing
the page to a cropped image. This is non-destructive to the underlying content (text stays
selectable, vector graphics stay vector, file size is barely affected) and matches how virtually
every real-world PDF crop tool works, including Acrobat's default crop behavior.

The crop rectangle is stored and transmitted as **fractions (0–1) of page width/height**, not
absolute point coordinates. Applying the same fractional rectangle to every page (rather than one
fixed absolute-coordinate box) keeps behavior sensible for documents with mixed page sizes.

`app/core/pdf_ops.py` gets a new function:

```python
def crop_pdf(input_path: str, output_path: str, top: float, right: float, bottom: float, left: float) -> None
```

`top`/`right`/`bottom`/`left` are fractions (0–1) of each page's height/width/height/width
respectively, describing how much to trim from each edge. Validates `0 <= value < 1` for each,
plus an explicit positive-area check: `left + right < 1` and `top + bottom < 1`.

The original design used a tighter per-edge bound (`0 <= value < 0.5`), under which the sums were
implied and no separate positive-area check was reachable. That bound was relaxed during the final
whole-branch review because it rejected a large class of ordinary crops: keeping just the right
half of a page (`left = 0.5`), or the headline "zoom in on a small region" use case, which
necessarily pushes several margins past 50%. `CropSelector.jsx` lets the user drag *any* rectangle,
so those drags were 422ing. The actual mathematical requirement for a positive-area crop is the
pair of sum checks above, not a per-edge 0.5 limit, so the sum checks now carry that guarantee
explicitly.

### Add page numbers — backend technique

Uses `page.insert_textbox()` to draw the formatted page number string into each page's content
stream. Position is computed from the page's own `page.rect` dimensions: a narrow text band inset
by a fixed margin (36pt, i.e. 0.5in — the conventional print margin) from whichever edge(s) the
chosen corner touches, with `align=` set to centre/left/right so the string lands in the right
corner of that band. This differs from the existing Watermark tool, which passes the *entire*
`page.rect` as the box and centres the text across the whole page; page numbers need actual
corner/edge placement, which the narrow band plus `align=` provides.

`app/core/pdf_ops.py` gets a new function:

```python
def add_page_numbers(input_path: str, output_path: str, position: str, format: str) -> None
```

`position` ∈ `{bottom-center, bottom-right, bottom-left, top-center, top-right, top-left}`.
`format` ∈ `{number, number-of-total, page-x-of-y}` (rendering as `"3"`, `"3 / 12"`, and
`"Page 3 of 12"` respectively, using the document's actual page count for the total).

### Frontend — CropSelector component

A new `CropSelector.jsx` component, used only by the Crop tool (all other tools, including Add
Page Numbers, keep the existing `PageGrid` thumbnail-grid preview).

- Renders a single, larger preview of page 1 (a new higher-resolution thumbnail mode, ~700px on
  the long edge, vs. the existing 220px grid thumbnails — precision matters more here since the
  user is drawing a box against it).
- Mouse-down starts a drag; mouse-move updates a rectangle overlay in real time; mouse-up commits
  it. A dimmed mask covers the area outside the current rectangle so the "what gets kept" area is
  visually obvious.
- Dragging again (a new mouse-down) discards the old rectangle and starts drawing a new one —
  this is the entire adjustment mechanism, no resize handles.
- Internally tracks the rectangle in screen pixels (relative to the image element) while
  dragging, then converts to `{top, right, bottom, left}` fractions using the rendered image's
  `getBoundingClientRect()` dimensions once the drag ends. This conversion is what makes the
  fraction resolution-independent of both the preview's display size and the actual PDF page
  size.
- If no rectangle has been drawn, the Run button stays disabled. This is new behavior for
  `ToolView.jsx` — today Run is only disabled on `busy || files.length === 0`; page-selection
  tools (Remove/Extract pages) don't actually gate Run on a non-empty selection, they rely on the
  backend's `PDFError` for that. Crop needs its own extra precondition since drawing a box is the
  entire input — `ToolView.jsx` gains a small generic hook for this (e.g. an optional
  `canRun(state)` check surfaced per-preview-type) rather than a crop-only special case bolted on.
  *As built:* the implementation used an inline `config.preview === "crop" && !cropRect` check in
  the Run button's `disabled` expression and in `handleRun()`, not the generic `canRun(state)`
  hook. This was a deliberate simplification — crop is the only tool with such a precondition, so
  a config-driven indirection would have added a layer with exactly one user. If a second tool
  ever needs a run precondition, that is the point to introduce the generic hook.

### Frontend — Add Page Numbers

No new component. Two new `select` fields (`position`, `format`) in `toolConfigs.js`, and a new
`preview: "page-numbers"` branch in `ToolView.jsx`'s `renderPreview()`, reusing `PageGrid`'s
existing `overlay` prop — but that prop's current CSS (`.page-thumb__overlay`) always centers its
content via flexbox, since it was built for Watermark's whole-page-centered text. Page numbers
need actual corner placement, so `.page-thumb__overlay` gains a `data-position` (or a set of
modifier classes) so the overlay content can be anchored to any of the six corners/edges instead
of only centered — Watermark keeps using the (now-default) centered behavior unchanged.

## API contracts

- `POST /tools/crop` — body `{file_id, top, right, bottom, left}` (floats, 0–1). Returns the
  standard `{outputs: [{id, filename, download_url}]}` shape every tool endpoint already returns.
- `POST /tools/add-page-numbers` — body `{file_id, position, format}` (plain strings). Same
  response shape.

Both are added to `web/backend/routes/tools.py` alongside the existing ten tool routes, following
the exact same `_output_response()` helper pattern.

## Error handling

- Crop: any fraction outside `[0, 1)`, or a `left + right` / `top + bottom` sum of 1 or more,
  raises `PDFError` → existing 422 banner (see Architecture above). This covers
  both a malformed/tampered request and the frontend's own guard against a genuinely empty drag
  (click without moving) — see Frontend section.
- Add page numbers: `position`/`format` are plain strings in the request model (matching the
  existing `ToImagesRequest.image_format` precedent, not a Pydantic enum/`Literal`); invalid
  values are rejected by `add_page_numbers()` itself raising `PDFError` → the existing 422
  banner, the same path every other invalid-enum-style input in this app already takes.
- Both reuse the existing app-level `FileNotFoundError` → 404 handler for a stale/unknown
  `file_id`, same as every other tool.

## Testing

- `app/core/pdf_ops.py` unit tests: `crop_pdf` — correct CropBox dimensions for a single page,
  correct behavior across a multi-page document with **mixed page sizes** (proving the
  fraction-based approach works as intended), and `PDFError` for each invalid-fraction case.
  `add_page_numbers` — inserted text is present and roughly positioned correctly for each
  position × format combination (6 positions × 3 formats, or a representative subset), using
  PyMuPDF's own text-extraction to verify the expected string appears in the expected quadrant of
  the page.
- `web/backend/routes/tools.py` route tests (via `TestClient`), matching the existing pattern for
  every other tool: success case, 404 for unknown `file_id`, 422 for invalid input (bad fractions
  / bad enum value).
- No new frontend test infrastructure — `CropSelector`'s drag-to-rectangle behavior and the page
  numbers live-preview overlay are verified via manual browser testing at the end of
  implementation, matching how Watermark's and Rotate's live previews were verified last round.

## Out of scope (for this spec)

- Resize handles / adjusting an existing crop box without redrawing it.
- Per-page crop boxes.
- Click-to-place page numbers or a free-text format template.
- Groups B, C, D of Phase 2 (separate future specs).

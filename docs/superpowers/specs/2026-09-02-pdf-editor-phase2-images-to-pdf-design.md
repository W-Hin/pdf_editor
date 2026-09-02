# Phase 2, Group B: Images to PDF — Design

**Status:** Approved by user 2026-09-02.

## Context

This is the second sub-project of Phase 2 (see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s
roadmap and `docs/superpowers/specs/2026-09-02-pdf-editor-phase2-crop-page-numbers-design.md`'s
decomposition into Groups A-D). Group A (Crop, Add Page Numbers) shipped first. This spec covers
Group B, originally scoped as two separate tools — "JPG→PDF" and "Scan to PDF."

## Scope decisions (from brainstorming)

- **One tool, not two.** "Scan to PDF" implied camera-capture of a physical document, which
  doesn't make sense for a PC-only app with no camera-capture flow (mobile was explicitly
  descoped earlier in this project). Both original roadmap items collapse into a single tool:
  **Images to PDF** — combine existing image files (already on disk) into one PDF.
- **Supported formats:** JPG/JPEG and PNG. (Not GIF/BMP/WEBP/etc. — easy to extend later if
  actually needed; YAGNI for v1.)
- **Multiple images → one PDF**, one image per page, in upload order — mirrors the existing
  Merge tool's multi-file pattern exactly (append-only upload list, no reordering UI).
- **Page size:** every page is a standard A4 page (595×842pt portrait / 842×595pt landscape at
  72dpi), not "one page sized to match each image." Orientation is chosen per image to match that
  image's own aspect ratio (a landscape photo gets a landscape page) — otherwise "Fit" mode would
  make landscape images tiny with large empty margins.
- **Fit vs Fill**, a single dropdown applied to every image in the batch (not per-image, not a
  full manual crop/position UI — that would duplicate Group A's `CropSelector` scope for
  potentially many images at once):
  - **Fit** (`object-fit: contain` equivalent): the whole image is visible, letterboxed with
    white margins where the image's aspect ratio doesn't exactly match the page's.
  - **Fill** (`object-fit: cover` equivalent): the image is scaled to cover the entire page,
    cropping whatever overflows.
- **Live preview** shows each uploaded image mocked up on an A4-shaped box using the chosen
  Fit/Fill mode, before running — so the user sees the actual crop/letterbox behavior, not just a
  raw thumbnail.

## Key technical finding (verified empirically before finalizing this design)

PyMuPDF's `fitz.open()` already treats a raw JPG/PNG file as a 1-page pseudo-document
transparently: `doc.page_count == 1`, `doc.is_encrypted == False`, and `page.rect` reports the
image's real pixel dimensions. Confirmed via a live test against this project's actual PyMuPDF
version (not assumed from documentation). This means:

- `app/core/pdf_ops.py`'s existing `open_pdf()` / `get_page_count()` already work, unmodified, on
  a raw image file.
- `render_page_thumbnail()` already works, unmodified, to generate a thumbnail of an uploaded
  image.
- `web/backend/routes/files.py`'s existing `POST /files` upload route and
  `GET /files/{id}/pages/{n}/thumbnail` route need **zero changes** — they already handle image
  uploads correctly, because the PDF-specific code they call turns out not to be PDF-specific at
  the PyMuPDF layer.

This substantially shrinks this Group's backend footprint versus what "mirrors Merge/PDF-to-Image"
might have implied: no new upload endpoint, no new thumbnail endpoint. Only one new core function
and one new route are needed.

## Architecture

### Backend

`app/core/pdf_ops.py` gets one new function:

```python
def images_to_pdf(image_paths: list[str], output_path: str, fit_mode: str) -> None
```

- Validates `fit_mode in ("fit", "fill")` and `len(image_paths) >= 1`, raising `PDFError`
  otherwise, before doing any file I/O (matching every other function's validate-before-open
  convention).
- For each image path: `open_pdf(path)` (already works for images per the finding above) to get
  its `page.rect` dimensions and thus its aspect ratio. Choose A4 landscape
  (`fitz.Rect(0, 0, 842, 595)`) when the image is wider than it is tall (`width > height`),
  A4 portrait (`fitz.Rect(0, 0, 595, 842)`) otherwise (taller-than-wide or exactly square).
- Create a new page in the output document at that page size. Compute the target rect for
  `page.insert_image()`:
  - **Fit** (contain): scale so the image's larger-relative-to-page dimension exactly matches the
    page's corresponding dimension, center the (smaller-or-equal) result within the page.
  - **Fill** (cover): scale so the image's smaller-relative-to-page dimension exactly matches the
    page's corresponding dimension, center the (larger-or-equal, overflowing) result — the
    overflow is naturally clipped at the page boundary by `insert_image`/PDF rendering, with no
    extra clipping code needed.
- A corrupt/unreadable image raises `PDFError` for free, via the same `open_pdf()` every other
  tool already uses — no new error-handling code.

`web/backend/routes/tools.py` gets one new route:

```python
class ImagesToPdfRequest(BaseModel):
    file_ids: list[str]
    filename: str
    fit_mode: str


@router.post("/images-to-pdf")
def images_to_pdf_route(req: ImagesToPdfRequest): ...
```

Following the exact `merge` route's pattern: resolve each `file_id` via `storage.resolve_file()`,
validate/sanitize `filename` the same way `merge` already does (strip, reject path separators,
strip a redundant `.pdf` suffix), call `images_to_pdf()`, return via the shared
`_output_response()` helper.

### Frontend

- **`toolConfigs.js`** gains an `"images-to-pdf"` entry: category `"Convert"`, `multiFile: true`,
  `preview: "images-to-pdf"`, `fileAccept: ".jpg,.jpeg,.png"`, `filenameSuffix: "_combined"`
  (auto-fills the filename field from the first uploaded image's name, exactly like Merge's
  `_merged` suffix does today), one `select` field for `fit_mode` using the `{value, label}`
  option shape introduced in Group A (`"fit"` → "Fit (show the whole image)", `"fill"` → "Fill
  (crop to fill the page)"), and the existing `filename` text field reused verbatim from Merge's
  config shape.
- **`ToolView.jsx`**'s upload `<input>` currently hardcodes `accept=".pdf"`. It gains a
  `config.fileAccept ?? ".pdf"` fallback so every existing tool (which never sets `fileAccept`)
  is completely unaffected, while this tool can accept image files.
- **New preview branch** (`config.preview === "images-to-pdf"`) renders one A4-shaped box per
  uploaded file, in upload order — no new interactive component needed (unlike Group A's
  `CropSelector`). Each box is a fixed-aspect-ratio container (portrait or landscape, chosen the
  same way the backend chooses page orientation) containing an `<img>` with CSS
  `object-fit: contain` for `fit_mode === "fit"` and `object-fit: cover` for `fit_mode === "fill"`
  — reproducing the backend's exact visual behavior with a CSS property instead of new geometry
  code, so what the user sees before running matches what Run produces.

  **Orientation source:** the upload endpoint's response (`{id, filename, page_count}`) carries no
  width/height field, and adding one would be an unnecessary backend change. Instead, orientation
  is read client-side: the image's own `<img onLoad>` handler exposes `naturalWidth`/
  `naturalHeight`, exactly the technique `PageGrid.jsx`'s `handleImageLoad` already uses for the
  Rotate tool's fit-scaling. Each preview box defaults to portrait on first render (before the
  image has loaded) and corrects to landscape via a state update once `onLoad` fires if the image
  turns out wider than tall — the same one-frame-then-correct pattern already shipped for Rotate.

## Error handling

- `images_to_pdf`: empty `image_paths` or an unrecognized `fit_mode` both raise `PDFError` before
  any file is touched → the existing 422 banner.
- A corrupt/unreadable uploaded image raises `PDFError` via the shared `open_pdf()` path — same
  behavior as a corrupt PDF uploaded to any other tool today.
- The route reuses `storage.resolve_file()` per file id — a stale/unknown id 404s via the
  existing app-level `FileNotFoundError` handler, identical to every other tool.

## Testing

- `app/core/pdf_ops.py` unit tests (`tests/test_pdf_ops.py`): single image → 1-page PDF; multiple
  images with mixed portrait/landscape aspect ratios → correct per-page orientation; Fit mode
  produces an inserted rect smaller than or equal to the page on both axes; Fill mode produces an
  inserted rect that meets or exceeds the page on both axes (proving the contain/cover math,
  without needing to render and pixel-diff the output); invalid `fit_mode` and empty
  `image_paths` both raise `PDFError`.
- `web/backend/routes/tools.py` route tests (`tests/web/test_tools_edit_convert.py`, alongside
  the other Convert-category tools): success case (upload 2 images, run, expect 1 PDF output with
  `page_count == 2`), empty `file_ids` → 422, invalid `fit_mode` → 422, unknown `file_id` → 404,
  filename sanitization matching Merge's existing test coverage for the same logic.
- No new frontend test infrastructure — the A4 preview's Fit/Fill CSS behavior is verified by
  manual browser testing at the end of implementation, matching every prior UI feature this
  project has shipped.

## Out of scope (for this spec)

- Per-image manual crop/position control (would duplicate Group A's `CropSelector` scope).
- Reordering uploaded images before combining (matches Merge's existing lack of a reorder step).
- Any format beyond JPG/JPEG/PNG.
- Camera capture / "Scan to PDF" as a distinct concept — folded into this single tool per the
  scope decision above.

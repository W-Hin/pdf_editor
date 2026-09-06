# Phase 3, Group D: Compare PDF + PDF→Markdown — Design

**Status:** Approved by user 2026-09-06.

## Context

First sub-project of Phase 3 (see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s
roadmap). Phase 3's full scope was decomposed into five groups, queued lightest-to-heaviest so
the sub-projects with the least new-dependency risk ship first:

1. **This spec** — Compare PDF + PDF→Markdown (no external binaries; `numpy`, already present
   transitively, becomes a direct dependency; `pymupdf4llm` is a new pure-Python wheel).
2. Repair + Unlock/Protect (`pikepdf`/`qpdf`, prebuilt wheels).
3. PDF→PowerPoint / PDF→Excel, best-effort (scope/fidelity questions, no new binary).
4. Office→PDF conversion via headless LibreOffice (a real external application).
5. OCR (Tesseract) and PDF→PDF/A (Ghostscript or equivalent) — grouped together because both
   need a bundled external binary and share the same offline-packaging investigation.

PDF→PDF/A was originally assumed to belong in this lightest group, but was moved to group 5 after
checking this machine: no Ghostscript is installed, and PyMuPDF has no built-in PDF/A converter —
real PDF/A compliance needs either a bundled Ghostscript or a hand-rolled ICC/XMP/OutputIntent
implementation, neither of which is "lightweight."

This app continues to target the web app exclusively (FastAPI + React) — the PySide6 desktop app
has been an untouched fallback since the very first day of the project and Phase 3 does not change
that.

## Scope decisions (from brainstorming)

- **Compare PDF compares text AND renders a visual overlay** — not text-only. The visual path
  exists specifically to catch differences a text diff can't see (a moved image, a redrawn shape,
  any non-text visual change).
- **Visual diff display: side-by-side images, each with differing regions highlighted** — not a
  single blended/superimposed image. Easier to read, and avoids the failure modes a blended overlay
  has when pages don't align pixel-for-pixel.
- **Page matching: strict index (page N vs. page N).** No content-based re-alignment for
  inserted/deleted mid-document pages — that's a sequence-alignment problem out of scope for this
  utility. A page-count mismatch just means the extra trailing page(s) show as fully added/removed.
- **Compare PDF has no downloadable output at all** — the first tool in this app that's pure
  in-app inspection. Every other tool follows "pick file(s) → configure → Run → download"; Compare
  PDF is "pick two files → view," full stop.
- **PDF→Markdown extracts images too**, zipped together with the `.md` file — the first zipped,
  multi-file output in this app (distinct from the existing "several independent output files,
  each its own download link" pattern used by tools like Split).

## Architecture

### Compare PDF — backend

`app/core/compare_pdf.py` (new file — this is a big enough, self-contained piece of logic to earn
its own module rather than growing `pdf_ops.py` further):

- `extract_page_texts(path: str) -> list[str]`: one string per page, via the same
  `_page_text_spans`-adjacent text extraction `pdf_ops.py` already has (reuses
  `page.get_text()` — no new extraction logic needed for plain page text).
- `diff_page_text(text_a: str, text_b: str) -> list[dict]`: wraps `difflib.unified_diff` (or
  `SequenceMatcher.get_opcodes()` for line-level add/remove/replace/equal spans — chosen over
  `unified_diff`'s string-based output because the frontend needs structured `{op, text}` entries
  to render its own diff styling, not a pre-formatted text block). Pure stdlib, no new dependency.
- `render_page_image(path: str, page_num: int, max_size: int) -> bytes`: reuses the existing
  `render_page_thumbnail` scaling convention (`scale = max_size / max(rect.width, rect.height)`)
  so Compare PDF's images are pixel-comparable in scale to what `PageScrollViewer` already shows
  elsewhere in the app.
- `diff_page_visual(path_a: str, path_b: str, page_num: int, max_size: int) -> list[dict]`:
  renders both pages to same-scale RGB pixmaps (if the two pages differ in aspect ratio, pad the
  smaller to the larger's canvas size — pure black-fill padding, not a stretch, so no distortion),
  converts each to a `numpy` array via `pix.samples`, takes `np.abs(a.astype(int) -
  b.astype(int))`, thresholds per-pixel (a difference below a small tolerance, e.g. 24/255 per
  channel, is treated as noise from anti-aliasing/JPEG-ish re-rendering rather than a real content
  change), then clusters the thresholded mask into bounding boxes via a coarse grid merge: divide
  the mask into ~20×20px cells, mark any cell containing a flagged pixel, then merge
  horizontally/vertically adjacent marked cells into rectangles (a small, dependency-free
  flood-fill over the coarse grid — no `scipy.ndimage.label` needed, since box-level precision is
  enough for "here's roughly where it changed," not pixel-perfect segmentation). Returns
  `[{x0, y0, x1, y1}, ...]` as page-fraction coordinates (0-1), matching how every other
  interactive element's position is already expressed elsewhere in this app (`EditPdfCanvas`'s
  elements, `RedactSelector`'s boxes, etc.).
- `numpy` moves from a transitive, unpinned dependency to an explicit line in `requirements.txt`.

### Compare PDF — API

`web/backend/routes/compare.py` (new route module — this doesn't fit `tools.py`'s "one endpoint
per single-file-in, single/multi-file-out tool" shape, since it takes two files and returns no
downloadable output):

- `POST /api/compare` — body `{file_id_a, file_id_b}`, returns
  `{page_count_a, page_count_b, pages: [{text_diff: [...], has_counterpart: bool}, ...]}`
  (the text diff for every page up front — it's cheap; the visual diff is requested lazily below,
  since rendering+diffing every page's images up front for a long document would be wasteful when
  the user is only looking at a few pages at a time).
- `GET /api/compare/{file_id_a}/{file_id_b}/{page_num}/visual` — returns
  `{image_a: <base64 PNG>, image_b: <base64 PNG>, boxes: [{x0,y0,x1,y1}, ...]}`, computed on
  demand per page as the user scrolls to it (mirrors how `PageScrollViewer` already lazily
  requests each page's thumbnail rather than rendering a whole document up front).
- No `storage.record_output` call anywhere in this flow — nothing is written to Recent
  Files/output history, consistent with "no downloadable output."

### Compare PDF — frontend

`web/frontend/src/components/ComparePdfView.jsx` (new):

- Two file-picker inputs (doc A, doc B) instead of the single-file pattern every other tool uses.
- Once both are uploaded and `POST /api/compare` returns, renders one block per page using
  `PageScrollViewer`'s continuous-scroll pattern (read-only — no `renderPageOverlay` interaction
  needed, just a per-page render function): a text-diff panel (added lines green, removed lines
  red, unchanged lines plain — standard diff styling) stacked above a side-by-side visual panel
  that lazily fetches `/api/compare/.../visual` for that page once it's scrolled into view (same
  `IntersectionObserver`-driven lazy-load `PageScrollViewer` already does for thumbnails).
- A page with `has_counterpart: false` renders as a single, full-width "Page added" or "Page
  removed" block instead of the two-panel layout — nothing to diff against.
- `ToolView.jsx` gains a branch (or `ComparePdfView` is used directly, bypassing `ToolView`'s
  generic "pick file → configure → Run" flow entirely, since none of that flow applies here) —
  exact wiring decided during planning once the current `ToolView`/routing structure is read fresh.

### PDF→Markdown — backend

Add to `app/core/pdf_ops.py` (small enough to not need its own module, unlike Compare PDF):

- `pdf_to_markdown_zip(input_path: str, output_path: str) -> None`: calls
  `pymupdf4llm.to_markdown(input_path, write_images=True, image_path=<temp dir>)` (its built-in
  table detection stays on — no reason to disable it), then zips the returned markdown string
  (written to a `.md` file inside the temp dir) together with every extracted image file into
  `output_path` (a `.zip`), via the stdlib `zipfile` module (no new dependency).
- New dependency: `pymupdf4llm` (pure-Python, built directly on the `PyMuPDF` already installed —
  no separate binary, no license concern beyond what already applies to PyMuPDF itself).

### PDF→Markdown — API and frontend

- `POST /api/tools/pdf-to-markdown` in `tools.py` (fits the existing single-file-in/single-file-out
  shape exactly) — `_output_response` already accepts any output path regardless of extension
  (confirmed: `page_count` is only computed `if path.suffix.lower() == ".pdf"`, else `None` — a
  `.zip` output falls through that branch cleanly with no code change needed there).
- Frontend: registers as a normal entry in `toolConfigs.js`/`ToolView.jsx`'s existing generic
  single-file tool flow — no new UI pattern, just a `.zip` download at the end instead of `.pdf`.

## Testing

`tests/test_compare_pdf.py` (new file, mirroring `test_pdf_ops.py`'s house style — throwaway PDFs
generated at test time via PyMuPDF):

- `test_diff_page_text_detects_a_changed_line`: two generated PDFs, one page each, differing by
  one sentence — assert the diff reports exactly that one change (an `equal` opcode for everything
  else).
- `test_diff_page_visual_detects_a_shape_change_text_diff_misses`: two generated PDFs with
  IDENTICAL extractable text but a rectangle drawn at a different position on one — assert
  `diff_page_text` reports no changes while `diff_page_visual` returns at least one non-empty
  bounding box.
- `test_diff_page_visual_ignores_negligible_rendering_noise`: two RENDERS of the exact same PDF
  (same input twice) — assert `diff_page_visual` returns zero boxes, proving the threshold
  correctly treats identical content as identical rather than flagging anti-aliasing noise as a
  difference.
- `test_compare_reports_trailing_page_as_added`: a 2-page vs. a 3-page PDF — assert page 3 has
  `has_counterpart: False` in the route's response.

`tests/test_pdf_ops.py` gains:

- `test_pdf_to_markdown_zip_contains_markdown_and_extracted_image`: a generated PDF with a
  heading, a paragraph, and one embedded image — assert the output `.zip` contains a `.md` file
  whose text includes the expected heading/paragraph substrings, and at least one image file.

No frontend automated tests (established convention) — manual verification at the end of
implementation: uploading two different PDFs to Compare PDF shows correct text and visual diffs
per page; a page-count mismatch shows the correct added/removed block; PDF→Markdown's downloaded
`.zip` opens correctly with a readable `.md` file and its images.

## Out of scope

- Content-based page re-alignment for Compare PDF (sequence-alignment for inserted/deleted pages)
  — strict index matching only, per the scope decision above.
- A downloadable Compare PDF report (HTML/PDF export of the diff) — in-app view only.
- PDF/A conversion — moved to Phase 3 group 5 (see Context above).

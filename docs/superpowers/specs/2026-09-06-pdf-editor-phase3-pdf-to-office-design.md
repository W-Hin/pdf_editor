# Phase 3, Group 3: PDF→PowerPoint + PDF→Excel (best-effort) — Design

**Status:** Approved by user 2026-09-06.

## Context

Third sub-project of Phase 3 (see the decomposition and queue order in
`docs/superpowers/specs/2026-09-06-pdf-editor-phase3-compare-markdown-design.md`'s Context
section). The original roadmap explicitly flags these as "best-effort only — no strong
open-source converter exists for these; low fidelity expected." Before writing this spec, both
directions were verified empirically end-to-end rather than assumed feasible from documentation
alone:

- Rendering a PDF page and embedding it as a full-slide image in a `python-pptx` presentation
  round-trips cleanly (built, saved, and re-opened a real `.pptx`).
- Extracting PyMuPDF text **blocks** (paragraph-level grouping, from `page.get_text("dict")` —
  already available, no new dependency) and placing one positioned `python-pptx` text box per
  block, with one run per span, produces correctly positioned/sized boxes with correct font size
  — verified against exact bbox/EMU values from a real test document.
- PyMuPDF's built-in `page.find_tables()` (already part of the existing PyMuPDF dependency)
  correctly detects a real ruled table and extracts its rows/columns as plain Python lists.
- `python-pptx` and `openpyxl` both install as pure-Python wheels with no external binary
  dependency, matching this group's "no new heavy dependency" position in the queue.

## Scope decisions (from brainstorming)

- **PDF→PowerPoint attempts real, positioned, editable text boxes** — not a picture-per-slide
  fallback. The user explicitly chose the higher-effort, higher-fidelity approach over the
  guaranteed-but-non-editable "render each page as an image" alternative, accepting the
  roadmap's own "low fidelity expected" framing as the honest ceiling on how well this can work
  for complex layouts (multi-column text, unusual positioning) rather than a guarantee.
- **Text box granularity is PyMuPDF's own text BLOCK (paragraph-level)** — the same granularity
  this project's existing PDF→Word converter (`pdf2docx`) already uses ("positioned text boxes...
  rather than true flowing paragraphs," per the original v1 design spec), for consistency across
  this app's PDF-to-office-format conversions.
- **Font mapping reuses this codebase's existing closest-base14/bold-italic-flag detection** —
  the same logic `pdf_ops.py` already has for Edit PDF/Add Text (`_closest_base14_family`,
  `flags & 16`/`flags & 2` for bold/italic) — not a separate, newly-invented mapping.
- **PDF→Excel only includes genuinely detected tables** — a page with no detected table
  contributes nothing to the output, rather than dumping raw unstructured text into cells as a
  fallback. A document with zero detected tables anywhere is a hard error, not an empty/pointless
  workbook.

## Architecture

### PDF→PowerPoint

`app/core/pdf_to_office.py` (new module — distinct from `pdf_ops.py` since this is PDF-to-other-
format conversion, alongside `convert.py`'s existing PDF→Word, not PDF-in-PDF-out editing):

```python
def pdf_to_pptx(input_path: str, output_path: str) -> None:
```

For each page: creates a slide sized to match the page's own dimensions (`python-pptx` accepts
arbitrary slide sizes in EMU; 1pt = 12700 EMU, verified). Iterates `page.get_text("dict")["blocks"]`
(skipping any block with no `"lines"` key — image blocks, not text); for each block, adds a
`python-pptx` text box positioned/sized to the block's bbox (converted pt→EMU), with
`text_frame.word_wrap = True`, one paragraph per line, and one run per span. Each run's
`font.size` comes from the span's own size; `font.bold`/`font.italic` come from the span's
`flags & 16`/`flags & 2` (the identical bit-flag check `_apply_text_edit` already uses); the
font *name* set on the run is the closest base-14 family via the existing
`_closest_base14_family(span["font"])` helper in `pdf_ops.py` (imported, not reimplemented).

### PDF→Excel

Also in `pdf_to_office.py`:

```python
def pdf_to_xlsx(input_path: str, output_path: str) -> None:
```

For each page, calls `page.find_tables()`; for each table found, `.extract()`'s its rows and
writes them into a new `openpyxl` worksheet (one sheet per detected table, named e.g.
`Page{n}_Table{i}` to stay unique and traceable back to its source page). If zero tables are
found across the entire document, raises `PDFError("No tables found in this document.")` before
ever calling `workbook.save()` — no empty/invalid `.xlsx` is ever produced.

### API and frontend

Both fit the existing single-file-in/single-file-out tool pattern exactly:

- `POST /api/tools/pdf-to-pptx` and `POST /api/tools/pdf-to-xlsx` in `tools.py`.
- Two new entries in `toolConfigs.js`/`ToolView.jsx`'s existing generic flow — no new UI pattern,
  no configuration options beyond the standard file picker + Run.
- New dependencies added to `requirements.txt`: `python-pptx`, `openpyxl` (both pure-Python
  wheels, verified with no external binary requirement).

## Testing

`tests/test_pdf_to_office.py` (new file, house style — throwaway PDFs generated at test time,
every numeric claim verified empirically during this session before being written here):

- `test_pdf_to_pptx_creates_positioned_textboxes`: a PDF with a heading and a paragraph at known
  positions — asserts exactly 2 text boxes exist, with position/size matching the source blocks'
  bboxes (in EMU) and correct text content.
- `test_pdf_to_pptx_preserves_font_size_bold_and_family`: a bold Helvetica span and a separate
  Times-family span — asserts the corresponding runs' `font.size`/`font.bold` and mapped family
  match.
- `test_pdf_to_pptx_matches_slide_size_to_page_size`: asserts the output presentation's slide
  width/height (EMU) match the source PDF's page dimensions.
- `test_pdf_to_xlsx_extracts_detected_table`: a PDF with one ruled 2×2 table — asserts the output
  sheet's cell values match exactly.
- `test_pdf_to_xlsx_skips_pages_without_tables`: a 2-page document, only one page has a table —
  asserts exactly one sheet in the output.
- `test_pdf_to_xlsx_raises_when_no_tables_found`: a table-free document — asserts `PDFError`.

No frontend automated tests (established convention) — manual checklist: run both converters on a
real multi-section document and a real tabular document, open the resulting `.pptx`/`.xlsx` in an
actual viewer to confirm they're valid, readable files, and sanity-check text-box positioning
against the original PDF's visual layout.

## Out of scope

- Any fallback for PDF→Excel pages without a detected table (dumping raw text into cells) — per
  the scope decision above, those pages simply contribute nothing.
- Preserving embedded images from the PDF in either output format — text/table content only, per
  the roadmap's own "best-effort" framing; adding image placement to an already-uncertain-fidelity
  conversion is not worth the added complexity for this pass.
- Any attempt to detect/reconstruct multi-column layouts, headers/footers as distinct PowerPoint
  placeholders, or slide-master styling — every block becomes a plain positioned text box, with
  no layout inference beyond what PyMuPDF's own block segmentation already provides.

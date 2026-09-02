# Phase 2, Group C1: Redact — Design

**Status:** Approved by user 2026-09-02.

## Context

This is a sub-project of Phase 2 (see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s
roadmap and `docs/superpowers/specs/2026-09-02-pdf-editor-phase2-crop-page-numbers-design.md`'s
decomposition into Groups A-D). Group A (Crop, Add Page Numbers) and Group B (Images to PDF) have
both shipped. Group C was originally scoped as two features — "direct in-PDF text editing" and
"Redact" — bundled together because both need a click-to-select-a-region UI. During brainstorming
for this spec, Group C was split further: Redact (this spec) is meaningfully simpler than direct
text editing (which additionally needs font detection/matching and text-run-level editing, not
just region removal) and reuses Crop's region-selection technique almost directly. Direct text
editing gets its own future spec.

## Scope decisions (from brainstorming)

- **Multi-page, not page-1-only.** Unlike Crop (one box, applied uniformly to every page), real
  redaction targets are scattered across different pages of a document (an SSN on page 2, a name
  on page 5). The UI supports navigating between pages and drawing boxes on any/all of them.
- **Multiple boxes per page.** A single page can have several redaction areas (e.g. a name and an
  account number on the same page).
- **Page navigation:** Previous/Next buttons plus a "Page X of N (K pages marked)" label — not a
  clickable thumbnail strip. Simple, familiar, and the marked-page count keeps the user oriented
  without needing to build a mini-thumbnail-strip component.
- **Removing a box:** a small × button on each drawn box — not "click the box to remove it" (which
  would be ambiguous against "click empty space to start a new drag").
- **Redaction technique: real removal, not a visual overlay.** Uses PyMuPDF's actual redaction
  API (`page.add_redact_annot()` + `page.apply_redactions()`), which permanently strips the
  underlying text/image content within each box — not just paints a black rectangle on top of
  still-present, still-recoverable content. This is the entire point of a tool called "Redact";
  a fake redaction would be a security defect, not a legitimate simpler alternative, so this
  wasn't treated as an open design question.

## Key technical finding (verified empirically before finalizing this design)

PyMuPDF's `add_redact_annot()` + `apply_redactions()` was tested directly against this project's
actual PyMuPDF version (not assumed from documentation) with three concrete checks:

1. **Real removal, not a visual overlay:** text inside a redacted rect is genuinely gone from
   `page.get_text()` afterward — confirmed by inserting two lines of text, redacting only one,
   and verifying the redacted string no longer appears in extracted text while the other line's
   text does.
2. **Visual fill:** the redacted area renders as solid black (`(0, 0, 0)` sampled directly from
   the rendered pixmap), with the surrounding page background unaffected.
3. **Multi-page, multi-box isolation:** queuing redaction annotations on multiple pages (via
   repeated `add_redact_annot()` calls) and then calling `apply_redactions()` once per page
   correctly scopes each page's removal to only that page's own annotations — a page with no
   annotations queued against it is completely untouched, and a page with multiple annotations
   has only the annotated regions' content removed, leaving the rest of that page's content
   intact.

This confirms the spec's core technical approach works exactly as designed, not just as
documented.

## Architecture

### Backend

`app/core/pdf_ops.py` gets one new function:

```python
def redact_pdf(input_path: str, output_path: str, redactions: list[dict]) -> None
```

Each item in `redactions` is `{"page": int, "top": float, "right": float, "bottom": float, "left": float}`
— `page` is 1-indexed; the four fractions are 0-1 fractions of *that specific page's* own
width/height, using the exact same fraction semantics and validation Crop already established
(`0 <= value < 1` per edge, plus `left + right < 1` and `top + bottom < 1` to guarantee positive
area — see `docs/superpowers/specs/2026-09-02-pdf-editor-phase2-crop-page-numbers-design.md`'s
Architecture section for why that pair of checks is sufficient on its own).

Processing:
1. Validate `redactions` is non-empty, raising `PDFError` otherwise.
2. Validate every `page` number is within `1..doc.page_count` *before* touching any page — a
   stale/out-of-range page reference fails cleanly up front rather than mid-loop, leaving no
   partially-redacted output.
3. Validate every box's fractions using Crop's exact bound.
4. For each redaction: convert its fractions to an absolute `fitz.Rect` on that specific page
   (identical conversion arithmetic to `crop_pdf`, just per-box instead of per-document-uniform),
   then `page.add_redact_annot(rect * page.derotation_matrix, fill=(0, 0, 0))` — queuing it, not
   applying yet.

   > **The derotation multiply is not optional, and "identical to `crop_pdf`" means *including*
   > this step.** `page.rect` is the *displayed* (rotation-aware) rectangle — the one the user
   > actually drew their box on — but `add_redact_annot` (like `set_cropbox`) interprets its
   > argument in *unrotated mediabox* space. `crop_pdf` already handles this by multiplying by
   > `page.derotation_matrix` before calling `set_cropbox` (identity when rotation is 0). The
   > original implementation of `redact_pdf` reused Crop's fraction arithmetic but **omitted this
   > derotation step**, and the gap was only caught by the final whole-branch review: on a
   > 90°-rotated page the tool reported success while leaving the marked text fully intact and
   > extractable, *and* destroyed an unrelated region instead. It is fixed now, and
   > `tests/test_pdf_ops.py::test_redact_pdf_handles_rotated_page` locks it in. Any future tool
   > that cites this "identical conversion arithmetic to `crop_pdf`" claim must verify the
   > derotation step specifically — it is the part that is easy to read past.
5. After all boxes are queued, call `page.apply_redactions()` once per page that has at least one
   annotation — this is what actually strips the content and paints the black fill.
6. Save.

A corrupt/unreadable input PDF raises `PDFError` for free via the existing `open_pdf()` path.

`web/backend/routes/tools.py` gets one new route. Unlike the spec's earlier draft, the request
model uses an explicit nested Pydantic model for each box — not a raw `list[dict]` — matching
every other route in this file (`CropRequest`, `AddPageNumbersRequest`, etc. all use explicit
typed fields, giving free validation and clear API shape instead of accepting arbitrary dicts):

```python
class RedactionBox(BaseModel):
    page: int
    top: float
    right: float
    bottom: float
    left: float


class RedactRequest(BaseModel):
    file_id: str
    redactions: list[RedactionBox]


@router.post("/redact")
def redact(req: RedactRequest): ...
```

Following the single-file-input tools' existing pattern (e.g. `rotate`): resolve `file_id`,
convert each validated `RedactionBox` to a plain dict (`app/core/pdf_ops.py` stays
framework-agnostic with zero Pydantic dependency, matching its existing "pure Python, zero UI
dependencies" design — Pydantic validation belongs at the route boundary only), call
`redact_pdf()` with that list of dicts, return via `_output_response()`.

### Frontend

A new `RedactSelector.jsx` component, built on the same drag-to-rectangle technique
`CropSelector` established in Group A (screen pixels → 0-1 fraction via the rendered image's
`getBoundingClientRect()`, using a higher-resolution ~700px single-page preview via
`thumbnailUrl(fileId, pageNumber, 700)` — the `max_size` query param already exists from Group A,
no backend change needed here), extended for multi-page/multi-box state:

- **State:** `currentPage` (starts at 1) and `redactions` — a single flat array of
  `{page, top, right, bottom, left}` for the *entire document*, matching the API body shape
  exactly (no reshaping needed between frontend state and the request payload). Switching pages
  doesn't clear or reset this array — it's filtered per-render (`redactions.filter(r => r.page === currentPage)`)
  to decide what's drawn on the currently-displayed page, so previously-marked pages keep their
  boxes when the user navigates back to them.
- **Page navigation:** Previous/Next buttons (disabled at the first/last page respectively) and a
  label reading "Page {currentPage} of {pageCount} ({markedPageCount} page{s} marked)", where
  `markedPageCount` is the count of distinct `page` values present in `redactions`.
- **Adding a box:** dragging on empty space within the preview adds a new
  `{page: currentPage, top, right, bottom, left}` entry to `redactions` — same drag-mechanics as
  `CropSelector` (mousedown/mousemove/mouseup, same ≥2%-of-both-dimensions minimum-drag
  threshold to ignore an accidental click), but *appending* a new box instead of *replacing* the
  single box `CropSelector` tracks.
- **Rendering boxes:** each box for the current page renders as a solid black rectangle directly
  over the content it will remove — this previews the *actual* redaction result, and is visually
  simpler than Crop's "dim everything outside the box" masking, since there's no longer a single
  "everything outside this one box" region to dim.
- **Removing a box:** each rendered box carries a small × button in its corner. The button's own
  click handler removes that specific entry from `redactions`; it must call
  `e.stopPropagation()` (or an equivalent guard) so clicking it doesn't also register as a
  mousedown on the container and accidentally start a new drag.
- **Run button:** disabled until `redactions.length > 0` (at least one box drawn anywhere in the
  document) — following the exact `config.preview === "redact" && redactions.length === 0`-style
  inline gate pattern Crop already established in the shared `handleRun`/Run-button code in
  `ToolView.jsx`, so no other tool's behavior changes.

`toolConfigs.js` gets a `redact` entry: category `"Edit"` (alongside Rotate, Watermark, Add page
numbers, Crop), `multiFile: false`, `preview: "redact"`, `endpoint: "redact"`, `fields: []` (no
config-driven fields — like Crop, the drawn boxes *are* the entire input).

## Error handling

- `redact_pdf`: empty `redactions`, an out-of-range `page`, or any box fraction outside the valid
  bound all raise `PDFError` before any page is modified → the existing 422 banner.
- A corrupt/unreadable input PDF raises `PDFError` via the shared `open_pdf()` path.
- The route reuses `storage.resolve_file()` — a stale/unknown `file_id` 404s via the existing
  app-level handler, identical to every other tool.
- Frontend: Run stays disabled until at least one box exists anywhere in the document, mirroring
  Crop's exact precedent for a tool whose entire input is user-drawn boxes rather than
  config-driven fields.

## Testing

- `app/core/pdf_ops.py` unit tests (`tests/test_pdf_ops.py`): single box on a single-page
  document removes the covered text (extract text before and after, confirm the redacted string
  is genuinely gone — this is the test that actually proves real redaction, not just a visual
  overlay, matching the spec's core requirement); multiple boxes on the same page; boxes spread
  across different pages of a multi-page document, each correctly redacting only its own page;
  empty `redactions` list rejected; out-of-range `page` rejected; invalid box fractions rejected
  (reusing Crop's exact boundary test cases: `0.5` no longer at the boundary since Crop's bound is
  `< 1` with a sum check — see the Crop spec's Architecture section for the up-to-date bound).
- `web/backend/routes/tools.py` route tests (`tests/web/test_tools_edit_convert.py`): success
  case, empty `redactions` → 422, unknown `file_id` → 404.
- No new frontend test infrastructure — `RedactSelector`'s drag/add/remove/navigate behavior is
  verified via manual browser testing at the end of implementation, matching every prior UI
  feature this project has shipped (Crop's drag-to-select, Images to PDF's Fit/Fill preview,
  etc.).

## Out of scope (for this spec)

- Direct in-PDF text editing (find/replace a text run in place) — a separate future spec, per the
  brainstorming decision to split what was originally "Group C" into two sub-projects.
- A clickable page-thumbnail-strip navigator (Previous/Next + a text label was chosen instead).
- Redacting by clicking detected text runs rather than drawing a box (that's closer to what direct
  text editing will need — Redact stays a pure freeform rectangle tool, like Crop).
- Any configurable redaction fill color (always solid black, matching every standard redaction
  tool's default).

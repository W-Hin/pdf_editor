# Add Watermark: Size & Rotation Controls — Design

**Status:** Approved by user 2026-09-04.

## Context

Second of five sub-projects from a larger feedback batch (see the decomposition in
`docs/superpowers/specs/2026-09-04-pdf-editor-page-scroll-viewer-design.md`'s Context section).
The user wants to control the watermark's font size and rotation angle — including angles like
45° that PyMuPDF's current rendering approach (`insert_textbox`) doesn't support — with the change
reflected live in the existing preview.

## Key technical finding (verified empirically before finalizing this design)

`page.insert_textbox(..., rotate=angle)` — the API `add_watermark` currently uses — only accepts
angles that are multiples of 90; passing `rotate=45` raises `ValueError: rotate must be multiple
of 90`. Switching to `page.insert_text()` with a `morph=(pivot_point, fitz.Matrix(angle))`
transform supports arbitrary angles — verified by rendering a 45°-rotated "DIAGONAL WATERMARK"
centered on a page and confirming the output image shows a genuine diagonal line of text, not an
error or a silently-unrotated result. `insert_text` doesn't auto-wrap the way `insert_textbox`
does, but a single centered watermark line doesn't need wrapping — matching its existing
single-line `<input type="text">` field.

## Scope decisions (from brainstorming)

- **Rotation is a continuous 0–360° slider**, not preset-angle buttons — full freedom to rotate to
  any angle, with the live preview updating as the slider is dragged.
- **Font size becomes a user-adjustable slider**, alongside the existing opacity slider — the core
  function (`add_watermark`) already accepts a `font_size` parameter; it just isn't exposed via
  the API or frontend yet.
- **Single-line watermark text only** — matches the existing text field, no new wrapping behavior.
- **One angle/size applies to every page** — matches current behavior (the same watermark
  configuration renders identically on every page), not a per-page setting.

## Architecture

### Backend

- `add_watermark`'s `rotate` parameter changes from an `int` restricted to `{0, 90, 180, 270}` to
  a `float` accepting the full `0..360` range, implemented via the `insert_text` + `morph`
  technique verified above (replacing the `insert_textbox` call).
- `WatermarkRequest` (`web/backend/routes/tools.py`) gains `font_size: float` and `rotate: float`
  fields (currently only `file_id`/`text`/`opacity` are exposed), both passed through to
  `add_watermark`.

### Frontend

- `toolConfigs.js`'s `watermark` entry gains two new fields: `font_size` (range slider, 10–120pt,
  default 40 — matching the core function's existing default) and `rotate` (a continuous 0–360°
  slider).
- The existing live preview (`PageGrid`'s `overlay` prop, unchanged mechanism — a CSS-only text
  overlay repeated across every page thumbnail in the grid) applies a CSS `transform:
  rotate(${angle}deg)` and scales the overlay text's `font-size`, so both sliders update the
  preview live, the same way the existing opacity slider already does.

## Testing

- `tests/test_pdf_ops.py`: `add_watermark` at a non-90°-multiple angle (e.g. 45°) renders
  correctly, verified via pixel sampling along the expected diagonal — matching this project's
  established pixel-sampling test style for other rotated/angled content. A custom `font_size`
  produces a visibly larger/smaller rendered ink bounding box than the default, verified via
  measurement, similar to Add Text's font-size tests.
- Route tests: the existing success-case test extended to include `font_size`/`rotate`.
- No frontend automated tests (established convention) — manual verification that both sliders
  update the live preview immediately and that the downloaded output matches what the preview
  showed.

## Out of scope

- Font family or color changes for the watermark (not requested).
- Multi-line watermark text.
- Per-page differing watermark angle/size.

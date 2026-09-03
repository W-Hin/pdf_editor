# Edit PDF: Add Text — Design

**Status:** Approved by user 2026-09-04.

## Context

Edit PDF (Phase 2, Group C2 — see
`docs/superpowers/specs/2026-09-03-pdf-editor-phase2-edit-pdf-design.md`) shipped as one unified
tool with five modes: Edit Text (redact-and-reinsert an *existing* text run), Draw, Shapes,
Highlight, and Insert Image. During that feature's brainstorming, the user separately flagged a
gap: there was no way to add brand-new text anywhere on the page with its own font styling — Edit
Text only edits text that already exists in the document. That request was deferred until after
PDF Forms (Group D2, shipped) so it could get its own focused design pass rather than being folded
in as an afterthought. This spec adds that capability as a sixth mode, **Add Text**, to the
already-shipped Edit PDF tool.

## Key technical findings (verified empirically before finalizing this design)

Verified directly against this project's actual PyMuPDF version (1.28.2) via throwaway scripts:

1. **`insert_text()` has no underline parameter.** Underlining a line of inserted text requires
   drawing a separate line manually beneath it via `page.draw_line()`, sized to that line's own
   measured width (`fitz.get_text_length()`) and positioned a small offset below the baseline.
   Verified: inserting `"Underlined Text"` at 20pt then drawing a line under it produces the
   expected single extra line-drawing object in the saved PDF, with `get_text()` still extracting
   the plain text correctly.
2. **Multi-line wrapping with per-line underline and alignment requires manual line layout, not
   `insert_textbox()`.** `insert_textbox()` (already used elsewhere in this codebase for Watermark
   and Page Numbers) wraps text for you but doesn't expose the resulting line boundaries or
   per-line widths, which are needed to draw a correctly-sized underline under *each* wrapped line
   and to position each line for left/center/right alignment. Verified instead: a manual greedy
   word-wrap (accumulate words while `get_text_length(candidate) <= box_width`, matching this
   codebase's existing shrink-to-fit measurement approach) followed by one `insert_text()` call per
   line, positioned by that line's own measured width for alignment and stacked by `size * 1.2` for
   line height. A test sentence at 12pt in a 228pt-wide box wrapped into exactly the expected 3
   lines, extracted back out as 3 correctly-separated lines, with 3 underline-drawing objects
   present when underline was enabled — confirming per-line positioning is correct, not just
   single-line.

## Scope decisions (from brainstorming)

- **A sixth mode**, not a separate tool: "Add Text" joins Edit Text | Draw | Shapes | Highlight |
  Insert Image in the same mode-switcher toolbar, on the same shared canvas, queued into the same
  `elements` array and applied in the same Run — no architectural change to the tool itself.
- **Placement:** click a spot on the page to drop a default-size text box there, which immediately
  opens an inline editor (a text area plus a styling strip) right on the canvas — mirroring Insert
  Image's "click to place, then resize/reposition" pattern rather than Highlight/Shapes' drag-a-box
  gesture, since there's no meaningful box to draw before any text exists.
- **After placement:** the box behaves like an `image` element, not a `text_edit` element — single
  click selects it (body-drag repositions, corner handles resize, × removes, Ctrl+C/X/V copies,
  cuts, and pastes it), while double-click reopens the inline editor to change the text or styling.
  This split (select-to-move vs. double-click-to-edit) was chosen deliberately over `text_edit`'s
  "click always reopens the editor" behavior, because unlike a `text_edit` (anchored to one
  specific existing run, where duplicating it elsewhere doesn't make sense) a freely-placed new
  text box is exactly the kind of element a user would want to copy/paste to another spot.
- **Wrapping:** multi-line, wrapping within the box; resizing the box reflows the wrap.
- **Styling, all in one inline toolbar on the editor:** font family (the same base-14 trio Edit
  Text already offers — Helvetica/Times/Courier), size, bold, italic, underline, color (the same
  shared color picker Draw/Shapes/Highlight already use), and alignment (left/center/right).
- **Keyboard shortcuts while the editor is focused:** Ctrl+B / Ctrl+I / Ctrl+U toggle bold/italic/
  underline — the same booleans the toolbar's B/I/U buttons control, just a second way to flip
  them. Scoped to the inline editor's own `onKeyDown` handler (not the canvas's document-level
  clipboard/undo listener, which explicitly *ignores* keystrokes while a text input is focused —
  this is the opposite condition, active only while that text input has focus).
- **Empty text is discarded, not saved as an empty box:** clicking away from the editor without
  having typed anything abandons the placement entirely.
- **Overflow:** if wrapped lines exceed the box height, drawing simply stops at the box's bottom
  edge rather than auto-shrinking the font — a documented ceiling (the box is user-resizable, so
  it's recoverable), matching the same treatment this tool's Edit Text mode already gives its own
  white-fill erase limitation.
- **Rich/partial styling within one box (e.g. bolding a single word mid-sentence) is out of
  scope** — the whole box shares one style, consistent with every other element type in this tool
  having one uniform style.

## Architecture

### Element model

One new entry in the existing flat `elements` array (alongside `text_edit`/`stroke`/`shape`/
`highlight`/`image`):

```js
{
  id, type: "new_text", page,
  x, y, width, height,        // fractions of displayed page size, same convention as `image`
  text,
  family,                     // "helvetica" | "times" | "courier"
  bold, italic, underline,    // booleans
  size,                       // pt
  color,                      // hex string
  align,                      // "left" | "center" | "right"
}
```

Unlike `text_edit`'s nullable `font_override` (which overrides a *detected* font), every
`new_text` field is always present — there's nothing to detect, since this text didn't exist
before. Defaults when a box is first placed: Helvetica, 14pt, not bold, not italic, not underlined,
black, left-aligned.

### Backend

`app/core/pdf_ops.py` gets a new `_apply_new_text(page, el)` helper, called from `edit_pdf()` in
the same "layer on top" pass as strokes/shapes/highlights/images (text edits still apply first,
per the existing ordering). It:

1. Converts `x/y/width/height` fractions to a raw-space `fitz.Rect`, the same fraction→raw
   conversion image placement already does.
2. Word-wraps `text` into lines that fit the box width via greedy accumulation against
   `fitz.get_text_length()`, per finding #2 above.
3. Inserts each line with `page.insert_text()`, positioned by `align` (via each line's own
   measured width) and stacked by `size * 1.2` line height, using the same `_base14_alias()`
   family/bold/italic lookup `text_edit` already uses.
4. When `underline` is set, draws a line under each line of text via `page.draw_line()`, sized to
   that line's own measured width, per finding #1 above.
5. Stops drawing once past the box's bottom edge (overflow — see Scope decisions).

**Validation**, up front in the same pass as every other element type, before any page is touched:
position/size fractions bounded like `image` elements; `text.strip()` non-empty (matching
Watermark's existing empty-text rejection); `color` a valid hex (reusing `_hex_to_rgb`); `family`
one of the three supported names; `align` one of the three supported values.

No new backend routes — this rides entirely on the existing `POST /tools/edit-pdf` endpoint and
its existing discriminated-union `EditElement` Pydantic model (gets a new `NewTextElement` member).

### Frontend

`EditPdfCanvas.jsx` gets a sixth mode, "Add Text," in the existing mode switcher.

- **Placing:** clicking the canvas in Add Text mode drops a default-size box (e.g. 25% page width
  × a height sized for ~2 lines at the default font size, mirroring Insert Image's 25%-width
  default) at the click point, and immediately opens its inline editor: a `<textarea>` plus a
  styling strip (family dropdown, size field, Bold/Italic/Underline toggle buttons, color swatch,
  alignment buttons) positioned on/near the box. Typing live-updates the box's rendered preview.
- **Confirming:** clicking outside the editor commits it as a `new_text` element, unless the text
  area is empty, in which case the placement is discarded.
- **Editing shortcuts while the editor is focused:** Ctrl+B/I/U toggle the same three booleans the
  toolbar buttons control (see Scope decisions).
- **After placement:** rendered and interacted with exactly like an `image` element — single click
  selects (outline, corner resize handles, body-drag reposition, enables copy/cut), double-click
  reopens the inline editor pre-filled with current text/styling.
- **Removal:** the same × button at its bounding box every other element type already uses.
- **Undo/redo:** placement, edits, moves, and resizes each push one snapshot onto the existing
  `history` stack — no new mechanism.
- **Run button / request body:** no change — `new_text` elements ride along in the existing
  `elements` array Run already sends.

`toolConfigs.js` needs no changes — this is a new mode within the existing `edit-pdf` tool entry,
not a new tool.

## Error handling

- `edit_pdf`: `new_text` elements validated in the same up-front pass as every other element type
  (position/size fractions, non-empty text, valid hex color, valid family/align) — a `PDFError` on
  any invalid one leaves no partially-edited output, the same guarantee the tool already gives.
- Frontend: an empty-text placement is silently discarded — nothing was ever queued, so no error
  banner is needed.

## Testing

- `tests/test_pdf_ops.py`: `_apply_new_text`/`edit_pdf` with a `new_text` element — single-line and
  wrapped multi-line cases (asserting actual extracted text and line count), each of the 3 font
  families × bold/italic combinations, underline rendering (asserting a line-drawing object exists
  at the expected position, per finding #1/#2 above), each alignment value (asserting measured
  line x-position), overflow (text taller than the box doesn't error — later lines are simply
  absent from the output), and invalid inputs (empty text, bad color, bad family/align,
  out-of-bounds rect) each rejected before any page is modified.
- `tests/web/test_tools_edit_convert.py`: the existing mixed-element success-case test extended to
  include one `new_text` element.
- No new frontend test infrastructure — manual browser verification at the end of implementation,
  per this project's established convention: place a box, type and style it, confirm the live
  preview matches; resize and confirm reflow; move it; double-click to re-edit; copy/cut/paste it;
  undo/redo through several steps; Ctrl+B/I/U while editing; Run and confirm the output actually
  contains the styled, wrapped, underlined text at the right position.

## Out of scope

- Any font beyond the existing base-14 trio (Helvetica/Times/Courier) — matching Edit Text's
  existing constraint, no new font-loading machinery.
- Auto-shrink-to-fit for overflow (Edit Text's approach) — resizing the box is the escape hatch
  here instead, since unlike Edit Text there's no "original run size" to preserve.
- Rich/partial styling within one box (e.g. bolding a single word mid-sentence) — the whole box
  shares one style, consistent with every other element type in this tool having one uniform
  style.
- Background fill or border on the text box itself — pure text (plus optional underline) over
  whatever's already on the page, no highlight-style translucent rect.

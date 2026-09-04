# Edit PDF: Partial Mid-Run Text Styling — Design

**Status:** Approved by user 2026-09-04.

## Context

Fifth and last of five sub-projects from a larger feedback batch (see the decomposition in
`docs/superpowers/specs/2026-09-04-pdf-editor-page-scroll-viewer-design.md`'s Context section).
The user wants to select part of a line of text (e.g. one word) and style just that part
differently from the rest of the same line — distinct from Sub-project 4 (real-time inline
editing of a whole run) and from Add Text's own explicit out-of-scope decision on rich/partial
styling for freely-placed text boxes. This is the most technically demanding of the five: it
requires the `text_edit` element to hold more than one style per run, and a selection-driven way
to apply a style to only part of a line.

This sub-project directly builds on Sub-project 4's inline editor and depends on it being
implemented first — its data model change (single `text`/`font_override` → a list of styled
segments) extends what Sub-project 4 ships.

## Scope decisions (from brainstorming)

- **Character-level selection** (drag to select any range, not just whole words) — full free-form
  precision, chosen over word-level-only selection.
- **A two-phase interaction, not one continuous rich-text surface**: typing/committing the base
  text stays exactly as Sub-project 4 built it (a plain single-style `<input>`); styling a
  selection is a separate step that only ever acts on already-typed, static text. This avoids the
  hard, failure-prone problem of keeping a structured "which characters have which style" model
  perfectly synced with a live-editable surface while the user is actively typing — selection-driven
  styling only ever computes a character range once, against text that isn't changing underneath
  it.
- **Auto-shrink-to-fit applies to the whole line as one unit** — if multiple differently-sized
  segments together overflow the original run's width, every segment's size shrinks by the same
  proportional factor (not independently), preserving relative size differences between segments.

## Architecture

### Data model

`text_edit` elements move from a single `text` + `font_override` pair to an ordered list of styled
segments:

```python
{
    "type": "text_edit", "page": int, "run_index": int,
    "segments": [{"text": str, "family": str, "bold": bool, "italic": bool, "size": float}, ...],
}
```

concatenating all segments' `text` in order produces the full replacement line. A run with no
partial styling is simply a one-segment list — this fully subsumes today's single-style behavior
rather than maintaining two parallel formats side by side.

### Backend rendering

`_apply_text_edit` redacts the original run exactly as it does today, then inserts each segment
side-by-side on the same baseline: each segment's X position is the cumulative measured width
(`fitz.get_text_length`, the same primitive already used for auto-shrink) of every segment before
it. If the segments' combined width overflows the original run's width, every segment's size
shrinks by the same proportional factor together — not clamped independently — so a segment that
was already larger/smaller than its neighbors keeps that same relative difference after shrinking.

### Frontend selection & styling

Once text is typed and committed via Sub-project 4's inline `<input>`, a read-only rendering of
that same text — as adjacent styled `<span>`s built from the current `segments` list — becomes
drag-selectable using the browser's native text selection. A small floating popover appears near
an active selection (styled similarly to Google Docs'/Medium's inline-formatting popover) offering
family/bold/italic/size controls; applying one computes the selection's character range against
the current segment list, splits whichever segment(s) that range overlaps at the exact character
boundary, and restyles only the newly-split segment(s) covering the selected text — every other
segment on the line is untouched.

## Testing

- `tests/test_pdf_ops.py`: `_apply_text_edit`/`edit_pdf` given a multi-segment `text_edit` places
  each segment at its own correct style and X position — verified via `get_text("dict")` spans
  (multiple spans, each with the expected `font`/`flags` for its segment, concatenating back to
  the full original line text, each positioned at the expected cumulative offset from the
  previous). Combined-overflow shrink is verified by comparing the *ratio* between two segments'
  sizes before and after shrinking (not just that both got smaller) — confirming the proportional,
  not independent, shrink behavior.
- No frontend automated tests (established convention) — manual verification: selecting part of a
  line and applying a style affects only that part; the rest of the line keeps its own prior
  style(s) untouched; a long multi-styled line overflowing its box shrinks as one visually
  proportional unit; the downloaded output matches what the editor's preview showed.

## Out of scope

- Typing/committing the base text itself, or anything about Edit Text's overall interaction model
  — that's Sub-project 4, which this sub-project depends on and extends.
- Selection/styling that spans across multiple runs at once (one line/run at a time, matching how
  every other Edit PDF interaction in this tool already scopes to one run or one element).

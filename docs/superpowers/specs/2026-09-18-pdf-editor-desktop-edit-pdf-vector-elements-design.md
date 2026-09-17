# Desktop App: Edit PDF, Phase 6B (Vector Elements) — Design

**Status:** Approved by user 2026-09-18.

## Context

Phase 6B of Edit PDF, sub-project 6 (the last of the 6 "hard" desktop
tools). Builds directly on Phase 6A's already-designed (not yet built)
`EditElementsModel`/`EditPageWidget` canvas foundation — this phase adds no
new architecture, only three new element-type branches to that same
per-type dispatch, plus new `QPainter` vector-rendering logic none of the
five existing widgets in `app/ui/widgets.py` do today (they either paint a
single hard-coded box style, blit a bitmap, or overlay real Qt input
widgets — none draw shapes/polylines/translucent fills). As with every
prior sub-project, `app/core/pdf_ops.py`'s core functions for all three
types are already fully implemented and battle-tested — confirmed exact
line numbers below — so this remains a pure desktop-UI build.

## Element types

### `shape`

`{page, shape, x0, y0, x1, y1, color, width, filled}` — identical to the
web's `ShapeElement`. `shape` is one of `rectangle`/`ellipse`/`line`/
`arrow` (validated against the core's own `_SHAPE_TYPES` set,
`app/core/pdf_ops.py:537` — not a Pydantic enum on the web side either, so
the desktop dialog validates the same way: check membership before
calling `edit_pdf`, let the core's own `_validate_shape` at line 564 be the
final word). `x0,y0,x1,y1` are the raw drag-start/drag-end points in
page-fraction space, **not normalized** — min/max only happens at
render/apply time (matching the web exactly, and matching
`_apply_shape`'s own use of `fitz.Rect(...).normalize()` at apply time,
line 705). `width` is a point stroke-width (not a fraction) drawn from the
same three presets the web uses (`thin=1, medium=3, thick=6`). `filled`
only applies to rectangle/ellipse; line/arrow ignore it (an arrow's head is
always solid-filled regardless).

**Interaction:** drag-to-create, gated by the same minimum-drag threshold
already established in 6A — for rectangle/ellipse both axes must clear it;
for line/arrow, only one axis needs to (so a perfectly horizontal or
vertical line/arrow is valid, matching the web's own per-shape-type gating
logic exactly). One resize handle, which always drags `x1,y1` while
`x0,y0` stay fixed — i.e. resize always pivots off the *opposite* corner
from wherever the single handle happens to be drawn (bottom-right, by
convention), not "nearest corner" logic. Move = whole-element drag. Delete
= marker button, matching 6A's convention.

**Rendering:** rectangle/ellipse/line map directly to `QPainter`'s own
`drawRect`/`drawEllipse`/`drawLine`. Arrow needs a client-side port of
`_apply_shape`'s arrowhead math (`_draw_arrow`, line 693 — `atan2`/`cos`/
`sin` trigonometry computing a filled triangular head) purely for the
on-screen live preview; the actual PDF export still goes through the
existing, unchanged `_apply_shape`/`_draw_arrow`, so this port only needs
to look reasonably like an arrow on screen, not byte-for-byte match the
export's exact geometry.

Commits via the existing, unchanged `_apply_shape` (line 705) — validated
first by the existing, unchanged `_validate_shape` (line 564, plus the
`_SHAPE_TYPES` membership check).

### `stroke` (freehand draw)

`{page, points: [{x, y}, ...], color, width}` — identical to the web's
`StrokeElement`/`StrokePoint`. `points` is the raw, unthrottled,
unsimplified sequence of every mouse-move sample captured while the button
is held down, in page-fraction space, in order.

**Interaction:** mousedown begins capture; every subsequent mouse-move
while the button is held appends a point. On release: discarded outright
if fewer than 2 points were captured; otherwise the point cloud's own x/y
*extent* (not point count) must clear the minimum-drag threshold on both
axes, or it's discarded as a "click with jitter," matching the web exactly.
**No resize handle at all** post-creation (matching the web — you cannot
resize a freehand stroke, only move or delete it). Delete = marker button.

**Rendering:** a `QPainterPath` built by moving to the first point and
lining to every subsequent one, stroked with a `QPen` of the element's
color/width — the direct Qt equivalent of the core's own
`page.new_shape().draw_polyline(...)`. A degenerate 1-point stroke (which
the core's `_apply_stroke`, line 667, expands into a tiny 2-point line
rather than choking on) is handled the same way client-side for the
live-preview case, though in practice the 2-point minimum-capture rule
above means this only matters for a defensive edge case, not normal use.

Commits via the existing, unchanged `_apply_stroke` (line 667) — validated
first by the existing, unchanged `_validate_stroke` (line 555).

### `highlight`

`{page, top, left, right, bottom, color}` — identical to the web's
`HighlightElement`, and using the **inset-from-edges convention** (not
x/y/width/height) — the same convention Crop/Redact's boxes already use
elsewhere in this app (`box_to_insets`/`insets_to_box` in
`app/ui/widgets.py`), so `top`/`left` are the box's own top-left inset,
while `right`/`bottom` are literally "space remaining" on those far edges
(`1 - x1`, `1 - y1`) — a detail that matters for the clipboard's
paste-offset math below. No fill-opacity field: opacity (0.4) is hardcoded
server-side in `_apply_highlight` (line 728), matching the web exactly.

**Interaction:** drag-to-create a rectangular region (both axes must clear
the minimum-drag threshold, matching the web); the two raw drag corners are
sorted (`min`/`max`) into the inset form at commit, reusing
`box_to_insets` directly. One resize handle, anchored top-left — dragging
it only ever changes the `right`/`bottom` insets (recomputed from the new
width/height), `left`/`top` stay fixed. This is a materially different
resize behavior from `shape`'s "always drags the opposite corner from
wherever the handle sits" — `highlight`'s handle is always bottom-right,
period, matching the web's own `lockAspect: false` resize-from-bottom-right
mode for this type specifically.

**Rendering:** a single `QPainter.fillRect` with the element's color at
0.4 alpha — Qt's native alpha channel (`QColor.setAlphaF`) handles this
directly, cleaner than the web's own hex-suffix hack (`HIGHLIGHT_ALPHA_HEX
= "66"`), which exists there only because CSS `opacity` would also fade
the highlight's own delete button (a stacking-context problem that doesn't
exist in a single `QPainter`-drawn canvas, since the marker button isn't a
separate DOM/CSS-opacity-affected child here).

Commits via the existing, unchanged `_apply_highlight` (line 728) —
validated first by the existing, unchanged `_validate_highlight` (line
577).

## Toolbar changes

The "active creation mode" toggle from 6A (a 2-way New Text/Insert Image
choice) extends to a 5-way selector: New Text, Insert Image, Draw, Shapes,
Highlight — exactly one active at a time, same as 6A. Each of the three new
modes gets its own small option row, shown only while that mode is active:
Draw (color swatches + width preset), Shapes (shape-type selector +
color + width preset + filled checkbox), Highlight (color swatches only).

## Shared interaction extensions

`EditElementsModel`'s clipboard paste-offset logic (`Shared Interaction`
in 6A's spec) gains one new per-type branch for each of these three types,
mirroring the web's own per-convention `shift()` logic exactly:

- `shape` (`x0,y0,x1,y1`): shift by however much room is left before
  hitting `1` on whichever corner is the "max" one for each axis (mirrors
  `new_text`/`image`'s own `x+width`-vs-`1` room calculation from 6A,
  adapted to raw corner points instead of `x,width`).
- `stroke` (`points`): shift by the room left before the point cloud's own
  max x/y across every point.
- `highlight` (`top/left/right/bottom` insets): shift using the `right`/
  `bottom` insets *directly* as the "remaining room" value — this is the
  one type where the stored fields already ARE the remaining-room
  quantity, so no separate max-corner calculation is needed at all, unlike
  every other type.

Every axis's shift is independently clamped to `[0, 0.03]` (the same
`OFFSET` constant 6A establishes) — translating the *whole* element by the
same delta on each axis, never clamping per-coordinate independently
(the web's own explicit rationale: independent-coordinate clamping would
distort/shrink a near-edge element, and would make `highlight`'s inverted
insets go negative and fail the core's own validation).

Undo/redo, keyboard nudge, delete, and z-order reordering need no
type-specific changes at all — `EditElementsModel`'s existing generic
`nudge`/`reorder`/`remove`/`commit` methods from 6A already operate on
whichever element is selected regardless of type.

## Testing

Following the same convention: `EditPageWidget` gets synthetic-mouse-event
tests for each new type's create/move/resize(-or-not, for stroke)/delete,
plus the arrow-specific "only one axis needs to clear the drag threshold"
case and the highlight-specific "resize only changes right/bottom insets"
case. `EditElementsModel` gets the three new clipboard-offset branches
tested directly, including the near-edge clamping case for each. An
end-to-end `EditPdfDialog` test builds a real multi-page fixture, places
one of each of the three new types, exports, and verifies via `fitz` that
a rectangle/line/arrow, a freehand stroke, and a translucent highlight all
genuinely appear in the real output PDF (a pixel-render diff against an
unedited control, matching the rigor `tests/test_pdf_ops.py`'s own existing
shape/stroke/highlight core-level tests already use for verifying visual
output that isn't literal extractable text).

## Out of scope

- `text_edit` in-place editing (Phase 6C) — its own future brainstorm,
  deliberately last.
- Any change to `app/core/pdf_ops.py`'s `_apply_shape`/`_apply_stroke`/
  `_apply_highlight`/`_validate_shape`/`_validate_stroke`/
  `_validate_highlight`, or to the web app's own `EditPdfCanvas.jsx`/
  `edit-pdf` route — all already exist, already tested, and need no
  changes.

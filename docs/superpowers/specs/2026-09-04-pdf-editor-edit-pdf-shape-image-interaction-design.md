# Edit PDF: Shape/Image Interaction & Z-Order — Design

**Status:** Approved by user 2026-09-04.

## Context

Third of five sub-projects from a larger feedback batch (see the decomposition in
`docs/superpowers/specs/2026-09-04-pdf-editor-page-scroll-viewer-design.md`'s Context section).
This groups together a cluster of related Edit PDF interaction gaps and bugs: elements other than
`image`/`new_text` can't be moved after insertion, shapes only respond to clicks on their thin
outline rather than anywhere inside them, there's no way to restyle an already-placed element in
real time, no z-order controls exist for overlapping elements, Insert Image shows a blank box until
the file is run and downloaded, image resizing is always proportional (no independent width/height
control), inserted images don't match the proportions of the box drawn for them, and Add Text
boxes can be resized smaller than the text they contain.

## Key technical findings (verified empirically/via code reading before finalizing this design)

1. **Line vs Arrow already look different in the final output — only the live editor preview is
   the gap.** `EditPdfCanvas.jsx`'s SVG preview renders both shape types as a plain `<line>`; the
   actual arrowhead is only drawn server-side by `_apply_shape`/`_draw_arrow`. This is a
   preview-only gap, not a backend rendering bug.
2. **Insert Image's "blank box" is a genuine missing feature, not a bug in image handling.** The
   `image` element's rendered box (`EditPdfCanvas.jsx`) never includes an `<img>` tag — only a
   dashed border, a resize handle, and a remove button. The uploaded file is already reachable via
   the app's existing `downloadUrl(fileId)` (serves the raw uploaded file), so this is a
   straightforward addition, no new backend endpoint needed.
3. **The image aspect-ratio mismatch traced to a specific formula bug.** `handleImageFileSelected`
   computes `height = width * (naturalSize.height / naturalSize.width)` — both `width` and the
   result `height` are *fractions of the page*, but this formula only produces the image's true
   proportions if the page itself is square. On a normal (non-square) page, the resulting box's
   proportions don't match the image's real proportions. `page.insert_image()`'s default
   `keep_proportion=True` (confirmed via `inspect.signature`) then correctly preserves the image's
   *true* aspect ratio when placing it — auto-fitting within whatever (incorrectly-proportioned)
   rect it's given — so the box drawn in the editor and the image actually placed disagree, which
   is exactly the "chosen vs. inserted size differs, appeared longer horizontally" symptom
   described.
4. **Z-order needs no backend change at all.** `edit_pdf`'s apply loop already iterates
   `other_elements` in the order they appear in the `elements` array — whatever order the array
   holds is already the paint order server-side. The only reason z-order doesn't work today is
   that the *frontend* renders elements grouped by type (all strokes, then all shapes, then
   highlights, then images, then text) rather than interleaved in array order, so an element's
   actual array position currently has no visible effect on what's drawn on top of what.

## Scope decisions (from brainstorming)

- **Click-anywhere-to-select, drag-to-move, and z-order apply to every element type** — strokes
  and highlights get the same treatment as shapes/images/text, not just the types explicitly
  called out, for a consistent experience across the whole tool.
- **Resize is not offered for strokes** — freehand ink doesn't have a natural "resize" affordance;
  strokes get select + move only. Every other type (shape, highlight, image, text) gets resize.
- **Restyling a selected element reuses the existing mode style-bars**, given a second meaning:
  with nothing selected, the controls set the default for the next *new* element (today's
  behavior, unchanged); with an element selected, the same controls instead reflect and live-edit
  *that element's* current style. No new UI surface — the existing color/width/fill controls
  become dual-purpose.
- **Image resize gets three handles**: the existing corner handle (proportional, unchanged), plus
  a new right-edge handle (width-only) and bottom-edge handle (height-only) — matching the
  standard corner-vs-edge resize convention from tools like PowerPoint/Word.
- **Multi-select is out of scope** — one element selected/restyled/reordered at a time, matching
  the existing single-`selectedId` model everywhere else in this tool.

## Architecture

### Unified selection, hit-testing, and movement

- Every element type gets a computed bounding box: shapes (`x0/y0/x1/y1`) and highlights
  (`top/left/right/bottom`) already have one implicitly; strokes get one computed from the min/max
  of their points (already used today just for positioning the remove button).
- A transparent hit-test overlay, sized to that bounding box, sits on top of each element's actual
  visual (SVG polyline/shape or a plain div) — this is what makes "click anywhere inside" work for
  shapes (SVG's default hit-testing only responds to a painted area; an unfilled shape's interior
  isn't painted), and gives every element type the same click/drag target regardless of how it's
  actually drawn.
- Move/resize reuses the generalized drag machinery Add Text's implementation already built
  (`startElementDrag`/`handleElementDragMove`/`handleElementDragEnd`, with per-type options like
  `lockAspect`) — extended from image/text-only to strokes (move only)/shapes/highlights too.
  Moving a stroke translates every one of its points together by the same offset.

### Real-time restyling

When an element is selected, its mode's style-bar controls (color/width for Draw & Shapes, the
fill toggle for Rectangle/Ellipse, color for Highlight) read from and write to that specific
element's current style instead of the "next new element" defaults. Selecting nothing reverts the
controls to their existing default-setting behavior.

### Z-order

Rendering restructures from "group all elements of one type into one shared block" to **one
interleaved list per page, in `elements` array order** — every element (regardless of type)
becomes its own positioned layer in that single ordered list, rather than being routed into a
type-specific SVG/div block. Four new controls (bring to front / send to back / forward /
backward) reorder the selected element within that array: front moves it to the end, back to the
start, forward/backward swap it with its immediate neighbor. No backend change — `edit_pdf`
already respects array order (finding #4 above).

### Image fixes

- **Visible preview**: an `<img src={downloadUrl(el.file_id)} />` renders inside the image
  element's box, replacing the current empty dashed placeholder.
- **Correct default proportions**: the default-size computation (on first placement) accounts for
  the rendered page container's own pixel dimensions (read from its DOM bounding box, not assumed
  square), so the drawn box's fraction proportions genuinely match the image's real pixel
  proportions from the moment it's placed.
- **Independent resize, WYSIWYG export**: with the box now starting correctly proportioned, the
  backend stops relying on `insert_image`'s `keep_proportion=True` auto-fit (which could silently
  override an intentional non-proportional resize) and instead calls it with
  `keep_proportion=False`, placing the image into exactly the given rect fractions every time —
  guaranteeing the exported result matches what the box showed in the editor, whether resized
  proportionally (corner handle) or independently (edge handles).

### Add Text minimum-size validation

The resize handle refuses to shrink an Add Text box below the space its current text actually
needs at its current font size and wrapping — measured with the same line-wrapping/width logic
`_apply_new_text` already uses server-side, so the frontend's "too small" check agrees with what
the backend would actually need to render the text without truncation.

## Testing

- `tests/test_pdf_ops.py`: `_apply_image` called with `keep_proportion=False` places the image at
  exactly the given rect's corners (verified via pixel sampling at those exact corners, not
  wherever PyMuPDF's own auto-fit would otherwise center/letterbox it).
- No frontend automated tests (established convention) — manual verification at the end of
  implementation: Line and Arrow are visually distinct while drawing (not just after export);
  every element type (stroke/shape/highlight/image/text) is click-anywhere-to-select and
  drag-to-move (strokes: select+move only, no resize); a selected shape's style-bar controls edit
  it live; the four z-order buttons visibly reorder overlapping elements; the image preview shows
  the actual picture immediately on placement, not just after Run; each of an image's three resize
  handles behaves as expected (proportional / width-only / height-only); a downloaded
  image-containing export matches what the editor showed, for both proportional and
  independently-resized images; Add Text's resize handle refuses to shrink below the current
  text's footprint.

## Out of scope

- Resize for strokes (move-only, per Scope decisions above).
- Multi-select (one element at a time, matching the existing model).
- Any change to Add Text's own placement/editing flow (covered by a separate sub-project) beyond
  the minimum-size validation described here.

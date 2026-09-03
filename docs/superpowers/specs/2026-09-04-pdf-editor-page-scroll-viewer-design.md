# Page-Viewer Overhaul: `PageScrollViewer` — Design

**Status:** Approved by user 2026-09-04.

## Context

After using the shipped Phase 2 features, the user gave a large batch of feedback spanning three
areas: Add Watermark controls, a cluster of Edit PDF interaction bugs/requests, and a Recent Files
preview request. That feedback was too large for one spec — see the decomposition agreed with the
user — and was split into five sub-projects. This is the first and most foundational: every one of
the other sub-projects either depends on, or explicitly asked for, the same underlying change —
"if other pages have use these features as well, apply the changes to those part as well."

Today, four tools (`EditPdfCanvas.jsx`, `FormFillCanvas.jsx`, `SignCanvas.jsx`,
`RedactSelector.jsx`) each independently implement the same pattern: one page rendered at a time
via `thumbnailUrl(fileId, currentPage, maxSize)`, a `currentPage` state variable, and
Previous/Next buttons with a "Page X of Y" label. The user's feedback: this makes the content look
small and blurry (the whole app is capped at `max-width: 1080px`, and thumbnails render at only
700px), and paging through one screen at a time makes it hard to review edits across a document.
Recent Files currently has no content preview at all.

## Scope decisions (from brainstorming)

- **A single shared component, `PageScrollViewer`**, replaces the duplicated single-page-plus-
  pagination pattern in all four existing tools, and becomes the new Recent Files preview too —
  not five separate implementations of the same scroll/jump/track behavior.
- **Continuous vertical scroll** — every page renders stacked top-to-bottom, replacing
  Previous/Next pagination in all five consumers.
- **"Page X of Y" auto-tracks scroll position** via an `IntersectionObserver` (whichever page has
  the most visible area updates X), and **X is directly editable** — click the number, type, Enter
  scrolls that page into view.
- **The toolbar (mode switcher) centers** in the new, wider layout.
- **Wider, sharper rendering**: a dedicated wider container (not the app-wide 1080px cap, which
  stays as-is for unrelated pages) plus a bumped thumbnail resolution request.
- **"Which page" becomes implicit from where you click or drag**, not a pre-selected `currentPage`
  — the same interaction model a continuous-scroll document editor (e.g. Google Docs) already
  uses. This replaces each tool's own `currentPage`-gated placement logic.
- **All pages render eagerly** (no virtualization) — a stated, explicit scope boundary for this
  pass, acceptable for the modest document sizes this app targets; revisit only if it becomes a
  real problem.

## Architecture

### `PageScrollViewer` (new shared component)

- Renders every page of the current file stacked vertically in one scrollable container, each
  page an `<img>` at the bumped resolution (see below), wrapped in its own per-page positioning
  container (own ref, own bounding box) — necessary because, unlike today's single shared
  `stageRef`, a click/drag's fraction must now be computed relative to the SPECIFIC page it
  landed on.
- **Header bar** (not per-page): "Page `[X]` of `Y`", sitting above the scroll area. `X` is an
  editable field; Enter scrolls that page into view. `Y` is the document's page count.
- **Scroll-tracking**: an `IntersectionObserver` watches every page container; the page with the
  most visible area drives `X`.
- **Tool-agnostic via a render prop**: `PageScrollViewer` takes `renderPageOverlay={(pageNumber,
  pageRef) => <...>}`, called once per mounted page. `PageScrollViewer` itself knows nothing about
  shapes, form fields, or signatures — only pages, scroll, and layout. `pageRef` (or an equivalent
  "resolve a point within this page" helper) is how a consuming tool computes click/drag fractions
  relative to that specific page, replacing today's single global `stageRef`.
- Read-only consumers (Recent Files) simply omit `renderPageOverlay`.

### Per-tool integration

The interaction-model shift — "which page" comes from where you act, not a pre-selected page —
means each tool's placement/drawing logic moves from being gated on a single `currentPage` to
being scoped to whichever page's `renderPageOverlay(pageNumber, ...)` call the gesture started in:

- **`EditPdfCanvas`**: each page renders its own filtered elements
  (`elements.filter(el => el.page === pageNumber)`) and its own mode-handlers (draw/shape/
  highlight/image/text-box), parameterized by that page's `pageNumber` instead of a shared
  `currentPage`. Only one thing can be "in progress" at once (one active stroke, one open text
  draft, etc.) — that stays single, global state; only *which page* it belongs to is now
  determined by where the gesture started.
- **`FormFillCanvas`**: simplest adaptation — fields are filtered per page
  (`fields.filter(f => f.page === pageNumber)`) and rendered as real controls in place; there's no
  "in-progress placement" concept here to begin with.
- **`SignCanvas`**: placing a signature happens on whichever page is clicked, same pattern as Edit
  PDF's simpler element types.
- **`RedactSelector`**: drag-to-draw a redaction box on whichever page is visible.
- **Recent Files preview**: fully read-only — `PageScrollViewer` with no `renderPageOverlay`, just
  stacked page images, scroll-tracked "Page X of Y," and jump-to-page. This is the first place
  `PageScrollViewer` is used purely for viewing, with no editing tool wrapped around it.

### Layout and rendering

- `PageScrollViewer`'s own container gets a wider max-width (~1400px) than the app-wide
  `.app__main` cap (1080px, unchanged for every other page — the tool grid, the plain file list,
  etc. are not affected).
- Thumbnail requests bump from `max_size=700` to `max_size=1400` for `PageScrollViewer`
  consumers — the backend's existing PyMuPDF pixmap rendering already accepts this parameter, so
  this is a call-site change only, no backend work.
- The mode-switcher toolbar (Edit PDF's Edit Text | Draw | Shapes | Highlight | Insert Image | Add
  Text) centers horizontally within the new wider container.

## Error handling

- **Jump-to-page**: out-of-range or non-numeric input is clamped to the valid `1..Y` range (or
  reverted if not a number at all) rather than surfacing a validation error — this is a navigation
  convenience, not a form.
- **Large documents**: all pages render eagerly; no virtualization in this pass (stated scope
  boundary above, not a silent gap).

## Testing

No automated frontend tests exist in this project (established convention) — verification is
manual, at the end of implementation: scrolling through a multi-page document updates "Page X of
Y" correctly; typing a page number and pressing Enter scrolls there; each of the four interactive
tools (Edit PDF, PDF Forms, Sign, Redact) still works correctly per-page under the new
implicit-page-from-click model (placing/drawing/filling on any visible page, not just one
pre-selected page); Recent Files shows a working read-only scrollable preview; the wider layout
renders sharp instead of blurry at the new resolution; the toolbar is visibly centered.

## Out of scope (for this spec)

- Virtualizing page rendering for very large documents (stated scale limitation above).
- Any change to the app-wide `.app__main` layout or non-`PageScrollViewer` pages.
- The four other sub-projects from this feedback batch (Watermark size/rotation, shape/image
  interaction & z-order fixes, real-time inline text editing, partial mid-run text styling) — each
  gets its own spec, brainstormed separately.

# Edit PDF: Expanded Colors + Delete/Nudge Shortcuts — Design

**Status:** Approved by user 2026-09-12.

## Context

Queued from earlier in this session: the user wanted more colors available for Add Shape
and Add Text — specifically white, to draw an opaque box over unwanted text — plus a
Delete/Backspace shortcut to remove a selected element. When asked what other shortcuts
were worth adding, the assistant suggested undo/redo, duplicate, arrow-key nudge, escape,
and z-order shortcuts, without the user having picked among them yet.

Before proposing anything, `web/frontend/src/components/EditPdfCanvas.jsx` (1893 lines,
touched extensively across earlier Phase 2 sub-projects this session) was read fresh. This
surfaced a significant, previously-unknown-to-this-session finding: **undo/redo (`Ctrl+Z`/
`Ctrl+Y`), copy/cut/paste (`Ctrl+C`/`Ctrl+X`/`Ctrl+V`), and Escape-to-deselect already exist**
in a `handleKeyDown` effect (lines ~415-450) — built in an earlier part of this project's
history the current session summary didn't carry forward. This eliminates most of the
assistant's own earlier suggestions from consideration (already shipped) and narrows this
spec's actual scope to what genuinely doesn't exist yet: Delete/Backspace and arrow-key
nudge.

The backend was also verified before proposing the color work: `app/core/pdf_ops.py`'s
`_hex_to_rgb` already accepts any well-formed 6-digit hex string with no whitelist — the
color expansion is a pure frontend change, no backend validation changes needed. No native
`<input type="color">` exists anywhere in this codebase yet.

## Scope decisions (from brainstorming)

- **A native `<input type="color">` is added to all four color-using tools** (Add Text,
  Draw, Add Shape, Highlight) alongside their existing swatch buttons — zero new
  dependencies (built into every browser), and it produces exactly the `#rrggbb` hex format
  the backend already expects with no conversion needed.
- **White (`#ffffff`) is added as an explicit swatch to `MARKUP_COLORS`** (the array shared
  by Add Text, Draw, and Add Shape) — matching the user's explicit "white as one of them"
  request, giving one-click access without needing the picker for this specific common case.
- **Highlight keeps its own existing 4-color pastel swatch list unchanged** (yellow/green/
  cyan/coral — colors suited to a semi-transparent overlay) but gains the same native color
  picker as the other three tools. White is NOT added as a Highlight swatch (a translucent
  white overlay just looks like a light gray wash, not a meaningful color choice as a
  one-click preset) — but a user who wants it anyway can still dial it in via the picker.
- **The three near-duplicate swatch-row JSX blocks get consolidated** into one small reusable
  piece, since a 4th near-copy for Highlight's picker would otherwise be added on top of the
  three that already exist verbatim in this file.
- **Delete/Backspace removes the selected element** — mirrors the existing `Ctrl+X` code
  path exactly, minus the clipboard-copy step.
- **Arrow keys nudge the selected element by a small step; Shift+Arrow nudges by a larger
  step** — both step sizes are page-fraction based (element coordinates are stored as 0-1
  fractions of the page, not pixel counts, confirmed by reading the existing coordinate
  system), reusing the exact per-element-type coordinate-shift math the existing paste
  feature already has (shapes, highlight insets, image/text-box origin, and freehand stroke
  point arrays each shift correctly today) — clamped so a nudge never pushes an element
  outside the page. `text_edit` elements (in-place edits to existing PDF text, not draggable
  annotations) are excluded, matching the existing exclusion already applied to copy/cut/
  paste for this same element type.
- **Out of scope, queued for a future decision**: making `text_edit` elements themselves
  movable/independently positioned. Currently, editing existing text redacts the original
  text's exact position and inserts the replacement starting from that same anchor — so
  longer replacement text extends visually to the right rather than staying where the user
  might want it. Decoupling "where the old text gets redacted" from "where the new text
  gets placed" is technically feasible but touches both the backend text-insertion logic and
  the frontend's selection/drag model — a real feature, not a small tweak. The user's
  existing white-box-plus-new-text workflow (a filled white shape to cover the old text, a
  fully movable/resizable new text element on top) already solves the same problem today,
  so this is deferred rather than bundled into this pass.

## Architecture

### Colors

`MARKUP_COLORS` (currently `["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5"]`)
gains `"#ffffff"` as a 7th entry.

A new small reusable rendering helper (e.g. a local `renderColorSwatchRow(colors, activeColor,
onPick)` function, or an extracted inline component — implementer's call on the exact shape,
matching this file's existing conventions) replaces the three verbatim-duplicated
`{MARKUP_COLORS.map((c) => (...))}` blocks (Add Text ~line 1410, Draw ~line 1760, Add Shape
~line 1807) and is also used for Highlight's existing 4-color list (~line 1856). Each call
site additionally renders one `<input type="color" value={activeColor} onChange={...} />`
alongside the swatch buttons — its `onChange` calls the exact same color-setting function
each tool already uses for its swatch `onClick` (`updateSelectedElementStyle(...)` when an
element of the matching type is selected, otherwise the tool's own "next new element" default
setter), so a custom-picked color applies identically to how clicking a swatch already does.

### Shortcuts

Both additions go in the existing `handleKeyDown` function (~line 415), following its
established structure (an `isTypingTarget` guard already present, `e.preventDefault()` before
any handled key, checks against `selectedId`):

```javascript
if (!ctrl) {
  if (e.key === "Escape") setSelectedId(null);
  else if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
    e.preventDefault();
    commitElements(elements.filter((el) => el.id !== selectedId));
    setSelectedId(null);
  } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) && selectedId) {
    const el = elements.find((e) => e.id === selectedId);
    if (el && el.type !== "text_edit") {
      e.preventDefault();
      nudgeSelectedElement(el, e.key, e.shiftKey);
    }
  }
  return;
}
```

A new `nudgeSelectedElement(el, key, isBigStep)` function adapts the exact per-element-type
coordinate-shift logic `pasteClipboard`'s `shift`/type-branching already implements (the
`"x0" in base` / `"left" in base` / `"x" in base` / `"points" in base` branches), replacing
paste's fixed diagonal `OFFSET` with a directional delta (`ArrowLeft`/`ArrowRight` move the
x-axis, `ArrowUp`/`ArrowDown` move the y-axis) and a magnitude that depends on `isBigStep`,
clamped to the element's own valid 0-1 range the same way paste's `shift()` helper already
clamps against remaining page space.

## Testing

Frontend-only — no backend changes (colors already validated by `_hex_to_rgb`, no whitelist;
positions already validated by each element type's existing `_validate_*` range checks). No
automated tests, matching this project's established convention for frontend-only work.

Manual checklist: each of the four tools' new native color picker actually applies to the
active/selected element (not just visually shown, but present in the exported PDF); the white
swatch is present in Add Text/Draw/Add Shape's swatch row; a filled white rectangle genuinely
covers text underneath it in the exported PDF; Delete/Backspace removes the currently selected
element and does nothing when nothing is selected; arrow-key nudge moves the selected element
in the correct direction at both step sizes, and stops cleanly at a page edge rather than
pushing the element out of bounds; nudging while a `text_edit` element is selected does
nothing (matching its existing move/copy exclusion).

## Out of scope

- Making `text_edit` elements independently movable/positioned — queued for a future
  decision, see the scope-decisions section above.
- Multi-element selection (nudge/delete only ever apply to the single currently-selected
  element, matching every other existing selection-based operation in this file).
- Any change to Highlight's existing swatch color set — only the native picker is added.

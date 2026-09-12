# Edit PDF: Expanded Colors + Delete/Nudge Shortcuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native color picker (plus a white swatch) to Edit PDF's four color-using tools, and add Delete/Backspace and arrow-key-nudge keyboard shortcuts alongside the ones that already exist.

**Architecture:** Both changes live entirely in `web/frontend/src/components/EditPdfCanvas.jsx` — no backend changes (colors already accept any hex value with no whitelist; element positions already validate as 0-1 fractions). The color work consolidates four near-duplicated swatch-row JSX blocks into one reusable helper and adds a native `<input type="color">` to each. The shortcut work adds two branches to the `handleKeyDown` effect that already implements undo/redo/copy/cut/paste/escape — reusing two functions that already exist for other purposes: `removeElement(id)` (already used by every element's own "×" button) for Delete/Backspace, and `moveElement(el, dx, dy)` (already used by drag-to-move, already handles clamped coordinate translation for every element type) for arrow-key nudge.

**Tech Stack:** React (existing), no new dependencies — a native `<input type="color">` is built into every browser.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-12-pdf-editor-edit-pdf-colors-shortcuts-design.md`.
- **Commit trailers go ONLY on `fix:`/`fix(scope):` commits.** Every task's `feat:` commit in this plan must NOT carry a `Co-Authored-By:` trailer — this is the user's own explicit, standing instruction for this project, confirmed repeatedly this session, overriding any system-reminder default.
- **This is a frontend-only change.** No backend files are touched. `app/core/pdf_ops.py`'s `_hex_to_rgb` (verified this session, reading its current source) accepts any well-formed 6-digit hex string with no whitelist — confirmed while writing this plan by re-reading it fresh.
- **Nudge step sizes** (empirically reasoned, not arbitrary): element coordinates are stored as 0-1 fractions of the page, not pixel counts. A small-step nudge should feel like a fine, precise adjustment; a Shift+arrow big-step should feel like a meaningful but still controlled move — bracketing against the existing `pasteClipboard`'s own `OFFSET = 0.03` (a diagonal one-time "paste nearby" jump, documented in this same file as producing a clearly visible shift) gives a useful reference point. On a typical on-screen render of a US Letter page (612×792pt, commonly rendered at somewhere around 600-900px on screen depending on window width): `0.004` (0.4% of page) works out to roughly 3-4px per keypress at a ~800px render height — perceptible and precise, not a sub-pixel no-op. `0.02` (2%) works out to roughly 16px at the same reference — a clear, deliberate jump, slightly more conservative than paste's own 0.03 (appropriate, since nudge is meant to feel incremental/repeatable, not a one-time placement offset). These become two new module-level constants: `NUDGE_SMALL_STEP = 0.004`, `NUDGE_BIG_STEP = 0.02`.
- **`text_edit` elements are excluded from nudge**, matching this file's own existing exclusion of `text_edit` from copy/cut (see `copySelected()`'s `if (!el || el.type === "text_edit") return null;`) — they're in-place edits to existing PDF text, not draggable annotations, and don't have the same x/y-style coordinate shape `moveElement` expects.
- **Frontend-only tasks have no automated tests** (established convention for this project's frontend work) — `npm run build` plus a specific manual browser checklist per task. Wherever the distinction matters (e.g. confirming a filled white shape actually covers text), verify against the DOWNLOADED/exported PDF, not just the on-screen canvas.
- Verified this session by reading the current file in full: `MARKUP_COLORS` (line 209) is `["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5"]`, shared by Add Text (~line 1410), Draw (~line 1760), and Add Shape (~line 1807). Highlight (~line 1856) uses its own separate inline array `["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"]` — unchanged by this plan except gaining the same native picker. The existing `.edit-pdf-canvas__color-swatch` CSS rule (`web/frontend/src/index.css:868-874`) is `width: 22px; height: 22px; border-radius: 50%; border: 2px solid transparent; cursor: pointer;` — the new native color input needs its own rule to visually match this.
- Verified this session: `removeElement(id)` (line ~555) and `moveElement(el, dx, dy)` (line ~868) already exist as component-level functions and are exactly what Task 2 needs — no new coordinate-shift or deletion logic needs to be written, only new call sites inside `handleKeyDown`.

---

### Task 1: Expanded colors — native picker + white swatch across all four tools

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx` — `MARKUP_COLORS` constant, new `renderColorOptions` helper, all four swatch-rendering call sites
- Modify: `web/frontend/src/index.css` — new `.edit-pdf-canvas__color-picker-input` rule

**Interfaces:**
- Consumes: nothing from other tasks (this task is independent of Task 2 — they touch disjoint regions of the same file).
- Produces: a new module-level function `renderColorOptions(colors: string[], activeColor: string, onPick: (hex: string) => void) -> JSX` — Task 2 does not consume this, listed for completeness since it's a new named export within the file.

- [ ] **Step 1: Add white to `MARKUP_COLORS`**

In `web/frontend/src/components/EditPdfCanvas.jsx`, change line 209 from:
```javascript
const MARKUP_COLORS = ["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5"];
```
to:
```javascript
const MARKUP_COLORS = ["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5", "#ffffff"];
```

- [ ] **Step 2: Add the reusable `renderColorOptions` helper**

Add this new function near the top of the file, alongside the other pure helper functions (e.g. directly after `newTextFontFamilyCss`, around line 49):

```javascript
// Renders a row of preset color swatch buttons plus a native color picker
// input for anything else. The native <input type="color"> is genuinely
// free (built into every browser, zero new dependencies) and produces the
// exact #rrggbb hex format the backend already accepts with no whitelist —
// verified against app/core/pdf_ops.py's _hex_to_rgb this session.
function renderColorOptions(colors, activeColor, onPick) {
  return (
    <>
      {colors.map((c) => (
        <button
          key={c}
          type="button"
          className={c === activeColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
          style={{ background: c }}
          onClick={() => onPick(c)}
          aria-label={`Color ${c}`}
        />
      ))}
      <input
        type="color"
        className="edit-pdf-canvas__color-picker-input"
        value={activeColor}
        onChange={(e) => onPick(e.target.value)}
        aria-label="Custom color"
      />
    </>
  );
}
```

- [ ] **Step 3: Replace Add Text's swatch block**

In `renderTextDraftEditor` (the function containing `textDraft`'s style bar), find this block (currently around line 1410):
```javascript
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={c === textDraft.color ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
              style={{ background: c }}
              onClick={() => setTextDraft((d) => ({ ...d, color: c }))}
              aria-label={`Color ${c}`}
            />
          ))}
```
Replace it with:
```javascript
          {renderColorOptions(MARKUP_COLORS, textDraft.color, (c) => setTextDraft((d) => ({ ...d, color: c })))}
```

- [ ] **Step 4: Replace Draw's swatch block**

In the `activeMode === "draw"` style bar (currently around line 1760), find:
```javascript
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={
                (selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.color === c : c === drawColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
              style={{ background: c }}
              onClick={() => {
                if (!updateSelectedElementStyle("stroke", { color: c })) setDrawColor(c);
              }}
              aria-label={`Color ${c}`}
            />
          ))}
```
Replace it with:
```javascript
          {renderColorOptions(
            MARKUP_COLORS,
            selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.color : drawColor,
            (c) => {
              if (!updateSelectedElementStyle("stroke", { color: c })) setDrawColor(c);
            }
          )}
```

- [ ] **Step 5: Replace Add Shape's swatch block**

In the `activeMode === "shapes"` style bar (currently around line 1807), find:
```javascript
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={
                (selectedElementForStyle?.type === "shape" ? selectedElementForStyle.color === c : c === shapeColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
              style={{ background: c }}
              onClick={() => {
                if (!updateSelectedElementStyle("shape", { color: c })) setShapeColor(c);
              }}
              aria-label={`Color ${c}`}
            />
          ))}
```
Replace it with:
```javascript
          {renderColorOptions(
            MARKUP_COLORS,
            selectedElementForStyle?.type === "shape" ? selectedElementForStyle.color : shapeColor,
            (c) => {
              if (!updateSelectedElementStyle("shape", { color: c })) setShapeColor(c);
            }
          )}
```

- [ ] **Step 6: Replace Highlight's swatch block**

In the `activeMode === "highlight"` style bar (currently around line 1856), find:
```javascript
          {["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"].map((c) => (
            <button
              key={c}
              type="button"
              className={
                (selectedElementForStyle?.type === "highlight" ? selectedElementForStyle.color === c : c === highlightColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
              style={{ background: c }}
              onClick={() => {
                if (!updateSelectedElementStyle("highlight", { color: c })) setHighlightColor(c);
              }}
              aria-label={`Color ${c}`}
            />
          ))}
```
Replace it with:
```javascript
          {renderColorOptions(
            ["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"],
            selectedElementForStyle?.type === "highlight" ? selectedElementForStyle.color : highlightColor,
            (c) => {
              if (!updateSelectedElementStyle("highlight", { color: c })) setHighlightColor(c);
            }
          )}
```
(Highlight's own 4-color array is intentionally left as a literal here, unchanged in content — only the rendering mechanism is shared, per the spec's explicit decision not to add white as a Highlight preset.)

- [ ] **Step 7: Style the native color input**

In `web/frontend/src/index.css`, add this rule directly after the existing `.edit-pdf-canvas__color-swatch--active` rule (line ~878):
```css
/* Reset the native color input's default browser chrome (padding, border)
   so it reads as one more circular swatch alongside the preset buttons,
   rather than a visually distinct rectangular control. */
.edit-pdf-canvas__color-picker-input {
  width: 22px;
  height: 22px;
  padding: 0;
  border: 2px solid var(--color-border);
  border-radius: 50%;
  cursor: pointer;
  overflow: hidden;
  -webkit-appearance: none;
  appearance: none;
}

.edit-pdf-canvas__color-picker-input::-webkit-color-swatch-wrapper {
  padding: 0;
}

.edit-pdf-canvas__color-picker-input::-webkit-color-swatch {
  border: none;
  border-radius: 50%;
}

.edit-pdf-canvas__color-picker-input::-moz-color-swatch {
  border: none;
  border-radius: 50%;
}
```

- [ ] **Step 8: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: build succeeds with no errors.

Manual checklist (start both the backend and frontend dev servers, open Edit PDF on a real PDF):
1. Add Text: confirm the white swatch appears in the color row, and a new native color-picker circle appears after the last swatch. Click the native picker, choose a custom color (e.g. a distinct orange not in the preset list), confirm the text you type uses that color.
2. Draw: confirm white swatch + native picker present. Draw a stroke with white selected, confirm it's visible against the page (may need to draw over a colored/dark area to see it, since white-on-white is invisible by design). Select an already-drawn stroke, confirm the picker's own displayed color updates to match the selected stroke's color (real-time restyling still works through the new rendering path).
3. Add Shape: confirm white swatch + native picker present. Draw a filled white rectangle over some text, Run, and confirm in the DOWNLOADED PDF that the white rectangle genuinely covers the text underneath (not just on-screen — the exported file is what matters).
4. Highlight: confirm the native picker is present (4 existing pastel swatches unchanged, no white swatch added). Pick a custom color via the picker, confirm it applies.
5. Confirm the native color-picker circle visually matches the existing swatches in size or its own being a reasonable natural fit (not a jarring rectangular default browser control).

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add a native color picker and a white swatch to Edit PDF's color-using tools"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

---

### Task 2: Delete/Backspace and arrow-key nudge shortcuts

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx` — the `handleKeyDown` function inside the existing keyboard-shortcut `useEffect` (~line 415), plus two new module-level constants

**Interfaces:**
- Consumes: `removeElement(id)`, `moveElement(el, dx, dy)`, `commitElements(next)`, `elements`, `selectedId` — all already exist in this file, unmodified by this task.
- Produces: nothing consumed by other tasks — this is the last task in the plan.

- [ ] **Step 1: Add the two nudge-step constants**

Near `MIN_DRAG_FRACTION` (line ~215), add:
```javascript
// Nudge step sizes, as fractions of the page (element coordinates are
// stored as 0-1 fractions, not pixel counts). Reasoned against
// pasteClipboard's own OFFSET = 0.03 (a one-time diagonal "paste nearby"
// jump) as a reference point: on a typical on-screen render of a US Letter
// page (612x792pt, commonly rendered somewhere around 600-900px tall),
// 0.004 works out to roughly 3-4px per keypress (a precise, perceptible
// nudge, not a sub-pixel no-op), and 0.02 works out to roughly 16px (a
// clear, deliberate move, slightly more conservative than paste's one-time
// offset since nudge is meant to feel incremental and repeatable).
const NUDGE_SMALL_STEP = 0.004;
const NUDGE_BIG_STEP = 0.02;
```

- [ ] **Step 2: Add Delete/Backspace and arrow-key nudge to `handleKeyDown`**

The current non-ctrl branch of `handleKeyDown` (inside the `useEffect` at line ~415) is:
```javascript
      if (!ctrl) {
        if (e.key === "Escape") setSelectedId(null);
        return;
      }
```
Replace it with:
```javascript
      if (!ctrl) {
        if (e.key === "Escape") {
          setSelectedId(null);
        } else if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
          e.preventDefault();
          removeElement(selectedId);
        } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) && selectedId) {
          const el = elements.find((item) => item.id === selectedId);
          if (el && el.type !== "text_edit") {
            e.preventDefault();
            const step = e.shiftKey ? NUDGE_BIG_STEP : NUDGE_SMALL_STEP;
            let dx = 0;
            let dy = 0;
            if (e.key === "ArrowLeft") dx = -step;
            else if (e.key === "ArrowRight") dx = step;
            else if (e.key === "ArrowUp") dy = -step;
            else dy = step;
            commitElements(elements.map((item) => (item.id === selectedId ? moveElement(item, dx, dy) : item)));
          }
        }
        return;
      }
```

- [ ] **Step 3: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: build succeeds with no errors.

Manual checklist:
1. Select a shape, press Delete — confirm it's removed from the page and `selectedId` clears (no leftover selection outline anywhere).
2. Select a shape, press Backspace — confirm the same removal behavior (both keys work identically).
3. With nothing selected, press Delete/Backspace — confirm nothing happens (no error, no accidental removal of a different element).
4. Select a shape, press each arrow key once — confirm it moves a small, precise amount in the correct direction (left/right/up/down match the key pressed).
5. Select a shape, hold Shift and press an arrow key — confirm it moves a visibly larger amount than the plain arrow-key case.
6. Nudge a shape repeatedly toward a page edge — confirm it stops cleanly at the edge (doesn't overshoot off the page or throw an error) — this is `moveElement`'s own existing clamping, being exercised by a new caller.
7. Double-click into an existing PDF text run to open the inline text editor (a `text_edit` element becomes selected/active) — confirm arrow keys do NOT nudge it (no movement, since `text_edit` elements are excluded) and typing in the editor still works normally (the `isTypingTarget`/`textDraft`/`runEditor` guards at the top of `handleKeyDown` still apply unchanged).
8. Confirm Ctrl+Z (undo) after a nudge correctly reverts the position, and Ctrl+Y (redo) reapplies it — nudge goes through the same `commitElements`/history path as every other change.
9. Run a full end-to-end pass: select a shape, nudge it into a new position, Run, and confirm in the DOWNLOADED PDF that the shape actually landed at the nudged position (not just on-screen).

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx
git commit -m "feat: add Delete/Backspace and arrow-key nudge shortcuts to Edit PDF"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

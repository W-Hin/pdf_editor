# Edit PDF: Real-Time Inline Text Editing — Design

**Status:** Approved by user 2026-09-04.

## Context

Fourth of five sub-projects from a larger feedback batch (see the decomposition in
`docs/superpowers/specs/2026-09-04-pdf-editor-page-scroll-viewer-design.md`'s Context section).
Edit Text mode currently works by clicking a run to open a separate "Replacement text" form
underneath the page canvas. The user wants this to work in place instead: double-click a run,
edit it directly where it sits on the page — the same inline-editor interaction Add Text already
shipped, applied here to editing existing text instead of placing new text.

This is the simplest of the five sub-projects: it reuses an already-proven pattern from this exact
codebase (Add Text's inline editor, commit-on-blur, auto-focus) rather than introducing anything
new, and requires **no backend change at all** — `_apply_text_edit` already handles an empty
replacement string correctly (redacts the original run, then inserts nothing), which is exactly
the "erase" behavior this design needs.

## Scope decisions (from brainstorming)

- **Single click stays exactly as it is today** — hovering/clicking a run shows its outline; no
  editor opens. Only **double-click** opens the inline editor, matching Add Text's
  select-vs-edit split.
- **The inline editor is a single-line `<input>`**, not a multi-line textarea — a text run is one
  line/span by definition (this project's established "text run" meaning, from `get_text`'s span
  walk), so there's nothing to wrap.
- **Only family/bold/italic/size are editable** — no underline/color/alignment, since this
  overrides a *detected* font on existing text rather than freely styling new text (matching
  `text_edit`'s existing `font_override` shape exactly: `{family, bold, italic, size}`).
- **Clearing all the text and clicking away commits an erase**, not a cancel — consistent with
  "what you see in the editor is what gets applied" and giving Edit Text a real way to delete a
  line without switching tools. No backend change needed (see Context).
- **An explicit "Revert" control replaces the current "Remove edit" button** — reopening an
  already-edited run's inline editor shows a small control that removes the queued edit entirely,
  restoring the original text, without requiring the user to manually retype it.

## Architecture

Entirely a frontend change to `EditPdfCanvas.jsx`'s Edit Text mode:

- `openRunEditor` moves from a single-click handler to a double-click handler on each run's
  overlay div.
- The editor renders as a floating overlay positioned at the run's `bbox` (matching Add Text's
  `textDraft` editor pattern exactly): a single-line `<input>` styled live to reflect the
  current/overridden font, with a small style-bar below carrying the family dropdown, bold/italic
  toggle buttons, and a size field — reusing the same commit-on-blur (`e.currentTarget.contains(
  e.relatedTarget)`) and auto-focus (`useEffect` on open) mechanics already proven in Add Text's
  implementation.
- Commit logic: builds/updates a `text_edit` element exactly as today's `submitRunEditor` does
  (`{id, type: "text_edit", page, run_index, text, font_override}`) — the only behavioral change
  is that an empty `text` value is now a valid, intentional commit (an erase) rather than something
  the UI would prevent.
- The "Revert" control removes the pending `text_edit` element for that run (today's
  `removeTextEdit`, unchanged in behavior — just relocated into the inline editor's UI instead of
  the bottom form).

## Testing

No backend changes — no new backend tests. No frontend automated tests (established convention) —
manual verification at the end of implementation: double-clicking a run opens the inline editor at
the right position, styled correctly; single-click no longer opens anything; editing text and
family/bold/italic/size and clicking away commits correctly (verified by re-opening the run and
seeing the update, and by running the tool and checking the output); clearing all text and
clicking away queues an erase, confirmed by running the tool and seeing the text genuinely gone
from the output; the Revert control removes a queued edit and restores the original text on
re-open; undo/redo still works for text edits exactly as it does for every other element type.

## Out of scope

- Anything about *how* an edit is detected/matched (run extraction, rotation handling) — unchanged.
- Rich/partial mid-run styling — covered by the fifth sub-project, brainstormed separately.

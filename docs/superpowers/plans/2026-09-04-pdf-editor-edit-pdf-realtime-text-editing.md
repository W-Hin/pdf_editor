# Edit PDF: Real-Time Inline Text Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Edit PDF's "click a run → fill out a bottom Replacement Text form" flow with real-time in-place editing: double-click a text run to open a floating single-line editor positioned exactly over it, edit directly, click away to commit (an empty result commits as an erase).

**Architecture:** Entirely a frontend change to `web/frontend/src/components/EditPdfCanvas.jsx`'s Edit Text mode. A single `runEditor` state object (replacing the four separate `editingRunIndex`/`editingRunPage`/`draftText`/`draftOverride`/`draftFamilyTouched` state variables) drives a new inline editor overlay, rendered by a new `renderRunEditorOverlay(run)` function co-located inside the existing `renderTextRun(run, pageNumber)` dispatch — no changes to `renderPageOverlay` itself are needed. The overlay reuses the exact commit-on-blur (`e.currentTarget.contains(e.relatedTarget)`) and auto-focus (`useEffect` keyed on an identity) mechanics Add Text's `textDraft`/`renderTextDraftEditor` already ship in this same file. The bottom-of-page `edit-pdf-canvas__run-editor` form and its `submitRunEditor`/`openRunEditor` (old) functions are deleted outright.

**Tech Stack:** React (function components, hooks), the existing `@phosphor-icons/react` icon set already imported in this file, plain CSS (no new dependencies).

## Global Constraints

- No backend changes. `_apply_text_edit` (`app/core/pdf_ops.py:578`) already handles `replacement_text=""` correctly — empirically re-verified for this plan: `edit_pdf` with a `text_edit` element carrying `"text": ""` redacts the original run and inserts nothing (`page.get_text()` on the output is `''`), with no other backend change required.
- Only `family`, `bold`, `italic`, `size` are editable on a run — no underline/color/alignment controls (this overrides a *detected* font on existing content, not free styling of new text; matches `text_edit`'s existing `font_override` shape `{family, bold, italic, size}` exactly, unchanged from today).
- Single click on a run does nothing new — the existing CSS-only hover outline (`.edit-pdf-canvas__run:hover`) is the only single-click-adjacent behavior; it needs no code change. Only **double-click** opens the inline editor.
- Clearing all the text and clicking away commits an **erase** (an empty `text_edit`), not a cancel — this is a deliberate, already-approved design choice.
- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. This plan's task commit is `feat:` and must **not** carry the trailer.
- No automated frontend tests (established project convention) — `npm run build` plus a specific manual browser checklist is the verification bar for the frontend task.

---

### Task 1: Real-time inline text-run editor

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes (all pre-existing in this file, unchanged): `runs` state (`{index, text, font, size, bold, italic, bbox: {top, left, right, bottom}, page}` per entry — `bbox` values are page-fraction insets, exactly like a `highlight` element's `left/top/right/bottom`); `pendingTextEditFor(run)` (looks up the queued `text_edit` element for a run, if any — unchanged); `commitElements(next)`, `newElementId()`, `elements`, `selectedId` (unchanged); `newTextFontFamilyCss(family)`, `FAMILY_OPTIONS` (unchanged, already used by Add Text's editor).
- Produces: a new `runEditor` state shape `{ page, runIndex, text, family, bold, italic, size, familyTouched } | null` (replaces `editingRunIndex`/`editingRunPage`/`draftText`/`draftOverride`/`draftFamilyTouched`, all four of which are deleted in this task — no other task or file references them). `openRunEditor(pageNumber, run)`, `commitRunEditor()`, `revertRunEditor(run)`, `handleRunEditorBlur(e)`, `renderRunEditorOverlay(run)` (all new). `submitRunEditor`/`removeTextEdit`/the old `openRunEditor` are deleted.

- [ ] **Step 1: Replace the four `draft*`/`editingRun*` state variables with one `runEditor` object**

Find (around line 133-142):

```jsx
  const [editingRunIndex, setEditingRunIndex] = useState(null);
  const [editingRunPage, setEditingRunPage] = useState(null);
  const [draftText, setDraftText] = useState("");
  const [draftOverride, setDraftOverride] = useState(null);
  // The family dropdown always defaults to "helvetica" regardless of the run's
  // detected font, so comparing its VALUE against "helvetica" cannot tell
  // "explicitly chose Helvetica on a Times run" from "never touched it" — and
  // silently drops the user's choice. Track the interaction itself instead.
  const [draftFamilyTouched, setDraftFamilyTouched] = useState(false);
```

Replace with:

```jsx
  // Null when no run is being edited. { page, runIndex, text, family, bold,
  // italic, size, familyTouched } while the inline editor is open — mirrors
  // textDraft's null-object pattern below. familyTouched exists for the same
  // reason the old draftFamilyTouched did: the family dropdown always starts
  // at "helvetica" regardless of the run's detected font, so comparing its
  // VALUE against "helvetica" can't distinguish "explicitly chose Helvetica
  // on a Times run" from "never touched it" — track the interaction itself.
  const [runEditor, setRunEditor] = useState(null);
  const runEditorInputRef = useRef(null);
```

- [ ] **Step 2: Add the auto-focus effect**

Add near the existing `textDraft` focus effect (around line 172-174):

```jsx
  useEffect(() => {
    if (runEditor) runEditorInputRef.current?.focus();
  }, [runEditor?.page, runEditor?.runIndex]);
```

- [ ] **Step 3: Update the runs-loading effect's reset call**

Find (around line 192-193):

```jsx
    loadRuns();
    setEditingRunIndex(null);
```

Replace with:

```jsx
    loadRuns();
    setRunEditor(null);
```

- [ ] **Step 4: Extend the global keydown guard to suppress shortcuts while the run editor is open**

Find (around line 256-257, inside the `handleKeyDown` function defined in the keyboard-shortcuts `useEffect`):

```jsx
    function handleKeyDown(e) {
      if (textDraft || isTypingTarget(document.activeElement)) return;
```

Replace with:

```jsx
    function handleKeyDown(e) {
      if (textDraft || runEditor || isTypingTarget(document.activeElement)) return;
```

This closes the same class of bug Add Text's editor already had fixed for it: the run editor's Bold/Italic buttons are plain `<button>` elements (not caught by `isTypingTarget`), so without this guard, clicking one and then pressing Ctrl+Z while the inline editor is still open would fire the global undo instead of doing nothing — corrupting the undo/redo stack mid-edit.

Also update this `useEffect`'s dependency array (currently `[elements, selectedId, textDraft]`, a few lines below the handler) to include `runEditor`:

```jsx
  }, [elements, selectedId, textDraft, runEditor]);
```

- [ ] **Step 5: Replace `openRunEditor`/`submitRunEditor`/`removeTextEdit` with `openRunEditor`/`commitRunEditor`/`revertRunEditor`**

Find (around line 778-818):

```jsx
  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    setEditingRunIndex(run.index);
    setEditingRunPage(pageNumber);
    setDraftText(pending ? pending.text : run.text);
    // Re-opening a queued edit that already carries an override means its
    // family was an explicit choice — keep it explicit.
    setDraftFamilyTouched(Boolean(pending?.font_override));
    setDraftOverride(
      pending?.font_override ?? {
        family: "helvetica",
        bold: run.bold,
        italic: run.italic,
        size: run.size,
      }
    );
  }

  function submitRunEditor(run) {
    const pending = pendingTextEditFor(run);
    const overrideChanged =
      draftFamilyTouched || draftOverride.bold !== run.bold || draftOverride.italic !== run.italic || draftOverride.size !== run.size;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editingRunPage,
      run_index: run.index,
      text: draftText,
      font_override: overrideChanged ? draftOverride : null,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
    setEditingRunIndex(null);
  }

  function removeTextEdit(run) {
    const pending = pendingTextEditFor(run);
    if (!pending) return;
    commitElements(elements.filter((el) => el.id !== pending.id));
    setEditingRunIndex(null);
  }
```

Replace with:

```jsx
  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    // Re-opening a queued edit that already carries an override means its
    // family was an explicit choice — keep it explicit.
    setRunEditor({
      page: pageNumber,
      runIndex: run.index,
      text: pending ? pending.text : run.text,
      family: pending?.font_override?.family ?? "helvetica",
      bold: pending?.font_override?.bold ?? run.bold,
      italic: pending?.font_override?.italic ?? run.italic,
      size: pending?.font_override?.size ?? run.size,
      familyTouched: Boolean(pending?.font_override),
    });
  }

  function commitRunEditor() {
    const editor = runEditor;
    setRunEditor(null);
    if (!editor) return;
    const run = runs.find((r) => r.index === editor.runIndex && r.page === editor.page);
    if (!run) return;
    const pending = pendingTextEditFor(run);
    const overrideChanged =
      editor.familyTouched || editor.bold !== run.bold || editor.italic !== run.italic || editor.size !== run.size;
    const textChanged = editor.text !== run.text;
    // Nothing pending and nothing changed from the run's own detected
    // text/font — the user opened the editor and closed it without editing
    // anything. Skip queuing a no-op text_edit so merely looking at a run
    // doesn't clutter `elements`/undo history. An empty text IS a real
    // change whenever the run originally had text (textChanged catches
    // this), and is deliberately committed as an erase per this
    // sub-project's design — never treated as "nothing to do".
    if (!pending && !textChanged && !overrideChanged) return;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editor.page,
      run_index: editor.runIndex,
      text: editor.text,
      font_override: overrideChanged ? { family: editor.family, bold: editor.bold, italic: editor.italic, size: editor.size } : null,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }

  function revertRunEditor(run) {
    const pending = pendingTextEditFor(run);
    if (pending) commitElements(elements.filter((el) => el.id !== pending.id));
    // Reset the still-open editor's fields back to the run's own detected
    // text/font so the input reflects the original immediately — no need to
    // close and reopen it to see the un-edited state.
    setRunEditor((e) => ({ ...e, text: run.text, family: "helvetica", bold: run.bold, italic: run.italic, size: run.size, familyTouched: false }));
  }

  function handleRunEditorBlur(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) {
      commitRunEditor();
    }
  }
```

- [ ] **Step 6: Add `renderRunEditorOverlay` and switch `renderTextRun` to double-click**

Find (around line 1214-1229):

```jsx
  function renderTextRun(run, pageNumber) {
    const pending = pendingTextEditFor(run);
    return (
      <div
        key={run.index}
        className={pending ? "edit-pdf-canvas__run edit-pdf-canvas__run--queued" : "edit-pdf-canvas__run"}
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onClick={() => openRunEditor(pageNumber, run)}
      />
    );
  }
```

Replace with:

```jsx
  function renderRunEditorOverlay(run) {
    return (
      <div
        key={run.index}
        className="edit-pdf-canvas__run-editor-inline"
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onBlur={handleRunEditorBlur}
      >
        <input
          ref={runEditorInputRef}
          type="text"
          className="edit-pdf-canvas__run-editor-input"
          value={runEditor.text}
          onChange={(e) => setRunEditor((r) => ({ ...r, text: e.target.value }))}
          style={{
            fontFamily: newTextFontFamilyCss(runEditor.family),
            fontWeight: runEditor.bold ? "bold" : "normal",
            fontStyle: runEditor.italic ? "italic" : "normal",
            fontSize: `${runEditor.size}px`,
          }}
        />
        <div className="edit-pdf-canvas__new-text-style-bar">
          <select
            value={runEditor.family}
            onChange={(e) => setRunEditor((r) => ({ ...r, family: e.target.value, familyTouched: true }))}
          >
            {FAMILY_OPTIONS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <input
            type="number"
            min={1}
            value={runEditor.size}
            onChange={(e) => setRunEditor((r) => ({ ...r, size: Number(e.target.value) }))}
          />
          <button
            type="button"
            className={runEditor.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
            onClick={() => setRunEditor((r) => ({ ...r, bold: !r.bold }))}
            aria-label="Bold"
          >
            <TextB size={14} weight="bold" />
          </button>
          <button
            type="button"
            className={runEditor.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
            onClick={() => setRunEditor((r) => ({ ...r, italic: !r.italic }))}
            aria-label="Italic"
          >
            <TextItalic size={14} weight="bold" />
          </button>
          {pendingTextEditFor(run) && (
            <button type="button" className="edit-pdf-canvas__width-button" onClick={() => revertRunEditor(run)}>
              Revert
            </button>
          )}
        </div>
      </div>
    );
  }

  function renderTextRun(run, pageNumber) {
    if (runEditor && runEditor.page === pageNumber && runEditor.runIndex === run.index) {
      return renderRunEditorOverlay(run);
    }
    const pending = pendingTextEditFor(run);
    return (
      <div
        key={run.index}
        className={pending ? "edit-pdf-canvas__run edit-pdf-canvas__run--queued" : "edit-pdf-canvas__run"}
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onDoubleClick={() => openRunEditor(pageNumber, run)}
      />
    );
  }
```

(`renderPageOverlay` itself needs no change — it already calls `renderTextRun(run, pageNumber)` once per run inside its existing `activeMode === "text" && runs.filter(...).map(...)` block, and that call site is untouched.)

- [ ] **Step 7: Delete the bottom-of-page "Replacement text" form**

Find (around line 1470-1531):

```jsx
      {activeMode === "text" && editingRunIndex !== null && (
        <div className="edit-pdf-canvas__run-editor">
          {(() => {
            const run = runs.find((r) => r.index === editingRunIndex && r.page === editingRunPage);
            if (!run) return null;
            const pending = pendingTextEditFor(run);
            return (
              <>
                <label className="field">
                  Replacement text
                  <input type="text" value={draftText} onChange={(e) => setDraftText(e.target.value)} />
                </label>
                <p className="edit-pdf-canvas__detected">
                  Detected: {run.font}, {run.size.toFixed(1)}pt{run.bold ? ", bold" : ""}
                  {run.italic ? ", italic" : ""}
                </p>
                <label className="field">
                  Font family override
                  <select
                    value={draftOverride.family}
                    onChange={(e) => {
                      setDraftFamilyTouched(true);
                      setDraftOverride((o) => ({ ...o, family: e.target.value }));
                    }}
                  >
                    {FAMILY_OPTIONS.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field field--checkbox">
                  <input type="checkbox" checked={draftOverride.bold} onChange={(e) => setDraftOverride((o) => ({ ...o, bold: e.target.checked }))} />
                  Bold
                </label>
                <label className="field field--checkbox">
                  <input type="checkbox" checked={draftOverride.italic} onChange={(e) => setDraftOverride((o) => ({ ...o, italic: e.target.checked }))} />
                  Italic
                </label>
                <label className="field">
                  Font size
                  <input type="number" min={1} value={draftOverride.size} onChange={(e) => setDraftOverride((o) => ({ ...o, size: Number(e.target.value) }))} />
                </label>
                <div className="edit-pdf-canvas__run-editor-actions">
                  <button type="button" onClick={() => submitRunEditor(run)}>
                    {pending ? "Update edit" : "Add edit"}
                  </button>
                  {pending && (
                    <button type="button" onClick={() => removeTextEdit(run)}>
                      Remove edit
                    </button>
                  )}
                  <button type="button" onClick={() => setEditingRunIndex(null)}>
                    Cancel
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      )}
```

Delete this block entirely (nothing replaces it — the inline editor rendered by Step 6 is the sole editing UI now).

- [ ] **Step 8: Update CSS — remove the now-unused bottom-form styles, add the inline editor's styles**

In `web/frontend/src/index.css`, find and delete these three now-unused rules (around line 714-735):

```css
.edit-pdf-canvas__run-editor {
  margin-top: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 360px;
}

.edit-pdf-canvas__detected {
  font-size: 12px;
  color: var(--color-muted-foreground);
  margin: 0;
}

.edit-pdf-canvas__run-editor-actions {
  display: flex;
  gap: var(--space-2);
}
```

Add the inline editor's styles near the existing `.edit-pdf-canvas__new-text-editor`/`.edit-pdf-canvas__new-text-textarea` rules (around line 949-966), reusing the same `z-index: 3` (so the inline editor floats above other page content the same way Add Text's editor does) and the same `.edit-pdf-canvas__new-text-style-bar` class for its style bar (no new style-bar CSS needed — it's identical to Add Text's):

```css
.edit-pdf-canvas__run-editor-inline {
  position: absolute;
  z-index: 3;
  display: flex;
  flex-direction: column;
}

.edit-pdf-canvas__run-editor-input {
  flex: 1;
  width: 100%;
  height: 100%;
  border: 1px solid var(--color-accent);
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.9);
  padding: 2px 4px;
  box-sizing: border-box;
  line-height: 1.2;
}
```

- [ ] **Step 9: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 10: Manual browser check**

- Single-clicking a text run does nothing new — only the existing hover outline shows; no editor opens.
- Double-clicking a text run opens the inline editor exactly over the run's own position, pre-filled with its current text, auto-focused (typing immediately replaces/extends the text with no extra click needed).
- Editing the text and clicking away commits the change — verified by re-opening the run (shows the new text) and by running the tool and inspecting the downloaded PDF's text.
- Changing family/bold/italic/size and clicking away commits the override — verified the same way (re-open shows the change; downloaded output reflects it).
- Opening a run's editor and clicking away with NO changes made does not queue a new edit (re-open still shows the original, unedited text; running the tool leaves that run completely untouched in the output).
- Clearing all the text in the editor and clicking away queues an erase — confirmed by running the tool and seeing that run's text genuinely gone from the output (not just visually blank in the editor).
- Reopening an already-edited run shows a "Revert" control; clicking it removes the queued edit, and the input immediately shows the original detected text/font (no need to close and reopen to see this).
- Undo/redo still works for text edits exactly as it does for every other element type — edit a run, click away to commit, then Ctrl+Z undoes it (run reverts to original in the editor UI and in a subsequent Run), Ctrl+Y redoes it.
- Pressing Ctrl+Z while the inline editor is still open (focus on the Bold button, not the input) does nothing to the global undo stack — closing the editor first (click away) still works normally afterward.
- The bottom-of-page "Replacement text" form no longer appears anywhere in Edit Text mode.

- [ ] **Step 11: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: replace Edit Text's bottom form with a real-time in-place editor"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows this task's single commit on top of `main`'s current tip, `feat:`-prefixed, no `Co-Authored-By` trailer.
- [ ] Confirm no remaining references to `editingRunIndex`, `editingRunPage`, `draftText`, `draftOverride`, `draftFamilyTouched`, `submitRunEditor`, or the old single-click `openRunEditor`/`removeTextEdit` anywhere in `EditPdfCanvas.jsx` (a plain text search for each name should return nothing).

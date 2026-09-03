import { useEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight, CursorText, PencilSimple, Rectangle, Highlighter, ImageSquare, X } from "@phosphor-icons/react";
import { thumbnailUrl, fetchTextRuns } from "../api";

const PREVIEW_MAX_SIZE = 700;

const MODES = [
  { id: "text", label: "Edit Text", icon: CursorText },
  { id: "draw", label: "Draw", icon: PencilSimple },
  { id: "shapes", label: "Shapes", icon: Rectangle },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "image", label: "Insert Image", icon: ImageSquare },
];

const FAMILY_OPTIONS = ["helvetica", "times", "courier"];

export default function EditPdfCanvas({ fileId, pageCount, onChange }) {
  const stageRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [activeMode, setActiveMode] = useState("text");
  const [elements, setElements] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [runs, setRuns] = useState([]);
  const [editingRunIndex, setEditingRunIndex] = useState(null);
  const [draftText, setDraftText] = useState("");
  const [draftOverride, setDraftOverride] = useState(null);

  useEffect(() => {
    if (!fileId) return;
    fetchTextRuns(fileId, currentPage).then((data) => setRuns(data.runs));
    setEditingRunIndex(null);
  }, [fileId, currentPage]);

  if (!fileId || !pageCount) return null;

  function commitElements(next) {
    setElements(next);
    onChange(next);
  }

  function newElementId() {
    return crypto.randomUUID();
  }

  function pointFromEvent(e) {
    const rect = stageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  // Stubs — replaced (body only) by later tasks. Kept here so the stage's
  // dispatcher below never needs to change as modes are filled in.
  function handleDrawMouseDown() {}
  function handleDrawMouseMove() {}
  function handleDrawMouseUp() {}
  function handleShapeMouseDown() {}
  function handleShapeMouseMove() {}
  function handleShapeMouseUp() {}
  function handleHighlightMouseDown() {}
  function handleHighlightMouseMove() {}
  function handleHighlightMouseUp() {}
  function handleImageStageClick() {}

  function handleStageMouseDown(e) {
    if (activeMode === "draw") return handleDrawMouseDown(e);
    if (activeMode === "shapes") return handleShapeMouseDown(e);
    if (activeMode === "highlight") return handleHighlightMouseDown(e);
    if (activeMode === "image") return handleImageStageClick(e);
  }

  function handleStageMouseMove(e) {
    if (activeMode === "draw") return handleDrawMouseMove(e);
    if (activeMode === "shapes") return handleShapeMouseMove(e);
    if (activeMode === "highlight") return handleHighlightMouseMove(e);
  }

  function handleStageMouseUp(e) {
    if (activeMode === "draw") return handleDrawMouseUp(e);
    if (activeMode === "shapes") return handleShapeMouseUp(e);
    if (activeMode === "highlight") return handleHighlightMouseUp(e);
  }

  function pendingTextEditFor(run) {
    return elements.find((el) => el.type === "text_edit" && el.page === currentPage && el.run_index === run.index);
  }

  function openRunEditor(run) {
    const pending = pendingTextEditFor(run);
    setEditingRunIndex(run.index);
    setDraftText(pending ? pending.text : run.text);
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
      draftOverride.family !== "helvetica" || draftOverride.bold !== run.bold || draftOverride.italic !== run.italic || draftOverride.size !== run.size;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: currentPage,
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

  return (
    <div className="edit-pdf-canvas">
      <div className="edit-pdf-canvas__modes">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            className={activeMode === mode.id ? "edit-pdf-canvas__mode-button edit-pdf-canvas__mode-button--active" : "edit-pdf-canvas__mode-button"}
            onClick={() => setActiveMode(mode.id)}
          >
            <mode.icon size={16} weight="regular" />
            {mode.label}
          </button>
        ))}
      </div>

      <div className="edit-pdf-canvas__nav">
        <button type="button" onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1}>
          <CaretLeft size={14} weight="bold" />
          Previous
        </button>
        <span>
          Page {currentPage} of {pageCount} ({new Set(elements.map((e) => e.page)).size} page{new Set(elements.map((e) => e.page)).size === 1 ? "" : "s"} have edits)
        </span>
        <button type="button" onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))} disabled={currentPage === pageCount}>
          Next
          <CaretRight size={14} weight="bold" />
        </button>
      </div>

      <div
        ref={stageRef}
        className="edit-pdf-canvas__stage"
        onMouseDown={handleStageMouseDown}
        onMouseMove={handleStageMouseMove}
        onMouseUp={handleStageMouseUp}
        onMouseLeave={handleStageMouseUp}
      >
        <img
          className="edit-pdf-canvas__image"
          src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
          alt={`Page ${currentPage} preview`}
          draggable={false}
        />

        {activeMode === "text" &&
          runs.map((run) => {
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
                onClick={() => openRunEditor(run)}
              />
            );
          })}
      </div>

      {activeMode === "text" && editingRunIndex !== null && (
        <div className="edit-pdf-canvas__run-editor">
          {(() => {
            const run = runs.find((r) => r.index === editingRunIndex);
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
                  <select value={draftOverride.family} onChange={(e) => setDraftOverride((o) => ({ ...o, family: e.target.value }))}>
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
    </div>
  );
}

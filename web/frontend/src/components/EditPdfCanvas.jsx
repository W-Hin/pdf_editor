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

const MARKUP_COLORS = ["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5"];
const STROKE_WIDTHS = { thin: 1, medium: 3, thick: 6 };

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
  const [drawColor, setDrawColor] = useState(MARKUP_COLORS[0]);
  const [drawWidth, setDrawWidth] = useState("medium");
  const [activeStroke, setActiveStroke] = useState(null);
  const [shapeType, setShapeType] = useState("rectangle");
  const [shapeColor, setShapeColor] = useState(MARKUP_COLORS[0]);
  const [shapeWidth, setShapeWidth] = useState("medium");
  const [shapeFilled, setShapeFilled] = useState(false);
  const [shapeDragStart, setShapeDragStart] = useState(null);
  const [shapeDragCurrent, setShapeDragCurrent] = useState(null);

  useEffect(() => {
    if (!fileId) return;
    async function loadRuns() {
      try {
        const data = await fetchTextRuns(fileId, currentPage);
        setRuns(data.runs);
      } catch (err) {
        console.error("Failed to load text runs:", err);
        setRuns([]);
      }
    }
    loadRuns();
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
  function handleDrawMouseDown(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    setActiveStroke([point]);
  }

  function handleDrawMouseMove(e) {
    if (!activeStroke) return;
    const point = pointFromEvent(e);
    if (!point) return;
    setActiveStroke((pts) => [...pts, point]);
  }

  function handleDrawMouseUp() {
    if (!activeStroke || activeStroke.length < 2) return;
    const next = [
      ...elements,
      { id: newElementId(), type: "stroke", page: currentPage, points: activeStroke, color: drawColor, width: STROKE_WIDTHS[drawWidth] },
    ];
    commitElements(next);
    setActiveStroke(null);
  }
  function handleShapeMouseDown(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    setShapeDragStart(point);
    setShapeDragCurrent(point);
  }

  function handleShapeMouseMove(e) {
    if (!shapeDragStart) return;
    const point = pointFromEvent(e);
    if (!point) return;
    setShapeDragCurrent(point);
  }

  function handleShapeMouseUp() {
    if (!shapeDragStart || !shapeDragCurrent) return;
    const { x: x0, y: y0 } = shapeDragStart;
    const { x: x1, y: y1 } = shapeDragCurrent;
    setShapeDragStart(null);
    setShapeDragCurrent(null);
    if (x0 === x1 && y0 === y1) return;
    const next = [
      ...elements,
      {
        id: newElementId(),
        type: "shape",
        page: currentPage,
        shape: shapeType,
        x0,
        y0,
        x1,
        y1,
        color: shapeColor,
        width: STROKE_WIDTHS[shapeWidth],
        filled: shapeType === "rectangle" || shapeType === "ellipse" ? shapeFilled : false,
      },
    ];
    commitElements(next);
  }
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

      {activeMode === "draw" && (
        <div className="edit-pdf-canvas__style-bar">
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={c === drawColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
              style={{ background: c }}
              onClick={() => setDrawColor(c)}
              aria-label={`Color ${c}`}
            />
          ))}
          {Object.keys(STROKE_WIDTHS).map((w) => (
            <button
              key={w}
              type="button"
              className={w === drawWidth ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
              onClick={() => setDrawWidth(w)}
            >
              {w}
            </button>
          ))}
        </div>
      )}

      {activeMode === "shapes" && (
        <div className="edit-pdf-canvas__style-bar">
          {["rectangle", "ellipse", "line", "arrow"].map((s) => (
            <button
              key={s}
              type="button"
              className={s === shapeType ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
              onClick={() => setShapeType(s)}
            >
              {s}
            </button>
          ))}
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={c === shapeColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
              style={{ background: c }}
              onClick={() => setShapeColor(c)}
              aria-label={`Color ${c}`}
            />
          ))}
          {Object.keys(STROKE_WIDTHS).map((w) => (
            <button
              key={w}
              type="button"
              className={w === shapeWidth ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
              onClick={() => setShapeWidth(w)}
            >
              {w}
            </button>
          ))}
          {(shapeType === "rectangle" || shapeType === "ellipse") && (
            <label className="field field--checkbox">
              <input type="checkbox" checked={shapeFilled} onChange={(e) => setShapeFilled(e.target.checked)} />
              Fill
            </label>
          )}
        </div>
      )}

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

        <svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none">
          {elements
            .filter((el) => el.type === "stroke" && el.page === currentPage)
            .map((el) => (
              <g key={el.id} onClick={() => setSelectedId(el.id)}>
                <polyline
                  points={el.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
                  fill="none"
                  stroke={el.color}
                  strokeWidth={el.width / 3}
                  vectorEffect="non-scaling-stroke"
                  className={el.id === selectedId ? "edit-pdf-canvas__stroke edit-pdf-canvas__stroke--selected" : "edit-pdf-canvas__stroke"}
                />
              </g>
            ))}
          {activeStroke && (
            <polyline
              points={activeStroke.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
              fill="none"
              stroke={drawColor}
              strokeWidth={STROKE_WIDTHS[drawWidth] / 3}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

        {elements
          .filter((el) => el.type === "stroke" && el.page === currentPage)
          .map((el) => {
            const xs = el.points.map((p) => p.x);
            const ys = el.points.map((p) => p.y);
            const left = Math.min(...xs);
            const top = Math.min(...ys);
            return (
              <button
                key={`${el.id}-remove`}
                type="button"
                className="edit-pdf-canvas__element-remove"
                style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => commitElements(elements.filter((e) => e.id !== el.id))}
                aria-label="Remove this stroke"
              >
                <X size={12} weight="bold" />
              </button>
            );
          })}

        <svg className="edit-pdf-canvas__shapes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ zIndex: 2 }}>
          {elements
            .filter((el) => el.type === "shape" && el.page === currentPage)
            .map((el) => {
              const stroke = el.color;
              const fill = el.filled ? el.color : "none";
              const commonProps = {
                stroke,
                fill,
                strokeWidth: el.width / 3,
                vectorEffect: "non-scaling-stroke",
                className: el.id === selectedId ? "edit-pdf-canvas__shape edit-pdf-canvas__shape--selected" : "edit-pdf-canvas__shape",
              };
              if (el.shape === "rectangle") {
                return (
                  <g key={el.id} onClick={() => setSelectedId(el.id)}>
                    <rect
                      {...commonProps}
                      x={Math.min(el.x0, el.x1) * 100}
                      y={Math.min(el.y0, el.y1) * 100}
                      width={Math.abs(el.x1 - el.x0) * 100}
                      height={Math.abs(el.y1 - el.y0) * 100}
                    />
                  </g>
                );
              }
              if (el.shape === "ellipse") {
                return (
                  <g key={el.id} onClick={() => setSelectedId(el.id)}>
                    <ellipse
                      {...commonProps}
                      cx={((el.x0 + el.x1) / 2) * 100}
                      cy={((el.y0 + el.y1) / 2) * 100}
                      rx={(Math.abs(el.x1 - el.x0) / 2) * 100}
                      ry={(Math.abs(el.y1 - el.y0) / 2) * 100}
                    />
                  </g>
                );
              }
              // line and arrow both render as a line preview; the real arrowhead is
              // drawn server-side by edit_pdf — this is close enough for the queue preview.
              return (
                <g key={el.id} onClick={() => setSelectedId(el.id)}>
                  <line {...commonProps} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} />
                </g>
              );
            })}
          {shapeDragStart && shapeDragCurrent && (
            <line
              x1={shapeDragStart.x * 100}
              y1={shapeDragStart.y * 100}
              x2={shapeDragCurrent.x * 100}
              y2={shapeDragCurrent.y * 100}
              stroke={shapeColor}
              strokeWidth={STROKE_WIDTHS[shapeWidth] / 3}
              strokeDasharray="2,1"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

        {elements
          .filter((el) => el.type === "shape" && el.page === currentPage)
          .map((el) => (
            <button
              key={`${el.id}-remove`}
              type="button"
              className="edit-pdf-canvas__element-remove"
              style={{ left: `${Math.min(el.x0, el.x1) * 100}%`, top: `${Math.min(el.y0, el.y1) * 100}%` }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => commitElements(elements.filter((e) => e.id !== el.id))}
              aria-label="Remove this shape"
            >
              <X size={12} weight="bold" />
            </button>
          ))}

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

import { useRef, useState } from "react";
import { CaretLeft, CaretRight, X } from "@phosphor-icons/react";
import { thumbnailUrl } from "../api";

const PREVIEW_MAX_SIZE = 700;
const MIN_DRAG_FRACTION = 0.02;

export default function RedactSelector({ fileId, pageCount, onChange }) {
  const containerRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [redactions, setRedactions] = useState([]);
  const [dragStart, setDragStart] = useState(null);
  const [dragCurrent, setDragCurrent] = useState(null);

  if (!fileId || !pageCount) return null;

  function pointFromEvent(e) {
    const rect = containerRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleMouseDown(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    setDragStart(point);
    setDragCurrent(point);
  }

  function handleMouseMove(e) {
    if (!dragStart) return;
    const point = pointFromEvent(e);
    if (!point) return;
    setDragCurrent(point);
  }

  function handleMouseUp() {
    if (!dragStart || !dragCurrent) return;
    const x0 = Math.min(dragStart.x, dragCurrent.x);
    const x1 = Math.max(dragStart.x, dragCurrent.x);
    const y0 = Math.min(dragStart.y, dragCurrent.y);
    const y1 = Math.max(dragStart.y, dragCurrent.y);
    setDragStart(null);
    setDragCurrent(null);
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) {
      return; // too small to be a deliberate drag
    }
    const next = [...redactions, { page: currentPage, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1 }];
    setRedactions(next);
    onChange(next);
  }

  function removeBox(index) {
    const next = redactions.filter((_, i) => i !== index);
    setRedactions(next);
    onChange(next);
  }

  const activeDragBox =
    dragStart && dragCurrent
      ? {
          x0: Math.min(dragStart.x, dragCurrent.x),
          y0: Math.min(dragStart.y, dragCurrent.y),
          x1: Math.max(dragStart.x, dragCurrent.x),
          y1: Math.max(dragStart.y, dragCurrent.y),
        }
      : null;

  const pageBoxes = redactions
    .map((r, index) => ({ ...r, index }))
    .filter((r) => r.page === currentPage);
  const markedPageCount = new Set(redactions.map((r) => r.page)).size;

  return (
    <div className="redact-selector">
      <div className="redact-selector__nav">
        <button
          type="button"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={currentPage === 1}
        >
          <CaretLeft size={14} weight="bold" />
          Previous
        </button>
        <span>
          Page {currentPage} of {pageCount} ({markedPageCount} page{markedPageCount === 1 ? "" : "s"} marked)
        </span>
        <button
          type="button"
          onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
          disabled={currentPage === pageCount}
        >
          Next
          <CaretRight size={14} weight="bold" />
        </button>
      </div>
      <div
        ref={containerRef}
        className="redact-selector__canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <img
          className="redact-selector__image"
          src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
          alt={`Page ${currentPage} preview — drag to mark an area for redaction`}
          draggable={false}
        />
        {pageBoxes.map((box) => (
          <div
            key={box.index}
            className="redact-selector__box"
            style={{
              left: `${box.left * 100}%`,
              top: `${box.top * 100}%`,
              width: `${(1 - box.left - box.right) * 100}%`,
              height: `${(1 - box.top - box.bottom) * 100}%`,
            }}
          >
            <button
              type="button"
              className="redact-selector__box-remove"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => removeBox(box.index)}
              aria-label="Remove this redaction area"
            >
              <X size={12} weight="bold" />
            </button>
          </div>
        ))}
        {activeDragBox && (
          <div
            className="redact-selector__box redact-selector__box--dragging"
            style={{
              left: `${activeDragBox.x0 * 100}%`,
              top: `${activeDragBox.y0 * 100}%`,
              width: `${(activeDragBox.x1 - activeDragBox.x0) * 100}%`,
              height: `${(activeDragBox.y1 - activeDragBox.y0) * 100}%`,
            }}
          />
        )}
      </div>
    </div>
  );
}

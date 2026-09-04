import { X } from "@phosphor-icons/react";
import { useState } from "react";
import PageScrollViewer from "./PageScrollViewer";

const MIN_DRAG_FRACTION = 0.02;

export default function RedactSelector({ fileId, pageCount, onChange }) {
  const [redactions, setRedactions] = useState([]);
  const [dragStart, setDragStart] = useState(null);
  const [dragCurrent, setDragCurrent] = useState(null);
  const [dragPage, setDragPage] = useState(null);

  function pointFromEvent(pageRef, e) {
    const rect = pageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setDragPage(pageNumber);
    setDragStart(point);
    setDragCurrent(point);
  }

  function handleMouseMove(pageRef, e) {
    if (!dragStart) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setDragCurrent(point);
  }

  function handleMouseUp() {
    if (!dragStart || !dragCurrent) return;
    const x0 = Math.min(dragStart.x, dragCurrent.x);
    const x1 = Math.max(dragStart.x, dragCurrent.x);
    const y0 = Math.min(dragStart.y, dragCurrent.y);
    const y1 = Math.max(dragStart.y, dragCurrent.y);
    const page = dragPage;
    setDragStart(null);
    setDragCurrent(null);
    setDragPage(null);
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) {
      return; // too small to be a deliberate drag
    }
    const next = [...redactions, { page, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1 }];
    setRedactions(next);
    onChange(next);
  }

  function removeBox(index) {
    const next = redactions.filter((_, i) => i !== index);
    setRedactions(next);
    onChange(next);
  }

  if (!fileId || !pageCount) return null;

  function renderPageOverlay(pageNumber, pageRef) {
    const pageBoxes = redactions.map((r, index) => ({ ...r, index })).filter((r) => r.page === pageNumber);
    const activeDragBox =
      dragPage === pageNumber && dragStart && dragCurrent
        ? {
            x0: Math.min(dragStart.x, dragCurrent.x),
            y0: Math.min(dragStart.y, dragCurrent.y),
            x1: Math.max(dragStart.x, dragCurrent.x),
            y1: Math.max(dragStart.y, dragCurrent.y),
          }
        : null;
    return (
      <div
        className="redact-selector__canvas"
        onMouseDown={(e) => handleMouseDown(pageNumber, pageRef, e)}
        onMouseMove={(e) => handleMouseMove(pageRef, e)}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
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
    );
  }

  return <PageScrollViewer fileId={fileId} pageCount={pageCount} renderPageOverlay={renderPageOverlay} className="redact-selector" />;
}

import { useRef, useState } from "react";
import { thumbnailUrl } from "../api";

const PREVIEW_MAX_SIZE = 700;
const MIN_DRAG_FRACTION = 0.02;

export default function CropSelector({ fileId, onChange }) {
  const containerRef = useRef(null);
  const [dragStart, setDragStart] = useState(null);
  const [dragCurrent, setDragCurrent] = useState(null);
  const [committedBox, setCommittedBox] = useState(null);

  if (!fileId) return null;

  function pointFromEvent(e) {
    const rect = containerRef.current.getBoundingClientRect();
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleMouseDown(e) {
    const point = pointFromEvent(e);
    setDragStart(point);
    setDragCurrent(point);
  }

  function handleMouseMove(e) {
    if (!dragStart) return;
    setDragCurrent(pointFromEvent(e));
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
      return; // too small to be a deliberate drag — keep any already-committed box
    }
    setCommittedBox({ x0, y0, x1, y1 });
    onChange({ top: y0, left: x0, right: 1 - x1, bottom: 1 - y1 });
  }

  const activeBox =
    dragStart && dragCurrent
      ? {
          x0: Math.min(dragStart.x, dragCurrent.x),
          y0: Math.min(dragStart.y, dragCurrent.y),
          x1: Math.max(dragStart.x, dragCurrent.x),
          y1: Math.max(dragStart.y, dragCurrent.y),
        }
      : committedBox;

  return (
    <div
      ref={containerRef}
      className="crop-selector"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <img
        className="crop-selector__image"
        src={thumbnailUrl(fileId, 1, PREVIEW_MAX_SIZE)}
        alt="Page 1 preview — drag to select the area to keep"
        draggable={false}
      />
      {activeBox && (
        <>
          <div
            className="crop-selector__mask"
            style={{ left: 0, right: 0, top: 0, height: `${activeBox.y0 * 100}%` }}
          />
          <div
            className="crop-selector__mask"
            style={{ left: 0, right: 0, top: `${activeBox.y1 * 100}%`, bottom: 0 }}
          />
          <div
            className="crop-selector__mask"
            style={{
              top: `${activeBox.y0 * 100}%`,
              height: `${(activeBox.y1 - activeBox.y0) * 100}%`,
              left: 0,
              width: `${activeBox.x0 * 100}%`,
            }}
          />
          <div
            className="crop-selector__mask"
            style={{
              top: `${activeBox.y0 * 100}%`,
              height: `${(activeBox.y1 - activeBox.y0) * 100}%`,
              right: 0,
              width: `${(1 - activeBox.x1) * 100}%`,
            }}
          />
          <div
            className="crop-selector__box"
            style={{
              left: `${activeBox.x0 * 100}%`,
              top: `${activeBox.y0 * 100}%`,
              width: `${(activeBox.x1 - activeBox.x0) * 100}%`,
              height: `${(activeBox.y1 - activeBox.y0) * 100}%`,
            }}
          />
        </>
      )}
    </div>
  );
}

import { useState } from "react";
import { Check, DotsSixVertical } from "@phosphor-icons/react";
import { thumbnailUrl } from "../api";

export default function PageGrid({
  fileId,
  pageCount,
  mode = "view",
  selected,
  onToggle,
  order,
  onReorder,
  pageRange,
  rotateAngle,
  overlay,
  overlayPosition,
}) {
  const [dragIndex, setDragIndex] = useState(null);
  const [naturalSizes, setNaturalSizes] = useState({});

  if (!fileId || !pageCount) return null;

  const fullPages = Array.from({ length: pageCount }, (_, i) => i + 1);
  const pages =
    mode === "reorder" && order
      ? order
      : pageRange
        ? fullPages.filter((n) => n >= pageRange[0] && n <= pageRange[1])
        : fullPages;

  function handleDragStart(index) {
    if (mode !== "reorder") return;
    setDragIndex(index);
  }

  function handleDrop(index) {
    if (mode !== "reorder") return;
    if (dragIndex === null || dragIndex === index) {
      setDragIndex(null);
      return;
    }
    const next = [...pages];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(index, 0, moved);
    onReorder(next);
    setDragIndex(null);
  }

  function handleImageLoad(pageNumber, e) {
    const { naturalWidth: w, naturalHeight: h } = e.target;
    if (!w || !h) return;
    setNaturalSizes((prev) =>
      prev[pageNumber]?.w === w && prev[pageNumber]?.h === h ? prev : { ...prev, [pageNumber]: { w, h } }
    );
  }

  function rotationStyleFor(pageNumber) {
    if (!rotateAngle) return undefined;
    const normalized = ((rotateAngle % 360) + 360) % 360;
    const swapsDimensions = normalized === 90 || normalized === 270;
    const size = naturalSizes[pageNumber];
    // Rotating a portrait thumbnail 90/270 swaps its visual bounding box,
    // which would spill past the (still-portrait) container and get clipped.
    // Scaling by the image's own width/height ratio shrinks it back to fit
    // inside the original box instead of cropping it.
    const scale = swapsDimensions && size ? size.w / size.h : 1;
    return { transform: `rotate(${rotateAngle}deg) scale(${scale})` };
  }

  return (
    <div className={`page-grid page-grid--${mode}`}>
      {pages.map((pageNumber, index) => {
        const isSelected = mode === "select" && selected?.includes(pageNumber);
        return (
          <div
            key={pageNumber}
            className={`page-thumb ${isSelected ? "page-thumb--selected" : ""}`}
            draggable={mode === "reorder"}
            onDragStart={() => handleDragStart(index)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => handleDrop(index)}
            onDragEnd={() => setDragIndex(null)}
            onClick={() => mode === "select" && onToggle(pageNumber)}
          >
            <div className="page-thumb__image-wrap">
              <img
                draggable={false}
                src={thumbnailUrl(fileId, pageNumber)}
                alt={`Page ${pageNumber}`}
                loading="lazy"
                onLoad={(e) => handleImageLoad(pageNumber, e)}
                style={rotationStyleFor(pageNumber)}
              />
              {overlay && (
                <div
                  className={`page-thumb__overlay${overlayPosition ? ` page-thumb__overlay--${overlayPosition}` : ""}`}
                  aria-hidden="true"
                >
                  {overlay(pageNumber)}
                </div>
              )}
            </div>
            <span className="page-thumb__label">Page {pageNumber}</span>
            {isSelected && (
              <span className="page-thumb__badge">
                <Check size={14} weight="bold" />
              </span>
            )}
            {mode === "reorder" && (
              <span className="page-thumb__drag-handle">
                <DotsSixVertical size={18} weight="bold" />
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

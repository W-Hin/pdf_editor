import { useState } from "react";
import { Check, DotsSixVertical } from "@phosphor-icons/react";
import { thumbnailUrl } from "../api";

export default function PageGrid({ fileId, pageCount, mode = "view", selected, onToggle, order, onReorder }) {
  const [dragIndex, setDragIndex] = useState(null);

  if (!fileId || !pageCount) return null;

  const pages = mode === "reorder" && order ? order : Array.from({ length: pageCount }, (_, i) => i + 1);

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
            <img draggable={false} src={thumbnailUrl(fileId, pageNumber)} alt={`Page ${pageNumber}`} loading="lazy" />
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

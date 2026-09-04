import { useEffect, useRef, useState } from "react";
import { thumbnailUrl } from "../api";

const DEFAULT_MAX_SIZE = 1800;

export default function PageScrollViewer({ fileId, pageCount, maxSize = DEFAULT_MAX_SIZE, renderPageOverlay, className = "" }) {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const pageRefsRef = useRef([]); // stable per-page ref objects, index 0 = page 1
  const containerRefsRef = useRef([]); // the page wrapper DOM nodes, for IntersectionObserver
  const visibilityRef = useRef(new Map()); // pageNumber -> intersection ratio

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  useEffect(() => {
    if (!pageCount) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const pageNumber = Number(entry.target.dataset.pageNumber);
          visibilityRef.current.set(pageNumber, entry.isIntersecting ? entry.intersectionRatio : 0);
        }
        let bestPage = null;
        let bestRatio = 0;
        for (const [pageNumber, ratio] of visibilityRef.current) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestPage = pageNumber;
          }
        }
        if (bestPage) setCurrentPage(bestPage);
      },
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] }
    );
    containerRefsRef.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [fileId, pageCount]);

  if (!fileId || !pageCount) return null;

  function jumpToPage(n) {
    const clamped = Math.min(Math.max(1, n), pageCount);
    const el = containerRefsRef.current[clamped - 1];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    setCurrentPage(clamped);
  }

  function handlePageInputKeyDown(e) {
    if (e.key !== "Enter") return;
    const n = parseInt(pageInput, 10);
    if (!Number.isNaN(n)) jumpToPage(n);
    else setPageInput(String(currentPage));
  }

  const pages = Array.from({ length: pageCount }, (_, i) => i + 1);

  return (
    <div className={`page-scroll-viewer ${className}`}>
      <div className="page-scroll-viewer__header">
        Page{" "}
        <input
          type="text"
          inputMode="numeric"
          className="page-scroll-viewer__page-input"
          value={pageInput}
          onChange={(e) => setPageInput(e.target.value)}
          onKeyDown={handlePageInputKeyDown}
          onBlur={() => setPageInput(String(currentPage))}
        />{" "}
        of {pageCount}
      </div>
      <div className="page-scroll-viewer__scroll">
        {pages.map((pageNumber) => {
          if (!pageRefsRef.current[pageNumber - 1]) pageRefsRef.current[pageNumber - 1] = { current: null };
          const pageRef = pageRefsRef.current[pageNumber - 1];
          return (
            <div
              key={pageNumber}
              ref={(el) => {
                containerRefsRef.current[pageNumber - 1] = el;
              }}
              data-page-number={pageNumber}
              className="page-scroll-viewer__page"
            >
              <div
                ref={(el) => {
                  pageRef.current = el;
                }}
                className="page-scroll-viewer__page-inner"
              >
                <img
                  className="page-scroll-viewer__image"
                  src={thumbnailUrl(fileId, pageNumber, maxSize)}
                  alt={`Page ${pageNumber} preview`}
                  draggable={false}
                />
                {renderPageOverlay && renderPageOverlay(pageNumber, pageRef)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

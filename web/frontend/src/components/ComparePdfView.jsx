import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { uploadFile, comparePdf, fetchCompareVisual } from "../api";

export default function ComparePdfView() {
  const navigate = useNavigate();
  const [fileA, setFileA] = useState(null);
  const [fileB, setFileB] = useState(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null); // { page_count_a, page_count_b, pages }
  const [visualByPage, setVisualByPage] = useState({}); // pageNum -> data | "loading"
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const containerRefsRef = useRef([]);
  const visibilityRef = useRef(new Map());
  const fetchedRef = useRef(new Set());

  async function handlePick(which, e) {
    setError("");
    const file = e.target.files[0];
    if (!file) return;
    try {
      const uploaded = await uploadFile(file);
      if (which === "a") setFileA(uploaded);
      else setFileB(uploaded);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleCompare() {
    setError("");
    setResult(null);
    setVisualByPage({});
    fetchedRef.current = new Set();
    try {
      const data = await comparePdf(fileA.id, fileB.id);
      setResult(data);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  useEffect(() => {
    if (!result) return;
    const totalPages = result.pages.length;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const pageNumber = Number(entry.target.dataset.pageNumber);
          visibilityRef.current.set(pageNumber, entry.isIntersecting ? entry.intersectionRatio : 0);
          if (entry.isIntersecting && !fetchedRef.current.has(pageNumber)) {
            const page = result.pages[pageNumber - 1];
            if (page.has_counterpart) {
              fetchedRef.current.add(pageNumber);
              setVisualByPage((v) => ({ ...v, [pageNumber]: "loading" }));
              fetchCompareVisual(fileA.id, fileB.id, pageNumber)
                .then((data) => setVisualByPage((v) => ({ ...v, [pageNumber]: data })))
                .catch((err) => setVisualByPage((v) => ({ ...v, [pageNumber]: { error: err.message } })));
            }
          }
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
    containerRefsRef.current.slice(0, totalPages).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [result, fileA, fileB]);

  function jumpToPage(n) {
    if (!result) return;
    const clamped = Math.min(Math.max(1, n), result.pages.length);
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

  function renderTextDiff(entries) {
    return (
      <div className="compare-pdf__text-diff">
        {entries.map((entry, i) => (
          <div key={i} className={`compare-pdf__diff-line compare-pdf__diff-line--${entry.op}`}>
            {entry.text || " "}
          </div>
        ))}
      </div>
    );
  }

  function renderVisual(pageNumber) {
    const data = visualByPage[pageNumber];
    if (!data) return null;
    if (data === "loading") return <p className="compare-pdf__visual-status">Loading visual diff…</p>;
    if (data.error) return <p className="compare-pdf__visual-status">{data.error}</p>;
    return (
      <div className="compare-pdf__visual-pair">
        {[data.image_a, data.image_b].map((src, i) => (
          <div key={i} className="compare-pdf__visual-image-wrap">
            <img src={src} alt={`Page ${pageNumber}, document ${i === 0 ? "A" : "B"}`} />
            {data.boxes.map((box, bi) => (
              <div
                key={bi}
                className="compare-pdf__diff-box"
                style={{
                  left: `${box.x0 * 100}%`,
                  top: `${box.y0 * 100}%`,
                  width: `${(box.x1 - box.x0) * 100}%`,
                  height: `${(box.y1 - box.y0) * 100}%`,
                }}
              />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="compare-pdf">
      <button className="tool-view__back" onClick={() => navigate("/")}>
        <ArrowLeft size={16} weight="bold" />
        Back
      </button>
      <h1>Compare PDF</h1>

      <div className="compare-pdf__pickers">
        <label className="tool-view__upload">
          <UploadSimple size={18} weight="regular" />
          {fileA ? fileA.filename : "Choose the first PDF…"}
          <input type="file" accept=".pdf" onChange={(e) => handlePick("a", e)} />
        </label>
        <label className="tool-view__upload">
          <UploadSimple size={18} weight="regular" />
          {fileB ? fileB.filename : "Choose the second PDF…"}
          <input type="file" accept=".pdf" onChange={(e) => handlePick("b", e)} />
        </label>
        <button className="run-button" disabled={!fileA || !fileB} onClick={handleCompare}>
          Compare
        </button>
      </div>

      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      {result && (
        <div className="compare-pdf__viewer">
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
            of {result.pages.length}
          </div>
          <div className="page-scroll-viewer__scroll">
            {result.pages.map((page, i) => {
              const pageNumber = i + 1;
              return (
                <div
                  key={pageNumber}
                  ref={(el) => {
                    containerRefsRef.current[pageNumber - 1] = el;
                  }}
                  data-page-number={pageNumber}
                  className="page-scroll-viewer__page compare-pdf__page"
                >
                  {page.has_counterpart ? (
                    <>
                      {renderTextDiff(page.text_diff)}
                      {renderVisual(pageNumber)}
                    </>
                  ) : (
                    <p className="compare-pdf__added-removed">
                      {pageNumber <= result.page_count_a && pageNumber > result.page_count_b
                        ? "Page removed (only in the first document)"
                        : "Page added (only in the second document)"}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

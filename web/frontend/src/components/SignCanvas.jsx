import { useEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight, PencilSimple, UploadSimple, X } from "@phosphor-icons/react";
import { thumbnailUrl, uploadFile } from "../api";

const PREVIEW_MAX_SIZE = 700;
const PAD_WIDTH = 400;
const PAD_HEIGHT = 150;
const SIGNATURE_STORAGE_KEY = "pdf-editor-saved-signature";
const DEFAULT_WIDTH_FRACTION = 0.25;
const MAX_HEIGHT_FRACTION = 0.9;

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function dataUrlToFile(dataUrl, filename) {
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  return new File([blob], filename, { type: blob.type || "image/png" });
}

function loadImageNaturalSizeFromDataUrl(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.onerror = () => reject(new Error("Could not load this image."));
    img.src = dataUrl;
  });
}

export default function SignCanvas({ fileId, pageCount, onChange }) {
  const stageRef = useRef(null);
  const padCanvasRef = useRef(null);
  const isDrawingRef = useRef(false);
  const dragRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [placements, setPlacements] = useState([]);
  const [signatureFileId, setSignatureFileId] = useState(null);
  const [signatureNaturalSize, setSignatureNaturalSize] = useState(null);
  const [signaturePreviewSrc, setSignaturePreviewSrc] = useState(null);
  const [savedSignature, setSavedSignature] = useState(null);
  const [drawing, setDrawing] = useState(false);
  const [padHasDrawing, setPadHasDrawing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    onChange(placements);
  }, [placements]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(SIGNATURE_STORAGE_KEY);
      if (saved) setSavedSignature(saved);
    } catch {
      // localStorage unavailable (quota, private browsing) — just don't offer reuse.
    }
  }, []);

  useEffect(() => {
    if (drawing) initPad();
  }, [drawing]);

  if (!fileId || !pageCount) return null;

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

  async function useSignature(dataUrl, { persist }) {
    setError("");
    try {
      const file = await dataUrlToFile(dataUrl, "signature.png");
      const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSizeFromDataUrl(dataUrl)]);
      setSignatureFileId(uploaded.id);
      setSignatureNaturalSize(naturalSize);
      setSignaturePreviewSrc(dataUrl);
      if (persist) {
        try {
          localStorage.setItem(SIGNATURE_STORAGE_KEY, dataUrl);
          setSavedSignature(dataUrl);
        } catch {
          // localStorage unavailable/quota exceeded — signature still works this session.
        }
      }
      return true;
    } catch (err) {
      setError("Could not use this signature: " + err.message);
      return false;
    }
  }

  async function handleUploadFileSelected(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const dataUrl = await readFileAsDataUrl(file);
      await useSignature(dataUrl, { persist: true });
    } catch (err) {
      setError("Could not read this image: " + err.message);
    }
  }

  function initPad() {
    const canvas = padCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#000000";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
  }

  function padPointFromEvent(e) {
    const canvas = padCanvasRef.current;
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function handlePadMouseDown(e) {
    isDrawingRef.current = true;
    setPadHasDrawing(true);
    const ctx = padCanvasRef.current.getContext("2d");
    const { x, y } = padPointFromEvent(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
  }

  function handlePadMouseMove(e) {
    if (!isDrawingRef.current) return;
    const ctx = padCanvasRef.current.getContext("2d");
    const { x, y } = padPointFromEvent(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  }

  function handlePadMouseUp() {
    isDrawingRef.current = false;
  }

  function handlePadClear() {
    initPad();
    setPadHasDrawing(false);
  }

  async function handlePadSave() {
    if (!padHasDrawing) {
      setError("Draw a signature first.");
      return;
    }
    const dataUrl = padCanvasRef.current.toDataURL("image/png");
    const ok = await useSignature(dataUrl, { persist: true });
    if (ok) setDrawing(false);
  }

  function handleStagePlace(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    const width = DEFAULT_WIDTH_FRACTION;
    const height = Math.min(MAX_HEIGHT_FRACTION, width * (signatureNaturalSize.height / signatureNaturalSize.width));
    const x = Math.min(Math.max(point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(point.y - height / 2, 0), 1 - height);
    setPlacements((prev) => [
      ...prev,
      { id: newElementId(), type: "image", page: currentPage, file_id: signatureFileId, x, y, width, height },
    ]);
  }

  function removePlacement(id) {
    setPlacements((prev) => prev.filter((p) => p.id !== id));
  }

  function startDrag(placement, mode, e) {
    e.stopPropagation();
    const point = pointFromEvent(e);
    if (!point) return;
    dragRef.current = { id: placement.id, mode, start: point, startPlacement: { ...placement } };
    window.addEventListener("mousemove", handleDragMove);
    window.addEventListener("mouseup", handleDragEnd);
    window.addEventListener("blur", handleDragEnd);
  }

  function handleDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(e);
    if (!point) return;
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    const { startPlacement } = drag;
    let updated;
    if (drag.mode === "move") {
      const x = Math.min(Math.max(startPlacement.x + dx, 0), 1 - startPlacement.width);
      const y = Math.min(Math.max(startPlacement.y + dy, 0), 1 - startPlacement.height);
      updated = { ...startPlacement, x, y };
    } else {
      const aspect = startPlacement.height / startPlacement.width;
      const widthCap = Math.min(1 - startPlacement.x, (1 - startPlacement.y) / aspect);
      const desiredWidth = Math.max(0.05, startPlacement.width + dx);
      const width = Math.min(desiredWidth, widthCap);
      const height = width * aspect;
      updated = { ...startPlacement, width, height };
    }
    setPlacements((prev) => prev.map((p) => (p.id === drag.id ? updated : p)));
  }

  function handleDragEnd() {
    window.removeEventListener("mousemove", handleDragMove);
    window.removeEventListener("mouseup", handleDragEnd);
    window.removeEventListener("blur", handleDragEnd);
    dragRef.current = null;
  }

  function useDifferentSignature() {
    setSignatureFileId(null);
    setSignatureNaturalSize(null);
    setSignaturePreviewSrc(null);
    setPlacements([]);
  }

  const markedPageCount = new Set(placements.map((p) => p.page)).size;

  return (
    <div className="sign-canvas">
      {error && <p className="sign-canvas__error">{error}</p>}

      {!signatureFileId && (
        <div className="sign-canvas__source-panel">
          {savedSignature && (
            <div className="sign-canvas__saved">
              <img src={savedSignature} alt="Saved signature" className="sign-canvas__saved-preview" />
              <button type="button" onClick={() => useSignature(savedSignature, { persist: false })}>
                Use saved signature
              </button>
            </div>
          )}
          <div className="sign-canvas__source-actions">
            <button type="button" onClick={() => setDrawing((d) => !d)}>
              <PencilSimple size={16} weight="regular" />
              Draw new
            </button>
            <label className="sign-canvas__upload">
              <UploadSimple size={16} weight="regular" />
              Upload new
              <input type="file" accept="image/png,image/jpeg" onChange={handleUploadFileSelected} style={{ display: "none" }} />
            </label>
          </div>
          {drawing && (
            <div className="sign-canvas__pad">
              <canvas
                ref={padCanvasRef}
                width={PAD_WIDTH}
                height={PAD_HEIGHT}
                className="sign-canvas__pad-canvas"
                onMouseDown={handlePadMouseDown}
                onMouseMove={handlePadMouseMove}
                onMouseUp={handlePadMouseUp}
                onMouseLeave={handlePadMouseUp}
              />
              <div className="sign-canvas__pad-actions">
                <button type="button" onClick={handlePadClear}>
                  Clear
                </button>
                <button type="button" onClick={handlePadSave}>
                  Save signature
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {signatureFileId && (
        <>
          <div className="sign-canvas__nav">
            <button type="button" onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1}>
              <CaretLeft size={14} weight="bold" />
              Previous
            </button>
            <span>
              Page {currentPage} of {pageCount} ({markedPageCount} page{markedPageCount === 1 ? "" : "s"} signed)
            </span>
            <button type="button" onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))} disabled={currentPage === pageCount}>
              Next
              <CaretRight size={14} weight="bold" />
            </button>
          </div>

          <div ref={stageRef} className="sign-canvas__stage" onMouseDown={handleStagePlace}>
            <img
              className="sign-canvas__image"
              src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
              alt={`Page ${currentPage} preview — click to place your signature`}
              draggable={false}
            />
            {placements
              .filter((p) => p.page === currentPage)
              .map((p) => (
                <div
                  key={p.id}
                  className="sign-canvas__placement"
                  style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%`, width: `${p.width * 100}%`, height: `${p.height * 100}%` }}
                  onMouseDown={(e) => startDrag(p, "move", e)}
                >
                  <img src={signaturePreviewSrc} className="sign-canvas__placement-image" alt="Placed signature" draggable={false} />
                  <div className="sign-canvas__placement-handle" onMouseDown={(e) => startDrag(p, "resize", e)} />
                  <button
                    type="button"
                    className="sign-canvas__placement-remove"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={() => removePlacement(p.id)}
                    aria-label="Remove this signature"
                  >
                    <X size={12} weight="bold" />
                  </button>
                </div>
              ))}
          </div>

          <button type="button" className="sign-canvas__different" onClick={useDifferentSignature}>
            Use a different signature
          </button>
        </>
      )}
    </div>
  );
}

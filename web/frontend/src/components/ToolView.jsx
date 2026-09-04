import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  UploadSimple,
  FilePdf,
  FileImage,
  Play,
  CircleNotch,
  WarningCircle,
  CheckCircle,
  DownloadSimple,
  Info,
  Scissors,
} from "@phosphor-icons/react";
import { TOOL_CONFIGS } from "../toolConfigs";
import { uploadFile, runTool, downloadUrl } from "../api";
import { isImageFilename } from "../fileTypes";
import PageGrid from "./PageGrid";
import CropSelector from "./CropSelector";
import ImagePagePreview from "./ImagePagePreview";
import RedactSelector from "./RedactSelector";
import EditPdfCanvas from "./EditPdfCanvas";
import SignCanvas from "./SignCanvas";
import FormFillCanvas from "./FormFillCanvas";

// Number fields (e.g. split's "pages per file") must be a whole number no
// smaller than field.min — used by both the preview and the actual submitted
// request, so what the user sees before running always matches what Run does.
function clampNumberField(field, rawValue) {
  let n = Math.round(Number(rawValue));
  if (!Number.isFinite(n)) n = field.min ?? field.default ?? 0;
  if (field.min !== undefined) n = Math.max(field.min, n);
  return n;
}

function formatPageNumberPreview(format, pageNumber, total) {
  if (format === "number-of-total") return `${pageNumber} / ${total}`;
  if (format === "page-x-of-y") return `Page ${pageNumber} of ${total}`;
  return String(pageNumber);
}

export default function ToolView() {
  const { toolId } = useParams();
  const navigate = useNavigate();
  const config = TOOL_CONFIGS[toolId];

  const [files, setFiles] = useState([]);
  const [fieldValues, setFieldValues] = useState(() =>
    Object.fromEntries((config?.fields ?? []).map((f) => [f.name, f.default]))
  );
  const [selected, setSelected] = useState([]);
  const [order, setOrder] = useState(null);
  const [cropRect, setCropRect] = useState(null);
  const [redactions, setRedactions] = useState([]);
  const [elements, setElements] = useState([]);
  const [formValues, setFormValues] = useState([]);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!config) {
    return <p>Unknown tool.</p>;
  }

  async function handleFilePick(e) {
    setError("");
    setResult(null);
    const picked = Array.from(e.target.files);
    let accumulated = config.multiFile ? files : [];
    for (const file of picked) {
      try {
        const uploaded = await uploadFile(file);
        accumulated = config.multiFile ? [...accumulated, uploaded] : [uploaded];
        setFiles(accumulated);
        const primary = accumulated[0];
        if (primary) {
          setSelected([]);
          setCropRect(null);
          setRedactions([]);
          setElements([]);
          setFormValues([]);
          setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
          if (config.filenameSuffix && !fieldValues.filename) {
            setFieldValues((v) => ({
              ...v,
              filename: primary.filename.replace(/\.[^.]+$/, "") + config.filenameSuffix,
            }));
          }
        }
      } catch (err) {
        setError(err.message);
        return;
      }
    }
  }

  function updateField(name, value) {
    setFieldValues((v) => ({ ...v, [name]: value }));
  }

  async function handleRun() {
    setError("");
    setResult(null);
    if (config.preview === "crop" && !cropRect) {
      setError("Drag a box on the page preview to select the area to keep.");
      return;
    }
    if (config.preview === "redact" && redactions.length === 0) {
      setError("Draw at least one box on the page preview to mark an area for redaction.");
      return;
    }
    if (config.preview === "edit-pdf" && elements.length === 0) {
      setError("Add at least one edit on the page preview before running.");
      return;
    }
    if (config.preview === "sign" && elements.length === 0) {
      setError("Place at least one signature on the page preview before running.");
      return;
    }
    if (config.preview === "fill-form" && formValues.length === 0) {
      setError("Fill in at least one field before running.");
      return;
    }
    setBusy(true);
    try {
      const body = {};
      for (const field of config.fields) {
        const raw = field.type === "number" ? clampNumberField(field, fieldValues[field.name]) : fieldValues[field.name];
        body[field.name] = field.scale ? raw * field.scale : raw;
      }
      if (config.multiFile) {
        body.file_ids = files.map((f) => f.id);
      } else {
        body.file_id = files[0]?.id;
      }
      if (config.mode === "select") body.pages = selected;
      if (config.mode === "reorder") body.order = order;
      if (config.preview === "crop") Object.assign(body, cropRect);
      if (config.preview === "redact") body.redactions = redactions;
      if (config.preview === "edit-pdf" || config.preview === "sign") {
        body.elements = elements.map(({ id, ...rest }) => rest);
      }
      if (config.preview === "fill-form") {
        body.values = formValues;
      }
      const data = await runTool(config.endpoint, body);
      setResult(data.outputs);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const primaryFile = files[0];

  function renderPreview() {
    // Tools where a visual "before you run" preview isn't meaningful
    // (compress doesn't change appearance; PDF-to-Word can't be rendered
    // in a browser) get an explanatory note plus the plain input preview,
    // instead of a fabricated/misleading transform.
    if (config.previewNote) {
      return (
        <>
          <div className="preview-note">
            <Info size={16} weight="regular" />
            {config.previewNote}
          </div>
          {primaryFile && (
            <PageGrid fileId={primaryFile.id} pageCount={primaryFile.page_count} mode={config.mode} />
          )}
        </>
      );
    }

    if (config.preview === "merge") {
      if (files.length === 0) return null;
      return files.map((f, i) => (
        <div key={f.id} className="preview-group">
          <div className="preview-group__label">
            <FilePdf size={14} weight="fill" />
            {i + 1}. {f.filename} — this is where its pages land in the merged file
          </div>
          <PageGrid fileId={f.id} pageCount={f.page_count} mode="view" />
        </div>
      ));
    }

    if (config.preview === "split") {
      if (!primaryFile) return null;
      const step = clampNumberField(config.fields.find((f) => f.name === "pages_per_file"), fieldValues.pages_per_file);
      const total = primaryFile.page_count;
      const ranges = [];
      for (let start = 1; start <= total; start += step) {
        ranges.push([start, Math.min(start + step - 1, total)]);
      }
      return ranges.map(([start, end], i) => (
        <div key={`${start}-${end}`} className="preview-group">
          <div className="preview-group__label">
            <Scissors size={14} weight="regular" />
            Output file {i + 1} — page{start === end ? "" : "s"} {start === end ? start : `${start}–${end}`}
          </div>
          <PageGrid fileId={primaryFile.id} pageCount={total} mode="view" pageRange={[start, end]} />
        </div>
      ));
    }

    if (config.preview === "rotate") {
      if (!primaryFile) return null;
      const angle = Number(fieldValues.angle) || 0;
      return (
        <PageGrid fileId={primaryFile.id} pageCount={primaryFile.page_count} mode="view" rotateAngle={angle} />
      );
    }

    if (config.preview === "watermark") {
      if (!primaryFile) return null;
      const text = fieldValues.text?.trim();
      const opacity = fieldValues.opacity ?? 30;
      const fontSize = fieldValues.font_size ?? 40;
      const rotate = fieldValues.rotate ?? 0;
      return (
        <PageGrid
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          mode="view"
          overlay={
            text
              ? () => (
                  <span
                    className="page-thumb__watermark-preview"
                    style={{
                      opacity: opacity / 100,
                      fontSize: `${(fontSize / 595) * 100}cqw`,
                      transform: `rotate(${-rotate}deg)`,
                    }}
                  >
                    {text}
                  </span>
                )
              : undefined
          }
        />
      );
    }

    if (config.preview === "page-numbers") {
      if (!primaryFile) return null;
      const position = fieldValues.position ?? "bottom-center";
      const format = fieldValues.format ?? "number";
      const total = primaryFile.page_count;
      return (
        <PageGrid
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          mode="view"
          overlayPosition={position}
          overlay={(pageNumber) => (
            <span className="page-thumb__page-number-preview">
              {formatPageNumberPreview(format, pageNumber, total)}
            </span>
          )}
        />
      );
    }

    // Note is rendered inline here rather than via config.previewNote: that
    // mechanism short-circuits renderPreview() above and would replace the
    // interactive CropSelector with a plain thumbnail grid.
    if (config.preview === "crop") {
      if (!primaryFile) return null;
      return (
        <>
          <div className="preview-note">
            <Info size={16} weight="regular" />
            The box you draw on page 1 is applied to every page.
          </div>
          <CropSelector fileId={primaryFile.id} onChange={setCropRect} />
        </>
      );
    }

    if (config.preview === "images-to-pdf") {
      if (files.length === 0) return null;
      const fitMode = fieldValues.fit_mode ?? "fit";
      return files.map((f) => (
        <div key={f.id} className="preview-group">
          <div className="preview-group__label">
            {isImageFilename(f.filename) ? (
              <FileImage size={14} weight="fill" />
            ) : (
              <FilePdf size={14} weight="fill" />
            )}
            {f.filename}
          </div>
          <ImagePagePreview fileId={f.id} fitMode={fitMode} />
        </div>
      ));
    }

    if (config.preview === "redact") {
      if (!primaryFile) return null;
      return (
        // key={primaryFile.id} forces a full unmount/remount when the user picks
        // a different file, discarding RedactSelector's internal redactions and
        // currentPage state. Without it those boxes survive the file switch and
        // get applied to the NEW document, destroying unmarked content.
        <RedactSelector
          key={primaryFile.id}
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          onChange={setRedactions}
        />
      );
    }

    if (config.preview === "edit-pdf") {
      if (!primaryFile) return null;
      return (
        // key={primaryFile.id} forces a full remount on file switch, discarding
        // EditPdfCanvas's internal elements/history/selection state — the exact
        // fix Redact needed after shipping without it (see the Redact spec).
        <EditPdfCanvas key={primaryFile.id} fileId={primaryFile.id} pageCount={primaryFile.page_count} onChange={setElements} />
      );
    }

    if (config.preview === "sign") {
      if (!primaryFile) return null;
      return (
        // key={primaryFile.id}: same file-switch remount fix every selector-style
        // component in this app uses — discards SignCanvas's internal placements/
        // signature state on file switch instead of applying stale placements to
        // a newly-loaded document.
        <SignCanvas key={primaryFile.id} fileId={primaryFile.id} pageCount={primaryFile.page_count} onChange={setElements} />
      );
    }

    if (config.preview === "fill-form") {
      if (!primaryFile) return null;
      return (
        // key={primaryFile.id}: same file-switch remount fix every selector-style
        // component in this app uses — discards FormFillCanvas's internal fields/
        // values state on file switch instead of applying stale values to a
        // newly-loaded document.
        <FormFillCanvas key={primaryFile.id} fileId={primaryFile.id} pageCount={primaryFile.page_count} onChange={setFormValues} />
      );
    }

    // Default: select/reorder tools (Remove/Extract/Reorder pages) and
    // plain view-only tools (PDF to Image) — same as before this feature.
    if (!primaryFile) return null;
    return (
      <PageGrid
        fileId={primaryFile.id}
        pageCount={primaryFile.page_count}
        mode={config.mode}
        selected={selected}
        onToggle={(n) => setSelected((s) => (s.includes(n) ? s.filter((p) => p !== n) : [...s, n]))}
        order={order}
        onReorder={setOrder}
      />
    );
  }

  return (
    <div className="tool-view">
      <button className="tool-view__back" onClick={() => navigate("/")}>
        <ArrowLeft size={16} weight="bold" />
        Back
      </button>
      <h1>{config.title}</h1>

      <label className="tool-view__upload">
        <UploadSimple size={18} weight="regular" />
        {config.multiFile
          ? `Add ${config.fileTypeLabel ?? "PDF"} file(s)…`
          : `Choose a ${config.fileTypeLabel ?? "PDF"} file…`}
        <input
          type="file"
          accept={config.fileAccept ?? ".pdf"}
          multiple={config.multiFile}
          onChange={handleFilePick}
        />
      </label>

      {files.length > 0 && (
        <div className="tool-view__file-list">
          {files.map((f) => (
            <div key={f.id} className="tool-view__file-chip">
              {isImageFilename(f.filename) ? (
                <FileImage size={16} weight="fill" />
              ) : (
                <FilePdf size={16} weight="fill" />
              )}
              {f.filename} — {f.page_count} page{f.page_count === 1 ? "" : "s"}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      {renderPreview()}

      {config.fields.map((field) => (
        <label key={field.name} className="field">
          {field.label}
          {field.type === "select" ? (
            <select
              value={fieldValues[field.name]}
              onChange={(e) => {
                const raw = e.target.value;
                updateField(field.name, typeof field.default === "number" ? Number(raw) : raw);
              }}
            >
              {field.options.map((opt) => {
                const optValue = typeof opt === "object" ? opt.value : opt;
                const optLabel = typeof opt === "object" ? opt.label : opt;
                return (
                  <option key={optValue} value={optValue}>
                    {optLabel}
                  </option>
                );
              })}
            </select>
          ) : field.type === "range" ? (
            <input
              type="range"
              min={field.min}
              max={field.max}
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, Number(e.target.value))}
            />
          ) : field.type === "number" ? (
            <input
              type="number"
              min={field.min}
              step={1}
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, Number(e.target.value))}
            />
          ) : (
            <input
              type="text"
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, e.target.value)}
            />
          )}
        </label>
      ))}

      <button
        className="run-button"
        disabled={
          busy ||
          files.length === 0 ||
          (config.preview === "crop" && !cropRect) ||
          (config.preview === "redact" && redactions.length === 0) ||
          (config.preview === "edit-pdf" && elements.length === 0) ||
          (config.preview === "sign" && elements.length === 0) ||
          (config.preview === "fill-form" && formValues.length === 0)
        }
        onClick={handleRun}
      >
        {busy ? <CircleNotch size={17} weight="bold" className="spin" /> : <Play size={16} weight="fill" />}
        {busy ? "Working…" : "Run"}
      </button>

      {result && (
        <div className="result">
          <p className="result__title">
            <CheckCircle size={18} weight="fill" />
            Done — {result.length} file{result.length === 1 ? "" : "s"} created.
          </p>
          {result.map((out) => (
            <a key={out.id} href={downloadUrl(out.id)} download>
              <DownloadSimple size={16} weight="regular" />
              Download {out.filename}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

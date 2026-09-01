import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { TOOL_CONFIGS } from "../toolConfigs";
import { uploadFile, runTool, downloadUrl } from "../api";
import PageGrid from "./PageGrid";

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
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!config) {
    return <p>Unknown tool.</p>;
  }

  async function handleFilePick(e) {
    setError("");
    const picked = Array.from(e.target.files);
    try {
      const uploaded = [];
      for (const file of picked) {
        uploaded.push(await uploadFile(file));
      }
      const nextFiles = config.multiFile ? [...files, ...uploaded] : uploaded;
      setFiles(nextFiles);
      const primary = nextFiles[0];
      if (primary) {
        setSelected([]);
        setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
        if (config.fields.some((f) => f.name === "filename") && !fieldValues.filename) {
          setFieldValues((v) => ({
            ...v,
            filename: primary.filename.replace(/\.pdf$/i, "") + "_merged",
          }));
        }
      }
    } catch (err) {
      setError(err.message);
    }
  }

  function updateField(name, value) {
    setFieldValues((v) => ({ ...v, [name]: value }));
  }

  async function handleRun() {
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const body = {};
      for (const field of config.fields) {
        const raw = fieldValues[field.name];
        body[field.name] = field.scale ? raw * field.scale : raw;
      }
      if (config.multiFile) {
        body.file_ids = files.map((f) => f.id);
      } else {
        body.file_id = files[0]?.id;
      }
      if (config.mode === "select") body.pages = selected;
      if (config.mode === "reorder") body.order = order;
      const data = await runTool(config.endpoint, body);
      setResult(data.outputs);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const primaryFile = files[0];

  return (
    <div className="tool-view">
      <button onClick={() => navigate("/")}>&larr; Back</button>
      <h1>{config.title}</h1>

      <input type="file" accept=".pdf" multiple={config.multiFile} onChange={handleFilePick} />

      {error && <div className="banner banner--error">{error}</div>}

      {primaryFile && (
        <PageGrid
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          mode={config.mode}
          selected={selected}
          onToggle={(n) => setSelected((s) => (s.includes(n) ? s.filter((p) => p !== n) : [...s, n]))}
          order={order}
          onReorder={setOrder}
        />
      )}

      {config.fields.map((field) => (
        <label key={field.name} className="field">
          {field.label}
          {field.type === "select" ? (
            <select value={fieldValues[field.name]} onChange={(e) => updateField(field.name, e.target.value)}>
              {field.options.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
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

      <button disabled={busy || files.length === 0} onClick={handleRun}>
        {busy ? "Working…" : "Run"}
      </button>

      {result && (
        <div className="result">
          <p>Done — {result.length} file(s) created.</p>
          {result.map((out) => (
            <a key={out.id} href={downloadUrl(out.id)} download>
              Download {out.filename}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

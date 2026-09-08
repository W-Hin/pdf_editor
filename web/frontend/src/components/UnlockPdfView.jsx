import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  UploadSimple,
  Play,
  CircleNotch,
  WarningCircle,
  CheckCircle,
  DownloadSimple,
} from "@phosphor-icons/react";
import { unlockPdf, downloadUrl } from "../api";

export default function UnlockPdfView() {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  function handlePick(e) {
    setError("");
    setResult(null);
    setFile(e.target.files[0] ?? null);
  }

  async function handleUnlock() {
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const data = await unlockPdf(file, password);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tool-view">
      <button className="tool-view__back" onClick={() => navigate("/")}>
        <ArrowLeft size={16} weight="bold" />
        Back
      </button>
      <h1>Unlock PDF</h1>

      <label className="tool-view__upload">
        <UploadSimple size={18} weight="regular" />
        {file ? file.name : "Choose a password-protected PDF file…"}
        <input type="file" accept=".pdf" onChange={handlePick} />
      </label>

      <label className="field">
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>

      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      <button className="run-button" disabled={busy || !file || !password} onClick={handleUnlock}>
        {busy ? <CircleNotch size={17} weight="bold" className="spin" /> : <Play size={16} weight="fill" />}
        {busy ? "Working…" : "Unlock"}
      </button>

      {result && (
        <div className="result">
          <p className="result__title">
            <CheckCircle size={18} weight="fill" />
            Done — {result.outputs.length} file{result.outputs.length === 1 ? "" : "s"} created.
          </p>
          {result.outputs.map((out) => (
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

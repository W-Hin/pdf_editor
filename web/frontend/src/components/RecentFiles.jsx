import { useEffect, useState } from "react";
import { ClockCounterClockwise, FilePdf, FileDoc, FileImage, DownloadSimple, Trash, WarningCircle, Eye } from "@phosphor-icons/react";
import { fetchHistory, deleteHistoryEntry, downloadUrl, thumbnailUrl } from "../api";
import { isImageFilename } from "../fileTypes";
import PageScrollViewer from "./PageScrollViewer";

function coverPreviewSrc(entry) {
  const name = entry.filename.toLowerCase();
  if (name.endsWith(".pdf")) return thumbnailUrl(entry.id, 1);
  if (isImageFilename(name)) return downloadUrl(entry.id);
  return null; // no cheap preview possible (e.g. .docx) — fall back to an icon
}

function FallbackIcon({ filename }) {
  const name = filename.toLowerCase();
  if (name.endsWith(".docx")) return <FileDoc size={22} weight="fill" />;
  if (isImageFilename(name)) return <FileImage size={22} weight="fill" />;
  return <FilePdf size={22} weight="fill" />;
}

export default function RecentFiles() {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState("");
  const [failedPreviews, setFailedPreviews] = useState(() => new Set());
  const [expandedId, setExpandedId] = useState(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setEntries(await fetchHistory());
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    try {
      await deleteHistoryEntry(id);
      setEntries((prev) => prev.filter((e) => e.id !== id));
      setError("");
    } catch (err) {
      setError(err.message);
    }
  }

  function markPreviewFailed(id) {
    setFailedPreviews((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
  }

  return (
    <section id="recent-files" className="recent-files">
      <h2>Recent Files</h2>
      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}
      {entries.length === 0 && !error && (
        <div className="recent-files__empty">
          <ClockCounterClockwise size={40} weight="thin" />
          <p>No files produced yet.</p>
        </div>
      )}
      <ul className="history-list">
        {entries.map((entry) => {
          const previewSrc = !failedPreviews.has(entry.id) ? coverPreviewSrc(entry) : null;
          return (
            <li key={entry.id}>
              <div className="history-list__info">
                <div className="history-list__thumb">
                  {previewSrc ? (
                    <img
                      src={previewSrc}
                      alt=""
                      loading="lazy"
                      onError={() => markPreviewFailed(entry.id)}
                    />
                  ) : (
                    <FallbackIcon filename={entry.filename} />
                  )}
                </div>
                <div>
                  <div className="history-list__filename">{entry.filename}</div>
                  <div className="history-list__meta">
                    {entry.tool} — {entry.created_at}
                  </div>
                </div>
              </div>
              <div className="history-list__actions">
                {entry.page_count ? (
                  <button
                    className="icon-button"
                    onClick={() => setExpandedId((id) => (id === entry.id ? null : entry.id))}
                  >
                    <Eye size={15} weight="regular" />
                    {expandedId === entry.id ? "Hide preview" : "Preview"}
                  </button>
                ) : null}
                <a className="icon-button" href={downloadUrl(entry.id)} download>
                  <DownloadSimple size={15} weight="regular" />
                  Download
                </a>
                <button className="icon-button icon-button--danger" onClick={() => handleDelete(entry.id)}>
                  <Trash size={15} weight="regular" />
                  Delete
                </button>
              </div>
              {expandedId === entry.id && entry.page_count && (
                <div className="history-list__preview">
                  <PageScrollViewer fileId={entry.id} pageCount={entry.page_count} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

import { useEffect, useState } from "react";
import { ClockCounterClockwise, FilePdf, DownloadSimple, Trash, WarningCircle } from "@phosphor-icons/react";
import { fetchHistory, deleteHistoryEntry, downloadUrl } from "../api";

export default function RecentFiles() {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState("");

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

  return (
    <div className="recent-files">
      <h1>Recent Files</h1>
      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}
      {entries.length === 0 && (
        <div className="recent-files__empty">
          <ClockCounterClockwise size={40} weight="thin" />
          <p>No files produced yet.</p>
        </div>
      )}
      <ul className="history-list">
        {entries.map((entry) => (
          <li key={entry.id}>
            <div className="history-list__info">
              <FilePdf size={22} weight="fill" />
              <div>
                <div className="history-list__filename">{entry.filename}</div>
                <div className="history-list__meta">
                  {entry.tool} — {entry.created_at}
                </div>
              </div>
            </div>
            <div className="history-list__actions">
              <a className="icon-button" href={downloadUrl(entry.id)} download>
                <DownloadSimple size={15} weight="regular" />
                Download
              </a>
              <button className="icon-button icon-button--danger" onClick={() => handleDelete(entry.id)}>
                <Trash size={15} weight="regular" />
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

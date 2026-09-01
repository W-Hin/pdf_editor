import { useEffect, useState } from "react";
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
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    try {
      await deleteHistoryEntry(id);
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="recent-files">
      <h1>Recent Files</h1>
      {error && <div className="banner banner--error">{error}</div>}
      {entries.length === 0 && <p>No files produced yet.</p>}
      <ul className="history-list">
        {entries.map((entry) => (
          <li key={entry.id}>
            <div>
              <strong>{entry.filename}</strong>
              <div>
                {entry.tool} — {entry.created_at}
              </div>
            </div>
            <div>
              <a href={downloadUrl(entry.id)} download>
                Download
              </a>{" "}
              <button onClick={() => handleDelete(entry.id)}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

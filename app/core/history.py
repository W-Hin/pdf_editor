"""The desktop app's Recent Files list, kept in a small SQLite database.

Only metadata is stored (where the output is, which tool made it, when). The
PDFs themselves stay wherever the tool wrote them, so the database stays tiny
however big those files are. The list can therefore go stale: a file may be
moved or deleted later, which `exists` reports at read time rather than trusting
what was true when the row was written.
"""
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DATA_DIR_ENV = "PDF_EDITOR_DATA_DIR"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    tool TEXT NOT NULL,
    page_count INTEGER,
    size_bytes INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_created ON history (created_at DESC, id DESC);
"""


def default_db_path() -> Path:
    base = os.environ.get(DATA_DIR_ENV)
    if base:
        return Path(base) / "history.db"
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(root) / "PDFEditor" / "history.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def add_entry(path: str, tool: str, page_count: int | None = None, db_path: Path | None = None) -> None:
    file = Path(path)
    try:
        size = file.stat().st_size
    except OSError:
        size = None
    with closing(_connect(db_path or default_db_path())) as conn, conn:
        conn.execute(
            "INSERT INTO history (path, filename, tool, page_count, size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(file), file.name, tool, page_count, size, time.strftime("%Y-%m-%d %H:%M:%S")),
        )


def _search_clause(query: str) -> tuple[str, list[str]]:
    """Every word of the query must appear in the file name, the tool or the
    folder (case-insensitively), so "merge report" finds Merge PDF's report.pdf."""
    words = query.split()
    if not words:
        return "", []
    one = "(filename LIKE ? ESCAPE '\\' OR tool LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')"
    params: list[str] = []
    for word in words:
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like, like]
    return " WHERE " + " AND ".join([one] * len(words)), params


def list_entries(limit: int = 100, db_path: Path | None = None, query: str = "", offset: int = 0) -> list[dict]:
    """Newest first, optionally only those matching `query`. Each entry gains
    `exists`: whether the file is still there."""
    where, params = _search_clause(query)
    with closing(_connect(db_path or default_db_path())) as conn:
        rows = conn.execute(
            "SELECT * FROM history" + where + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    entries = [dict(row) for row in rows]
    for entry in entries:
        entry["exists"] = Path(entry["path"]).is_file()
    return entries


def count_entries(query: str = "", db_path: Path | None = None) -> int:
    where, params = _search_clause(query)
    with closing(_connect(db_path or default_db_path())) as conn:
        return conn.execute("SELECT COUNT(*) FROM history" + where, params).fetchone()[0]


def remove_entry(entry_id: int, db_path: Path | None = None) -> bool:
    """Forget an entry. The file itself is never touched."""
    with closing(_connect(db_path or default_db_path())) as conn, conn:
        return conn.execute("DELETE FROM history WHERE id = ?", (entry_id,)).rowcount > 0

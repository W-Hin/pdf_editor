import json
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path

UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf_editor_web_uploads"
OUTPUT_DIR = Path.home() / "Documents" / "PDF Editor Output"
# The old flat-file history. It is only READ, once, to import an existing history
# into the database (see _connect), and then renamed out of the way. The database
# lives beside it.
HISTORY_FILE = OUTPUT_DIR / "history.json"

_uploads: dict[str, dict] = {}


def save_upload(filename: str, content: bytes) -> dict:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:12]
    safe_name = Path(filename).name
    path = UPLOAD_DIR / f"{file_id}_{safe_name}"
    path.write_bytes(content)
    record = {"id": file_id, "filename": safe_name, "path": str(path)}
    _uploads[file_id] = record
    return record


_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    tool TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source_filenames TEXT NOT NULL DEFAULT '[]',
    page_count INTEGER
);
"""


def _db_path() -> Path:
    return HISTORY_FILE.with_name("history.db")


def _row_to_record(row: sqlite3.Row) -> dict:
    record = dict(row)
    del record["seq"]
    record["source_filenames"] = json.loads(record["source_filenames"] or "[]")
    return record


def _import_legacy_history(conn: sqlite3.Connection) -> None:
    """One-time import of the old history.json (newest first there, so it is
    inserted oldest first to keep the same order). The file is renamed rather
    than deleted, as a backup; an unreadable one is left alone and ignored."""
    if not HISTORY_FILE.exists():
        return
    try:
        records = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        rows = [
            (
                r["id"], r["filename"], r["path"], r["tool"], r["created_at"],
                json.dumps(r.get("source_filenames") or []), r.get("page_count"),
            )
            for r in reversed(records)
        ]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return
    conn.executemany(
        "INSERT OR IGNORE INTO history (id, filename, path, tool, created_at, source_filenames, page_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    try:
        HISTORY_FILE.replace(HISTORY_FILE.with_name(HISTORY_FILE.name + ".migrated"))
    except OSError:
        pass  # the rows are in; INSERT OR IGNORE makes a re-import harmless


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    if conn.execute("PRAGMA user_version").fetchone()[0] == 0:
        with conn:
            _import_legacy_history(conn)
            conn.execute("PRAGMA user_version = 1")
    return conn


def load_history() -> list[dict]:
    """Newest first."""
    try:
        with closing(_connect()) as conn:
            rows = conn.execute("SELECT * FROM history ORDER BY seq DESC").fetchall()
    except sqlite3.DatabaseError:
        return []  # an unreadable database shows an empty list rather than an error page
    return [_row_to_record(row) for row in rows]


def record_output(path: Path, tool: str, source_filenames: list[str], page_count: int | None = None) -> dict:
    record = {
        "id": uuid.uuid4().hex[:12],
        "filename": path.name,
        "path": str(path),
        "tool": tool,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_filenames": source_filenames,
        "page_count": page_count,
    }
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO history (id, filename, path, tool, created_at, source_filenames, page_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record["id"], record["filename"], record["path"], record["tool"], record["created_at"],
                json.dumps(source_filenames), page_count,
            ),
        )
    return record


def delete_output(file_id: str) -> bool:
    with closing(_connect()) as conn, conn:
        row = conn.execute("SELECT * FROM history WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM history WHERE id = ?", (file_id,))
    deleted_path = Path(row["path"])
    deleted_path.unlink(missing_ok=True)
    parent = deleted_path.parent
    try:
        if parent != OUTPUT_DIR and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass
    return True


def resolve_file(file_id: str) -> Path:
    if file_id in _uploads:
        return Path(_uploads[file_id]["path"])
    try:
        with closing(_connect()) as conn:
            row = conn.execute("SELECT path FROM history WHERE id = ?", (file_id,)).fetchone()
    except sqlite3.DatabaseError:
        row = None
    if row is not None:
        return Path(row["path"])
    raise FileNotFoundError(f"No file found for id '{file_id}'")


def _unique_output_stamp() -> str:
    # Wall-clock microseconds alone can collide: on some platforms (notably
    # Windows) time.time()'s effective resolution is much coarser than a
    # microsecond, so two calls made back-to-back can produce the same
    # timestamp. A short uuid suffix guarantees uniqueness regardless of
    # clock resolution, while the timestamp prefix stays for readability.
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def output_path_for(stem: str, suffix: str, ext: str = ".pdf") -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / f"{stem}{suffix}_{_unique_output_stamp()}{ext}"


def output_dir_for(stem: str, suffix: str) -> Path:
    out_dir = OUTPUT_DIR / f"{stem}{suffix}_{_unique_output_stamp()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir

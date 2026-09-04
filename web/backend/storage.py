import json
import tempfile
import time
import uuid
from pathlib import Path

UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf_editor_web_uploads"
OUTPUT_DIR = Path.home() / "Documents" / "PDF Editor Output"
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


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_history(records: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")


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
    records = load_history()
    records.insert(0, record)
    _save_history(records)
    return record


def delete_output(file_id: str) -> bool:
    records = load_history()
    remaining = [r for r in records if r["id"] != file_id]
    if len(remaining) == len(records):
        return False
    deleted = next(r for r in records if r["id"] == file_id)
    _save_history(remaining)
    deleted_path = Path(deleted["path"])
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
    for record in load_history():
        if record["id"] == file_id:
            return Path(record["path"])
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

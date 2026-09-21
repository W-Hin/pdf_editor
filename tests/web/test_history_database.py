import json
import sqlite3

from web.backend import storage


def _legacy_records(tmp_path, count=3):
    out = tmp_path / "output"
    out.mkdir(exist_ok=True)
    # history.json stored newest FIRST.
    records = [
        {
            "id": f"id{i}", "filename": f"file{i}.pdf", "path": str(out / f"file{i}.pdf"), "tool": "Merge PDF",
            "created_at": f"2026-09-0{i + 1} 10:00:00", "source_filenames": [f"src{i}.pdf"], "page_count": i,
        }
        for i in reversed(range(count))
    ]
    (out / "history.json").write_text(json.dumps(records), encoding="utf-8")
    return records


def test_history_is_stored_in_a_sqlite_database_beside_the_old_file(tmp_path):
    (tmp_path / "output").mkdir()
    storage.record_output(tmp_path / "output" / "a.pdf", "Rotate PDF", ["in.pdf"], page_count=4)
    db = tmp_path / "output" / "history.db"
    assert db.exists()
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT filename, tool, page_count FROM history").fetchall()
    assert rows == [("a.pdf", "Rotate PDF", 4)]


def test_record_shape_is_unchanged_for_the_routes_and_frontend(tmp_path):
    record = storage.record_output(tmp_path / "output" / "a.pdf", "Merge PDF", ["x.pdf", "y.pdf"], page_count=2)
    assert set(record) == {"id", "filename", "path", "tool", "created_at", "source_filenames", "page_count"}
    loaded = storage.load_history()[0]
    assert loaded == record
    assert loaded["source_filenames"] == ["x.pdf", "y.pdf"]


def test_an_existing_history_json_is_imported_once_in_the_same_order(tmp_path):
    records = _legacy_records(tmp_path)
    loaded = storage.load_history()
    assert loaded == records  # same records, still newest first
    out = tmp_path / "output"
    assert not (out / "history.json").exists()
    assert (out / "history.json.migrated").exists()  # kept as a backup, not deleted
    assert storage.load_history() == records  # a second read does not import again


def test_the_import_does_not_repeat_or_duplicate_when_the_old_file_reappears(tmp_path):
    records = _legacy_records(tmp_path)
    storage.load_history()
    _legacy_records(tmp_path)  # someone drops a history.json back in
    assert storage.load_history() == records  # the database is already migrated: ignored


def test_new_entries_go_on_top_of_imported_ones(tmp_path):
    _legacy_records(tmp_path, count=2)
    fresh = storage.record_output(tmp_path / "output" / "new.pdf", "Compress PDF", ["a.pdf"])
    history = storage.load_history()
    assert [r["id"] for r in history] == [fresh["id"], "id1", "id0"]


def test_an_unreadable_history_json_is_ignored_and_left_alone(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "history.json").write_text("{ not valid json", encoding="utf-8")
    assert storage.load_history() == []
    assert (out / "history.json").exists()  # not renamed or deleted
    storage.record_output(out / "a.pdf", "Rotate PDF", ["in.pdf"])
    assert len(storage.load_history()) == 1


def test_a_legacy_record_with_missing_optional_fields_still_imports(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "history.json").write_text(json.dumps([
        {"id": "old1", "filename": "o.pdf", "path": str(out / "o.pdf"), "tool": "Merge PDF", "created_at": "2026-01-01 00:00:00"},
    ]), encoding="utf-8")
    loaded = storage.load_history()
    assert loaded[0]["source_filenames"] == [] and loaded[0]["page_count"] is None


def test_resolve_file_finds_a_recorded_output_by_id(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    record = storage.record_output(out / "a.pdf", "Rotate PDF", ["in.pdf"])
    assert storage.resolve_file(record["id"]) == out / "a.pdf"


def test_resolve_file_for_an_unknown_id_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        storage.resolve_file("nope")


def test_delete_output_removes_the_row_and_the_file(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    path = out / "a.pdf"
    path.write_bytes(b"x")
    record = storage.record_output(path, "Rotate PDF", ["in.pdf"])
    assert storage.delete_output(record["id"]) is True
    assert storage.load_history() == [] and not path.exists()
    assert storage.delete_output(record["id"]) is False


def test_names_with_quotes_and_unicode_round_trip(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    name = "o'brien \"report\" — résumé.pdf"
    record = storage.record_output(out / name, "Merge PDF", [name, "b'.pdf"])
    loaded = storage.load_history()[0]
    assert loaded["filename"] == name and loaded["source_filenames"] == [name, "b'.pdf"]
    assert loaded["id"] == record["id"]


def test_a_large_history_stays_quick_to_add_to_and_list(tmp_path):
    import time

    out = tmp_path / "output"
    out.mkdir()
    for i in range(2000):
        storage.record_output(out / f"f{i}.pdf", "Merge PDF", ["a.pdf"])
    start = time.perf_counter()
    storage.record_output(out / "one_more.pdf", "Merge PDF", ["a.pdf"])
    history = storage.load_history()
    elapsed = time.perf_counter() - start
    assert len(history) == 2001 and history[0]["filename"] == "one_more.pdf"
    assert elapsed < 2.0  # the old flat file rewrote every record on each save


def test_a_corrupt_database_reads_as_empty_instead_of_an_error(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "history.db").write_bytes(b"this is not a sqlite database at all" * 20)
    assert storage.load_history() == []

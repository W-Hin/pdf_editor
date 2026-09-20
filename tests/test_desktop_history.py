from pathlib import Path

from app.core import history


def _db(tmp_path):
    return tmp_path / "h.db"


def test_entries_come_back_newest_first_with_their_details(tmp_path):
    a = tmp_path / "a.pdf"
    a.write_bytes(b"12345")
    b = tmp_path / "b.pdf"
    b.write_bytes(b"1")
    history.add_entry(str(a), "Merge PDF", page_count=3, db_path=_db(tmp_path))
    history.add_entry(str(b), "Rotate PDF", db_path=_db(tmp_path))
    entries = history.list_entries(db_path=_db(tmp_path))
    assert [e["filename"] for e in entries] == ["b.pdf", "a.pdf"]
    assert entries[1]["tool"] == "Merge PDF"
    assert entries[1]["page_count"] == 3
    assert entries[1]["size_bytes"] == 5
    assert entries[0]["page_count"] is None


def test_exists_reflects_the_disk_at_read_time(tmp_path):
    f = tmp_path / "gone.pdf"
    f.write_bytes(b"x")
    history.add_entry(str(f), "Merge PDF", db_path=_db(tmp_path))
    assert history.list_entries(db_path=_db(tmp_path))[0]["exists"] is True
    f.unlink()
    assert history.list_entries(db_path=_db(tmp_path))[0]["exists"] is False


def test_remove_forgets_the_entry_but_keeps_the_file(tmp_path):
    f = tmp_path / "keep.pdf"
    f.write_bytes(b"x")
    history.add_entry(str(f), "Merge PDF", db_path=_db(tmp_path))
    entry = history.list_entries(db_path=_db(tmp_path))[0]
    assert history.remove_entry(entry["id"], db_path=_db(tmp_path)) is True
    assert history.list_entries(db_path=_db(tmp_path)) == []
    assert f.exists()
    assert history.remove_entry(entry["id"], db_path=_db(tmp_path)) is False


def test_limit_caps_how_many_come_back(tmp_path):
    for i in range(5):
        history.add_entry(str(tmp_path / f"{i}.pdf"), "Merge PDF", db_path=_db(tmp_path))
    assert len(history.list_entries(limit=3, db_path=_db(tmp_path))) == 3


def test_paths_with_quotes_and_unicode_round_trip(tmp_path):
    name = "o'brien \"report\" — résumé.pdf"
    history.add_entry(str(tmp_path / name), "Merge PDF", db_path=_db(tmp_path))
    assert history.list_entries(db_path=_db(tmp_path))[0]["filename"] == name


def test_default_path_follows_the_data_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_EDITOR_DATA_DIR", str(tmp_path / "x"))
    assert history.default_db_path() == Path(tmp_path / "x" / "history.db")
    history.add_entry(str(tmp_path / "f.pdf"), "Merge PDF")
    assert (tmp_path / "x" / "history.db").exists()

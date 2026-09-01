from pathlib import Path

import pytest


@pytest.fixture
def storage():
    from web.backend import storage as storage_module
    return storage_module


def test_save_upload_creates_file_and_record(storage):
    record = storage.save_upload("report.pdf", b"%PDF-1.4 fake content")

    assert record["filename"] == "report.pdf"
    assert Path(record["path"]).exists()
    assert Path(record["path"]).read_bytes() == b"%PDF-1.4 fake content"
    assert storage.resolve_file(record["id"]) == Path(record["path"])


def test_resolve_file_unknown_id_raises(storage):
    with pytest.raises(FileNotFoundError):
        storage.resolve_file("does-not-exist")


def test_record_output_appends_to_history_newest_first(storage, tmp_path):
    path_a = tmp_path / "a.pdf"
    path_a.write_text("a")
    path_b = tmp_path / "b.pdf"
    path_b.write_text("b")

    storage.record_output(path_a, "Merge PDF", ["x.pdf", "y.pdf"])
    record_b = storage.record_output(path_b, "Compress PDF", ["a.pdf"])

    history = storage.load_history()
    assert len(history) == 2
    assert history[0]["id"] == record_b["id"]
    assert history[0]["tool"] == "Compress PDF"
    assert history[0]["source_filenames"] == ["a.pdf"]
    assert storage.resolve_file(record_b["id"]) == path_b


def test_delete_output_removes_record_and_file(storage, tmp_path):
    path = tmp_path / "out.pdf"
    path.write_text("data")
    record = storage.record_output(path, "Rotate PDF", ["in.pdf"])

    deleted = storage.delete_output(record["id"])

    assert deleted is True
    assert storage.load_history() == []
    assert not path.exists()


def test_delete_output_unknown_id_returns_false(storage):
    assert storage.delete_output("nope") is False


def test_output_path_for_is_unique_across_calls(storage):
    first = storage.output_path_for("report", "_merged")
    second = storage.output_path_for("report", "_merged")

    assert first != second
    assert first.name.startswith("report_merged_")
    assert first.suffix == ".pdf"


def test_output_dir_for_creates_a_fresh_directory(storage):
    out_dir = storage.output_dir_for("report", "_split")

    assert out_dir.exists()
    assert out_dir.is_dir()
    assert out_dir.name.startswith("report_split_")

import pytest


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    # Import deferred into function body: pytest loads conftest at module level in the
    # tests/web namespace when tests/web/__init__.py exists. Top-level imports would fail
    # because the relative import resolution differs. The project root is already on
    # sys.path via pytest.ini's pythonpath=., so this late import works reliably.
    from web.backend import storage

    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(storage, "HISTORY_FILE", tmp_path / "output" / "history.json")
    storage._uploads.clear()
    yield
    storage._uploads.clear()

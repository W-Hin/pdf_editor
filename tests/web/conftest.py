import sys
from pathlib import Path

import pytest



@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    from web.backend import storage

    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(storage, "HISTORY_FILE", tmp_path / "output" / "history.json")
    storage._uploads.clear()
    yield
    storage._uploads.clear()

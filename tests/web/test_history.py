from fastapi.testclient import TestClient

from web.backend import storage
from web.backend.main import app

client = TestClient(app)


def test_history_empty_by_default():
    response = client.get("/api/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_lists_recorded_outputs(tmp_path):
    path = tmp_path / "out.pdf"
    path.write_text("data")
    storage.record_output(path, "Compress PDF", ["in.pdf"])

    response = client.get("/api/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["tool"] == "Compress PDF"


def test_delete_history_entry_removes_it(tmp_path):
    path = tmp_path / "out.pdf"
    path.write_text("data")
    record = storage.record_output(path, "Rotate PDF", ["in.pdf"])

    response = client.delete(f"/api/history/{record['id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": record["id"]}
    assert client.get("/api/history").json() == []


def test_delete_unknown_history_entry_returns_404():
    response = client.delete("/api/history/nope")
    assert response.status_code == 404

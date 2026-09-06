import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _upload_pdf(num_pages=1):
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return client.post(
        "/api/files", files={"file": ("sample.pdf", data, "application/pdf")}
    ).json()


def test_repair_reports_healthy_message():
    upload = _upload_pdf(num_pages=3)
    response = client.post("/api/tools/repair", json={"file_id": upload["id"]})
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1
    assert "healthy" in data["message"].lower()
    assert "3" in data["message"]


def test_protect_encrypts_with_password():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/protect", json={"file_id": upload["id"], "password": "mypassword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1


def test_protect_rejects_empty_password():
    upload = _upload_pdf()
    response = client.post("/api/tools/protect", json={"file_id": upload["id"], "password": ""})
    assert response.status_code == 422

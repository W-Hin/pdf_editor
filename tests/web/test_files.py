import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _make_pdf_bytes(num_pages=2):
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_returns_id_filename_and_page_count():
    pdf_bytes = _make_pdf_bytes(num_pages=3)

    response = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "sample.pdf"
    assert data["page_count"] == 3
    assert data["id"]


def test_upload_invalid_pdf_returns_422():
    response = client.post(
        "/api/files", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    )

    assert response.status_code == 422
    assert "detail" in response.json()


def test_thumbnail_returns_png():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/pages/1/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_thumbnail_unknown_file_id_returns_404():
    response = client.get("/api/files/nope/pages/1/thumbnail")
    assert response.status_code == 404


def test_download_returns_file_content():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/download")

    assert response.status_code == 200
    assert response.content == pdf_bytes


def test_download_unknown_file_id_returns_404():
    response = client.get("/api/files/nope/download")
    assert response.status_code == 404

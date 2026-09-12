import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _upload_image_only_pdf(text="Route test OCR content."):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), text, fontsize=14)
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    pdf_bytes = scanned.tobytes()
    scanned.close()
    doc.close()
    response = client.post("/api/files", files={"file": ("scan.pdf", pdf_bytes, "application/pdf")})
    return response.json()["id"]


def test_ocr_route_returns_success_message():
    file_id = _upload_image_only_pdf()
    response = client.post("/api/tools/ocr", json={"file_id": file_id, "languages": ["eng"], "convert_to_pdfa": False})
    assert response.status_code == 200
    data = response.json()
    assert "OCR'd" in data["message"]
    assert len(data["outputs"]) == 1


def test_ocr_route_rejects_empty_languages():
    file_id = _upload_image_only_pdf()
    response = client.post("/api/tools/ocr", json={"file_id": file_id, "languages": [], "convert_to_pdfa": False})
    assert response.status_code == 422


def test_pdf_to_pdfa_route_succeeds():
    file_id = _upload_image_only_pdf()
    response = client.post("/api/tools/pdf-to-pdfa", json={"file_id": file_id})
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_ocr_route_rejects_encrypted_file_with_422_not_500():
    # Reproduces the reviewer's exact repro: run a plain PDF through Protect
    # to get a genuinely-encrypted output, then submit that output's id to
    # the OCR route (storage.resolve_file accepts any existing output's id
    # for any tool route). Before the fix, _count_pages_with_text's bare
    # fitz.open() let PyMuPDF's exception escape unwrapped as a raw 500.
    file_id = _upload_image_only_pdf()
    protect_response = client.post("/api/tools/protect", json={"file_id": file_id, "password": "hunter2"})
    assert protect_response.status_code == 200
    encrypted_id = protect_response.json()["outputs"][0]["id"]

    response = client.post(
        "/api/tools/ocr", json={"file_id": encrypted_id, "languages": ["eng"], "convert_to_pdfa": False}
    )

    assert response.status_code == 422
    assert "password-protected" in response.json()["detail"]

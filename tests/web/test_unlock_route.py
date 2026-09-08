import fitz
import pikepdf
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _make_encrypted_pdf_bytes(password="secret123", num_pages=3):
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page()
    plain_bytes = doc.tobytes()
    doc.close()

    import io

    pdf = pikepdf.open(io.BytesIO(plain_bytes))
    buf = io.BytesIO()
    pdf.save(buf, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    pdf.close()
    return buf.getvalue()


def test_unlock_with_correct_password_succeeds():
    encrypted_bytes = _make_encrypted_pdf_bytes(password="secret123", num_pages=3)
    response = client.post(
        "/api/tools/unlock",
        files={"file": ("locked.pdf", encrypted_bytes, "application/pdf")},
        data={"password": "secret123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1


def test_unlock_with_wrong_password_fails():
    encrypted_bytes = _make_encrypted_pdf_bytes(password="secret123", num_pages=3)
    response = client.post(
        "/api/tools/unlock",
        files={"file": ("locked.pdf", encrypted_bytes, "application/pdf")},
        data={"password": "wrong"},
    )
    assert response.status_code == 422
    assert "path" not in response.json()["detail"].lower()


def test_unlock_with_non_encrypted_file_passes_through_cleanly():
    doc = fitz.open()
    doc.new_page()
    plain_bytes = doc.tobytes()
    doc.close()
    response = client.post(
        "/api/tools/unlock",
        files={"file": ("plain.pdf", plain_bytes, "application/pdf")},
        data={"password": "irrelevant"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1

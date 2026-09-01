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


def test_rotate_returns_one_output():
    upload = _upload_pdf()
    response = client.post("/api/tools/rotate", json={"file_id": upload["id"], "angle": 90})
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_rotate_rejects_non_multiple_of_90():
    upload = _upload_pdf()
    response = client.post("/api/tools/rotate", json={"file_id": upload["id"], "angle": 45})
    assert response.status_code == 422


def test_watermark_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/watermark", json={"file_id": upload["id"], "text": "DRAFT", "opacity": 0.3}
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_watermark_rejects_empty_text():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/watermark", json={"file_id": upload["id"], "text": "  ", "opacity": 0.3}
    )
    assert response.status_code == 422


def test_compress_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/compress", json={"file_id": upload["id"], "image_quality": 50}
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_to_images_returns_one_output_per_page():
    upload = _upload_pdf(num_pages=3)
    response = client.post(
        "/api/tools/to-images", json={"file_id": upload["id"], "image_format": "png"}
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 3


def test_to_word_returns_one_output():
    upload = _upload_pdf()
    response = client.post("/api/tools/to-word", json={"file_id": upload["id"]})
    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["filename"].endswith(".docx")

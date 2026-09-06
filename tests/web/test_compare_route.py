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


def test_compare_reports_trailing_page_as_added():
    # doc_a: 2 pages, doc_b: 3 pages
    upload_a = _upload_pdf(num_pages=2)
    upload_b = _upload_pdf(num_pages=3)
    response = client.post(
        "/api/compare",
        json={"file_id_a": upload_a["id"], "file_id_b": upload_b["id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["page_count_a"] == 2
    assert data["page_count_b"] == 3
    assert len(data["pages"]) == 3
    assert data["pages"][0]["has_counterpart"] is True
    assert data["pages"][1]["has_counterpart"] is True
    assert data["pages"][2]["has_counterpart"] is False


def test_compare_visual_diff_returns_base64_images_and_boxes():
    upload_a = _upload_pdf(num_pages=1)
    upload_b = _upload_pdf(num_pages=1)
    response = client.get(f"/api/compare/{upload_a['id']}/{upload_b['id']}/1/visual")
    assert response.status_code == 200
    data = response.json()
    assert data["image_a"].startswith("data:image/png;base64,")
    assert data["image_b"].startswith("data:image/png;base64,")
    assert isinstance(data["boxes"], list)


def test_compare_visual_rejects_out_of_range_page_num():
    upload_a = _upload_pdf(num_pages=1)
    upload_b = _upload_pdf(num_pages=2)
    response = client.get(f"/api/compare/{upload_a['id']}/{upload_b['id']}/5/visual")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Page 5" in detail
    assert "does not exist" in detail

import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _upload_pdf(num_pages=3, text_prefix="Page"):
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text_prefix} {i + 1}")
    data = doc.tobytes()
    doc.close()
    return client.post(
        "/api/files", files={"file": ("sample.pdf", data, "application/pdf")}
    ).json()


def test_merge_combines_two_files():
    upload_a = _upload_pdf(num_pages=2, text_prefix="A")
    upload_b = _upload_pdf(num_pages=3, text_prefix="B")

    response = client.post(
        "/api/tools/merge",
        json={"file_ids": [upload_a["id"], upload_b["id"]], "filename": "combined.pdf"},
    )

    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["filename"].startswith("combined_")
    download = client.get(outputs[0]["download_url"])
    assert download.status_code == 200


def test_merge_rejects_path_in_filename():
    upload_a = _upload_pdf()
    upload_b = _upload_pdf()

    response = client.post(
        "/api/tools/merge",
        json={"file_ids": [upload_a["id"], upload_b["id"]], "filename": "../evil.pdf"},
    )

    assert response.status_code == 422


def test_split_produces_one_file_per_range():
    upload = _upload_pdf(num_pages=4)

    response = client.post(
        "/api/tools/split", json={"file_id": upload["id"], "pages_per_file": 2}
    )

    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 2


def test_remove_pages_drops_selected():
    upload = _upload_pdf(num_pages=3)

    response = client.post(
        "/api/tools/remove-pages", json={"file_id": upload["id"], "pages": [2]}
    )

    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1


def test_remove_pages_rejects_empty_selection():
    upload = _upload_pdf()

    response = client.post(
        "/api/tools/remove-pages", json={"file_id": upload["id"], "pages": []}
    )

    assert response.status_code == 422


def test_extract_pages_selects_given_pages():
    upload = _upload_pdf(num_pages=4)

    response = client.post(
        "/api/tools/extract-pages", json={"file_id": upload["id"], "pages": [1, 3]}
    )

    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_reorder_pages_accepts_new_order():
    upload = _upload_pdf(num_pages=3)

    response = client.post(
        "/api/tools/reorder-pages", json={"file_id": upload["id"], "order": [3, 1, 2]}
    )

    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1

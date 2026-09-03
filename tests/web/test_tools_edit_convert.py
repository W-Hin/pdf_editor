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


def test_crop_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/crop",
        json={"file_id": upload["id"], "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_crop_rejects_out_of_range_fraction():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/crop",
        json={"file_id": upload["id"], "top": 1.2, "right": 0.1, "bottom": 0.1, "left": 0.1},
    )
    assert response.status_code == 422


def test_crop_rejects_fractions_summing_past_the_page():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/crop",
        json={"file_id": upload["id"], "top": 0.6, "right": 0.1, "bottom": 0.6, "left": 0.1},
    )
    assert response.status_code == 422


def test_crop_accepts_realistic_non_round_fractions():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/crop",
        json={"file_id": upload["id"], "top": 0.1857142857, "right": 0.2657142857, "bottom": 0.1142857143, "left": 0.0928571429},
    )
    assert response.status_code == 200


def test_add_page_numbers_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/add-page-numbers",
        json={"file_id": upload["id"], "position": "bottom-center", "format": "number"},
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_add_page_numbers_rejects_unknown_position():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/add-page-numbers",
        json={"file_id": upload["id"], "position": "middle", "format": "number"},
    )
    assert response.status_code == 422


def _upload_image(width=400, height=300, filename="photo.png"):
    doc = fitz.open()
    img_bytes = doc.new_page(width=width, height=height).get_pixmap().tobytes("png")
    doc.close()
    return client.post(
        "/api/files", files={"file": (filename, img_bytes, "image/png")}
    ).json()


def _upload_jpeg(width=400, height=300, filename="photo.jpg"):
    doc = fitz.open()
    img_bytes = doc.new_page(width=width, height=height).get_pixmap().tobytes("jpg")
    doc.close()
    return client.post(
        "/api/files", files={"file": (filename, img_bytes, "image/jpeg")}
    ).json()


def test_images_to_pdf_returns_one_output():
    upload1 = _upload_image(filename="a.png")
    upload2 = _upload_image(filename="b.png")
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload1["id"], upload2["id"]], "filename": "combined", "fit_mode": "fit"},
    )
    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["filename"].endswith(".pdf")

    download = client.get(outputs[0]["download_url"])
    assert download.status_code == 200
    result = fitz.open(stream=download.content, filetype="pdf")
    assert result.page_count == 2  # one page per uploaded image
    result.close()


def test_images_to_pdf_accepts_jpeg_images():
    upload = _upload_jpeg()
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload["id"]], "filename": "from-jpeg", "fit_mode": "fit"},
    )
    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1

    download = client.get(outputs[0]["download_url"])
    result = fitz.open(stream=download.content, filetype="pdf")
    assert result.page_count == 1
    result.close()


def test_images_to_pdf_unknown_file_id_returns_404():
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": ["nope"], "filename": "combined", "fit_mode": "fit"},
    )
    assert response.status_code == 404


def test_images_to_pdf_undecodable_image_returns_422_not_500():
    # SOI + a valid JFIF APP0 header, then garbage: MuPDF opens it lazily (so
    # upload succeeds and reports 1 page) but cannot decode it. Regression test
    # for this escaping as a raw exception -> HTTP 500.
    broken = (
        b"\xff\xd8"
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 200
    )
    upload = client.post("/api/files", files={"file": ("broken.jpg", broken, "image/jpeg")})
    assert upload.status_code == 200

    file_id = upload.json()["id"]
    thumbnail = client.get(f"/api/files/{file_id}/pages/1/thumbnail")
    assert thumbnail.status_code == 422

    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [file_id], "filename": "combined", "fit_mode": "fit"},
    )
    assert response.status_code == 422


def test_images_to_pdf_rejects_empty_file_ids():
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [], "filename": "combined", "fit_mode": "fit"},
    )
    assert response.status_code == 422


def test_images_to_pdf_rejects_unknown_fit_mode():
    upload = _upload_image()
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload["id"]], "filename": "combined", "fit_mode": "stretch"},
    )
    assert response.status_code == 422


def test_images_to_pdf_rejects_empty_filename():
    upload = _upload_image()
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload["id"]], "filename": "  ", "fit_mode": "fit"},
    )
    assert response.status_code == 422


def test_redact_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/redact",
        json={
            "file_id": upload["id"],
            "redactions": [{"page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1}],
        },
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_redact_rejects_empty_redactions():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/redact",
        json={"file_id": upload["id"], "redactions": []},
    )
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_redact_unknown_file_id_returns_404():
    response = client.post(
        "/api/tools/redact",
        json={
            "file_id": "nope",
            "redactions": [{"page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1}],
        },
    )
    assert response.status_code == 404


def test_get_text_runs_returns_runs():
    upload = _upload_pdf()
    response = client.get(f"/api/files/{upload['id']}/pages/1/text-runs")
    assert response.status_code == 200
    body = response.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["text"] == "Page 1"


def test_get_text_runs_unknown_file_id_returns_404():
    response = client.get("/api/files/nope/pages/1/text-runs")
    assert response.status_code == 404


def test_edit_pdf_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "highlight", "page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1, "color": "#ffff00"}
            ],
        },
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_edit_pdf_text_edit_element_succeeds():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "text_edit", "page": 1, "run_index": 0, "text": "Replaced", "font_override": None}
            ],
        },
    )
    assert response.status_code == 200


def test_edit_pdf_rejects_empty_elements():
    upload = _upload_pdf()
    response = client.post("/api/tools/edit-pdf", json={"file_id": upload["id"], "elements": []})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_edit_pdf_unknown_file_id_returns_404():
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": "nope",
            "elements": [
                {"type": "highlight", "page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1, "color": "#ffff00"}
            ],
        },
    )
    assert response.status_code == 404


def test_edit_pdf_image_element_unknown_file_id_returns_422():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "image", "page": 1, "file_id": "missing-image", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}
            ],
        },
    )
    assert response.status_code == 422

import fitz
import pytest


@pytest.fixture(autouse=True)
def isolated_history_db(tmp_path, monkeypatch):
    """Tests must never write to the real Recent Files database."""
    monkeypatch.setenv("PDF_EDITOR_DATA_DIR", str(tmp_path / "appdata"))


@pytest.fixture
def make_pdf(tmp_path):
    counter = 0
    def _make(num_pages=3, text_prefix="Page"):
        nonlocal counter
        counter += 1
        path = tmp_path / f"sample_{counter}.pdf"
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"{text_prefix} {i + 1}")
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make

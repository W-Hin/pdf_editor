import fitz
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    def _make(num_pages=3, text_prefix="Page"):
        path = tmp_path / "sample.pdf"
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"{text_prefix} {i + 1}")
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make

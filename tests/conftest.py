import sys
from pathlib import Path

import fitz
import pytest

# Ensure project root is in sys.path for both app and web modules
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


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

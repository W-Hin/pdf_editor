from pathlib import Path

import pytest

from app.core.convert import convert_to_word
from app.core.errors import PDFError


def test_convert_to_word_creates_docx(make_pdf, tmp_path):
    path = make_pdf(num_pages=1, text_prefix="Hello")
    out_path = str(tmp_path / "out.docx")

    convert_to_word(path, out_path)

    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 0


def test_convert_to_word_rejects_missing_file(tmp_path):
    with pytest.raises(PDFError):
        convert_to_word(str(tmp_path / "missing.pdf"), str(tmp_path / "out.docx"))

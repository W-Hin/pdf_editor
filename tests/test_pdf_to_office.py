import fitz
import pytest
from pptx import Presentation
from pptx.util import Pt

from app.core.errors import PDFError
from app.core.pdf_to_office import pdf_to_pptx


def _make_text_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Heading Text", fontname="hebo", fontsize=24)
    page.insert_text((72, 200), "Body paragraph in times.", fontname="tiro", fontsize=12)
    doc.save(str(path))
    doc.close()


def test_pdf_to_pptx_creates_positioned_textboxes(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_text_pdf(input_path)

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    assert output_path.exists()
    prs = Presentation(str(output_path))
    assert len(prs.slides) == 1
    shapes = list(prs.slides[0].shapes)
    assert len(shapes) == 2

    # Exact EMU values verified empirically against this exact fixture this
    # session (1pt = 12700 EMU, round(value_in_points * 12700)) — not
    # computed by hand.
    heading_shape = shapes[0]
    assert (heading_shape.left, heading_shape.top, heading_shape.width, heading_shape.height) == (
        914400,
        943864,
        1913839,
        419710,
    )
    heading_text = "".join(run.text for para in heading_shape.text_frame.paragraphs for run in para.runs)
    assert heading_text == "Heading Text"

    body_shape = shapes[1]
    assert (body_shape.left, body_shape.top, body_shape.width, body_shape.height) == (
        914400,
        2379523,
        1540764,
        203302,
    )
    body_text = "".join(run.text for para in body_shape.text_frame.paragraphs for run in para.runs)
    assert body_text == "Body paragraph in times."


def test_pdf_to_pptx_preserves_font_size_bold_and_family(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_text_pdf(input_path)

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    prs = Presentation(str(output_path))
    shapes = list(prs.slides[0].shapes)

    heading_run = shapes[0].text_frame.paragraphs[0].runs[0]
    # "hebo" (bold Helvetica) -> PyMuPDF reports font "Helvetica-Bold", flags
    # bit 4 (16) set for bold, bit 1 (2) clear for italic — verified this
    # session against this exact fixture.
    assert int(heading_run.font.size) == 304800  # Pt(24)
    assert heading_run.font.bold is True
    assert heading_run.font.italic is False
    assert heading_run.font.name == "Arial"

    body_run = shapes[1].text_frame.paragraphs[0].runs[0]
    # "tiro" (plain Times) -> PyMuPDF reports font "Times-Roman", flags bit 2
    # (4, serifed) set, bold/italic bits clear.
    assert int(body_run.font.size) == 152400  # Pt(12)
    assert body_run.font.bold is False
    assert body_run.font.italic is False
    assert body_run.font.name == "Times New Roman"


def test_pdf_to_pptx_matches_slide_size_to_page_size(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_text_pdf(input_path)

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    prs = Presentation(str(output_path))
    # 612pt x 792pt (US Letter) -> round(612*12700), round(792*12700) —
    # verified empirically this session.
    assert (prs.slide_width, prs.slide_height) == (7772400, 10058400)


def test_pdf_to_pptx_skips_image_blocks(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(10, 10, 50, 50), pixmap=pix)
    page.insert_text((10, 100), "Some text", fontsize=12)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    prs = Presentation(str(output_path))
    shapes = list(prs.slides[0].shapes)
    # Only the text block becomes a text box — the inserted image produces a
    # block with no "lines" key and is skipped entirely (confirmed
    # empirically this session: image blocks are type==1 with no "lines"
    # key; text blocks are type==0 with a "lines" key).
    assert len(shapes) == 1
    assert shapes[0].text_frame.paragraphs[0].runs[0].text == "Some text"


def test_pdf_to_pptx_raises_for_missing_file(tmp_path):
    with pytest.raises(PDFError):
        pdf_to_pptx(str(tmp_path / "does_not_exist.pdf"), str(tmp_path / "output.pptx"))


def test_pdf_to_pptx_clamps_sub_minimum_font_size(tmp_path):
    # python-pptx's ST_TextFontSize XML type only accepts 1pt-4000pt
    # (100-400000 centipoints); a hidden OCR layer / micro-print / a
    # text-matrix-scaled artifact can produce a span under 1pt. Without
    # clamping, `run.font.size = Pt(0.5)` raises a raw ValueError from
    # python-pptx that would kill the entire conversion for one span.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "tiny", fontsize=0.5)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    # Confirm the fixture actually reproduces the trigger condition: the
    # extracted span size is under python-pptx's 1pt minimum.
    check_doc = fitz.open(str(input_path))
    spans = [
        span
        for block in check_doc[0].get_text("dict")["blocks"]
        if "lines" in block
        for line in block["lines"]
        for span in line["spans"]
    ]
    check_doc.close()
    assert spans[0]["size"] < 1.0

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))  # must not raise ValueError

    prs = Presentation(str(output_path))
    run = prs.slides[0].shapes[0].text_frame.paragraphs[0].runs[0]
    assert run.text == "tiny"
    # Clamped to the minimum valid size, verified empirically this session:
    # int(Pt(1.0)) == 12700 centipoints.
    assert run.font.size == Pt(1.0)


def test_pdf_to_pptx_clamps_oversized_page_dimensions(tmp_path):
    # python-pptx bounds slide dimensions to 1-56 inches (914400-51206400
    # EMU). A large-format plotter/poster page bigger than 56in on both
    # sides (60in x 60in = 4320pt x 4320pt, since 1pt = 1/72in) exceeds
    # that on both width and height and, without clamping, raises a raw
    # ValueError from python-pptx when setting prs.slide_width/slide_height.
    doc = fitz.open()
    page = doc.new_page(width=4320, height=4320)  # 60in x 60in at 72pt/in
    page.insert_text((72, 100), "poster text", fontsize=12)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    # Confirm the fixture actually reproduces the trigger condition: the
    # unclamped EMU values exceed python-pptx's 51206400 EMU maximum on
    # both axes (verified empirically: round(4320 * 12700) == 54864000).
    assert round(4320 * 12700) > 51206400

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))  # must not raise ValueError

    prs = Presentation(str(output_path))
    # Clamped to python-pptx's own maximum, verified empirically this
    # session: Emu(51206400) round-trips unchanged (56 inches, the ceiling).
    assert prs.slide_width == 51206400
    assert prs.slide_height == 51206400


import openpyxl

from app.core.pdf_to_office import pdf_to_xlsx


def _draw_ruled_table(page, x0, y0, col_w, row_h, values):
    rows = len(values)
    cols = len(values[0])
    for r in range(rows + 1):
        page.draw_line((x0, y0 + r * row_h), (x0 + cols * col_w, y0 + r * row_h))
    for c in range(cols + 1):
        page.draw_line((x0 + c * col_w, y0), (x0 + c * col_w, y0 + rows * row_h))
    for r, row in enumerate(values):
        for c, val in enumerate(row):
            page.insert_text((x0 + c * col_w + 10, y0 + r * row_h + 20), val, fontsize=12)


def test_pdf_to_xlsx_extracts_detected_table(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _draw_ruled_table(page, 72, 100, 100, 30, [("A1", "B1"), ("A2", "B2")])
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.xlsx"
    pdf_to_xlsx(str(input_path), str(output_path))

    assert output_path.exists()
    workbook = openpyxl.load_workbook(str(output_path))
    assert workbook.sheetnames == ["Page1_Table1"]
    sheet = workbook["Page1_Table1"]
    # Exact cell values verified empirically against this exact fixture this
    # session — PyMuPDF's find_tables()/extract() on a real ruled table.
    assert list(sheet.iter_rows(values_only=True)) == [("A1", "B1"), ("A2", "B2")]


def test_pdf_to_xlsx_skips_pages_without_tables(tmp_path):
    doc = fitz.open()
    text_page = doc.new_page(width=612, height=792)
    text_page.insert_text((72, 100), "Just plain text, no table here.", fontsize=12)
    table_page = doc.new_page(width=612, height=792)
    _draw_ruled_table(table_page, 72, 100, 100, 30, [("X1", "Y1"), ("X2", "Y2")])
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.xlsx"
    pdf_to_xlsx(str(input_path), str(output_path))

    workbook = openpyxl.load_workbook(str(output_path))
    # Page 1 (text-only) contributes nothing; only page 2's table becomes a
    # sheet — verified empirically this session on this exact two-page shape.
    assert workbook.sheetnames == ["Page2_Table1"]
    assert list(workbook["Page2_Table1"].iter_rows(values_only=True)) == [("X1", "Y1"), ("X2", "Y2")]


def test_pdf_to_xlsx_raises_when_no_tables_found(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "No tables anywhere in this document.", fontsize=12)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.xlsx"
    with pytest.raises(PDFError):
        pdf_to_xlsx(str(input_path), str(output_path))
    assert not output_path.exists()


def test_pdf_to_xlsx_sanitizes_illegal_control_characters(tmp_path):
    # openpyxl raises IllegalCharacterError (a ValueError subclass) if any
    # string cell contains an ASCII control character (\x00-\x08, \x0b-\x0c,
    # \x0e-\x1f). PyMuPDF can round-trip these through a PDF's own
    # ToUnicode CMap into extracted table-cell text via page.insert_text()
    # followed by find_tables()/extract() — confirmed empirically this
    # session: a control character (chr(0x02), STX) embedded in text drawn
    # with insert_text() survives PyMuPDF's own extraction pipeline intact,
    # so this fixture exercises the real code path end-to-end rather than
    # a synthetic string. (Tried and confirmed working on the first
    # attempt — no fallback to monkeypatching find_tables() was needed.)
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    bad_cell = "A1" + chr(0x02) + "x"  # STX control char mid-string
    _draw_ruled_table(page, 72, 100, 100, 30, [(bad_cell, "B1"), ("A2", "B2")])
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    # Confirm the fixture actually reproduces the trigger condition: the
    # extracted cell text still contains the raw control character before
    # any sanitization, and openpyxl really does reject it unsanitized.
    #
    # Note: this module's app.core.pdf_ops (imported transitively via
    # app.core.pdf_to_office, already imported at the top of this test
    # file) itself imports pymupdf4llm, which has a confirmed empirical
    # side effect of changing PyMuPDF's global table-extraction strategy —
    # so "A1" + chr(0x02) + "x" round-trips as "A1 x\n\x02" here (word
    # split with an inserted space/newline, control char moved to the
    # end), not a byte-for-byte passthrough. The illegal character is
    # still present either way, which is all this test depends on.
    check_doc = fitz.open(str(input_path))
    extracted = check_doc[0].find_tables().tables[0].extract()
    check_doc.close()
    dirty_cell = extracted[0][0]
    assert "\x02" in dirty_cell
    with pytest.raises(openpyxl.utils.exceptions.IllegalCharacterError):
        openpyxl.Workbook().active.append(extracted[0])

    output_path = tmp_path / "output.xlsx"
    pdf_to_xlsx(str(input_path), str(output_path))  # must not raise IllegalCharacterError

    workbook = openpyxl.load_workbook(str(output_path))
    sheet = workbook["Page1_Table1"]
    rows = list(sheet.iter_rows(values_only=True))
    # The control character is stripped; everything else in the cell
    # (including the legal '\n') survives — verified empirically this
    # session against this exact fixture.
    expected_cell = dirty_cell.replace("\x02", "")
    assert rows == [(expected_cell, "B1"), ("A2", "B2")]
    assert "\x02" not in rows[0][0]

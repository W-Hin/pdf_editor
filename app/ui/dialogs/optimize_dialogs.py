from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QSlider, QLineEdit, QCheckBox

from app.core.pdf_ops import compress_pdf
from app.core.pdf_repair import repair_pdf, protect_pdf, unlock_pdf
from app.core.ocr import ocr_pdf, pdf_to_pdfa
from app.ui.dialogs.base import ToolDialog


class CompressDialog(ToolDialog):
    title = "Compress PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Image quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(60)
        layout.addWidget(self.quality_slider)

    def gather_params(self) -> dict:
        return {"image_quality": self.quality_slider.value()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_compressed.pdf"))
        compress_pdf(input_path, out_path, image_quality=params["image_quality"])
        return [out_path]


class RepairDialog(ToolDialog):
    title = "Repair PDF"

    def run_operation(self, input_paths: list[str], params: dict) -> tuple[list[str], str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_repaired.pdf"))
        result = repair_pdf(input_path, out_path)
        if result["warnings_count"] == 0:
            message = f"File is healthy — {result['page_count']} page{'s' if result['page_count'] != 1 else ''}."
        else:
            message = (
                f"Recovered {result['page_count']} page{'s' if result['page_count'] != 1 else ''} "
                f"after {result['warnings_count']} structural issue{'s' if result['warnings_count'] != 1 else ''} found."
            )
        return [out_path], message


class ProtectDialog(ToolDialog):
    title = "Protect PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMaxLength(127)
        layout.addWidget(self.password_input)

    def gather_params(self) -> dict:
        return {"password": self.password_input.text()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_protected.pdf"))
        protect_pdf(input_path, out_path, params["password"])
        return [out_path]


class UnlockDialog(ToolDialog):
    title = "Unlock PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_input)

    def gather_params(self) -> dict:
        return {"password": self.password_input.text()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_unlocked.pdf"))
        unlock_pdf(input_path, out_path, params["password"])
        return [out_path]


# (code, checkbox label) pairs — matches the web app's OCR language list exactly.
_OCR_LANGUAGES = [
    ("eng", "English"),
    ("spa", "Spanish"),
    ("fra", "French"),
    ("deu", "German"),
    ("por", "Portuguese"),
    ("chi_sim", "Chinese (Simplified)"),
    ("jpn", "Japanese"),
    ("ara", "Arabic"),
]


class OcrDialog(ToolDialog):
    title = "OCR PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Language(s):"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(6)
        self.language_checks: dict[str, QCheckBox] = {}
        for i, (code, label) in enumerate(_OCR_LANGUAGES):
            box = QCheckBox(label)
            if code == "eng":
                box.setChecked(True)
            self.language_checks[code] = box
            row, col = divmod(i, 2)
            grid.addWidget(box, row, col)
        layout.addLayout(grid)
        self.pdfa_check = QCheckBox("Also convert to PDF/A")
        layout.addWidget(self.pdfa_check)

    def gather_params(self) -> dict:
        languages = [code for code, box in self.language_checks.items() if box.isChecked()]
        return {"languages": languages, "convert_to_pdfa": self.pdfa_check.isChecked()}

    def run_operation(self, input_paths: list[str], params: dict) -> tuple[list[str], str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_ocr.pdf"))
        result = ocr_pdf(input_path, out_path, params["languages"], params["convert_to_pdfa"])
        if result["pages_skipped"] == 0:
            message = f"OCR'd all {result['pages_ocred']} page{'s' if result['pages_ocred'] != 1 else ''}."
        else:
            message = (
                f"OCR'd {result['pages_ocred']} of {result['pages_ocred'] + result['pages_skipped']} pages "
                f"— {result['pages_skipped']} already had text."
            )
        return [out_path], message


class PdfToPdfaDialog(ToolDialog):
    title = "PDF to PDF/A"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_pdfa.pdf"))
        pdf_to_pdfa(input_path, out_path)
        return [out_path]

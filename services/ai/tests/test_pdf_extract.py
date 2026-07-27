from pathlib import Path

import pytesseract
import pytest

from app.pdf import extract

FIXTURE_PDF = (Path(__file__).parent / "fixtures" / "sample_resume.pdf").read_bytes()


def test_extracts_text_from_a_real_pdf() -> None:
    text = extract.extract_text(FIXTURE_PDF)
    assert "Jane Doe" in text
    assert "Kubernetes" in text


def test_falls_back_to_ocr_when_a_page_has_no_extractable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the "no extractable text" branch regardless of the fixture's
    # real content, then assert the OCR fallback (mocked) is what wins.
    monkeypatch.setattr("pdfplumber.page.Page.extract_text", lambda self, *a, **k: "")
    monkeypatch.setattr(extract, "convert_from_bytes", lambda *a, **k: [object()])
    monkeypatch.setattr(pytesseract, "image_to_string", lambda image: "OCR EXTRACTED TEXT")

    text = extract.extract_text(FIXTURE_PDF)
    assert text.strip() == "OCR EXTRACTED TEXT"

import io

import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text page by page. Pages with no extractable text (scanned/
    image PDFs) fall back to rendering the page as an image and running OCR
    over it."""
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for index, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text and text.strip():
                pages.append(text)
                continue
            image = convert_from_bytes(pdf_bytes, first_page=index + 1, last_page=index + 1)[0]
            pages.append(pytesseract.image_to_string(image))
    return "\n".join(pages)

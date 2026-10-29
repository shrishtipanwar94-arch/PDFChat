"""PDF validation and per-page text extraction (PyMuPDF)."""

import pymupdf

PDF_SIGNATURE = b"%PDF-"


class PDFError(Exception):
    """The upload is not a usable PDF; the message is safe to show the user."""


def looks_like_pdf(data: bytes) -> bool:
    # The spec allows the header anywhere in the first 1024 bytes.
    return PDF_SIGNATURE in data[:1024]


def extract_pages(data: bytes) -> list[tuple[int, str]]:
    """Return (page_number, text) for each page, page numbers starting at 1."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PDFError("The file could not be opened as a PDF.") from exc

    with doc:
        if doc.needs_pass:
            raise PDFError("The PDF is password-protected.")
        pages = [(i + 1, page.get_text("text")) for i, page in enumerate(doc)]
    return pages


def page_count(pages: list[tuple[int, str]]) -> int:
    return len(pages)


def has_text(pages: list[tuple[int, str]]) -> bool:
    return any(text.strip() for _, text in pages)

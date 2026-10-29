import pymupdf
import pytest

from app import pdf


def make_pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_signature_check():
    assert pdf.looks_like_pdf(make_pdf(["hi"]))
    assert not pdf.looks_like_pdf(b"PK\x03\x04 this is a zip")
    assert not pdf.looks_like_pdf(b"")


def test_extract_pages_numbers_from_one():
    pages = pdf.extract_pages(make_pdf(["first page", "second page"]))
    assert [n for n, _ in pages] == [1, 2]
    assert "second page" in pages[1][1]
    assert pdf.has_text(pages)


def test_blank_pdf_has_no_text():
    pages = pdf.extract_pages(make_pdf(["", ""]))
    assert not pdf.has_text(pages)


def test_garbage_with_signature_raises_pdf_error():
    with pytest.raises(pdf.PDFError):
        pdf.extract_pages(b"%PDF-1.7 not really a pdf")

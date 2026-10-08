"""워드·PDF → 한글 변환 진입점: 확장자를 보고 알맞은 변환기를 부른다."""
from __future__ import annotations

from pathlib import Path

from app.docs.docx_to_hwp import ConvertResult, convert_docx
from app.docs.pdf_to_hwp import convert_pdf

SUPPORTED = ["docx", "pdf"]


def convert_to_hwp(filename: str, data: bytes, fmt: str = "hwpx", keep_pdf_pages: bool = True) -> ConvertResult:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext == "docx":
        return convert_docx(data, fmt)
    if ext == "pdf":
        return convert_pdf(data, fmt, keep_pages=keep_pdf_pages)
    raise ValueError(f".{ext} 파일은 변환할 수 없습니다. .docx 또는 .pdf만 가능합니다.")

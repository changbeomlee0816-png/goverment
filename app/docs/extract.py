"""문서 텍스트 추출: PDF / HWP(5.0) / HWPX / DOCX / TXT.

HWP는 외부 프로그램 없이 olefile로 BodyText 레코드를 직접 파싱한다.
실패 시 hwp5txt(pyhwp) 또는 LibreOffice(soffice)가 설치돼 있으면 그것으로 재시도한다.
"""
from __future__ import annotations

import io
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path
from xml.etree import ElementTree as ET

HWPTAG_BEGIN = 0x10
HWPTAG_PARA_TEXT = HWPTAG_BEGIN + 51  # 67

# HWP 제어문자: 확장/인라인 제어문자는 8 WCHAR(16바이트)를 차지한다.
_EXTENDED_CTRL = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
_INLINE_CTRL = {4, 5, 6, 7, 8, 9, 19, 20}


class ExtractError(RuntimeError):
    pass


def extract_text(path: str | Path, data: bytes | None = None) -> str:
    """확장자로 형식을 판별해 텍스트를 반환한다. data가 있으면 파일 대신 사용."""
    path = Path(path)
    ext = path.suffix.lower()
    if data is None:
        data = path.read_bytes()
    if ext == ".pdf":
        return _pdf(data)
    if ext == ".hwp":
        return _hwp(data, path)
    if ext == ".hwpx":
        return _hwpx(data)
    if ext == ".docx":
        return _docx(data)
    if ext in {".txt", ".md", ".csv"}:
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")
    raise ExtractError(f"지원하지 않는 형식입니다: {ext} (PDF/HWP/HWPX/DOCX/TXT 지원)")


# ---------------------------------------------------------------- PDF
def _pdf(data: bytes) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return _normalize("\n".join(pages))


# ---------------------------------------------------------------- HWP 5.0
def _hwp(data: bytes, path: Path) -> str:
    try:
        text = parse_hwp5(data)
        if text.strip():
            return text
    except Exception as exc:  # noqa: BLE001 - 외부 도구로 재시도
        last_error: Exception | None = exc
    else:
        last_error = None
    fallback = _external_convert(data, ".hwp")
    if fallback:
        return fallback
    raise ExtractError(f"HWP 텍스트 추출 실패: {last_error or '본문 없음'} (배포용/암호 문서일 수 있음)")


def parse_hwp5(data: bytes) -> str:
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            raise ExtractError("HWP 5.0 문서가 아닙니다")
        flags = struct.unpack("<I", header[36:40])[0]
        compressed = bool(flags & 0x01)
        if flags & 0x02:
            raise ExtractError("암호가 설정된 HWP 문서입니다")
        distributed = bool(flags & 0x04)

        storage = "ViewText" if distributed else "BodyText"
        sections = sorted(
            (e for e in ole.listdir() if e and e[0] == storage and e[-1].startswith("Section")),
            key=lambda e: int(e[-1].replace("Section", "") or 0),
        )
        if distributed:
            raise ExtractError("배포용 HWP 문서는 직접 추출할 수 없습니다")
        paragraphs: list[str] = []
        for entry in sections:
            raw = ole.openstream(entry).read()
            if compressed:
                raw = zlib.decompress(raw, -15)
            paragraphs.extend(iter_para_text(raw))
        return _normalize("\n".join(paragraphs))
    finally:
        ole.close()


def iter_para_text(raw: bytes):
    """섹션 스트림의 레코드를 순회하며 PARA_TEXT 레코드의 텍스트를 돌려준다."""
    pos, n = 0, len(raw)
    while pos + 4 <= n:
        header = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", raw, pos)[0]
            pos += 4
        payload = raw[pos : pos + size]
        pos += size
        if tag == HWPTAG_PARA_TEXT:
            yield decode_para_text(payload)


def decode_para_text(payload: bytes) -> str:
    out: list[str] = []
    i, n = 0, len(payload) - 1
    while i < n:
        code = payload[i] | (payload[i + 1] << 8)
        if code < 32:
            if code in _EXTENDED_CTRL or code in _INLINE_CTRL:
                if code == 9:
                    out.append("\t")
                i += 16
                continue
            if code in (10, 13):
                out.append("\n")
            elif code == 24:
                out.append("-")
            elif code in (30, 31):
                out.append(" ")
            i += 2
            continue
        out.append(chr(code))
        i += 2
    return "".join(out).rstrip("\n")


# ---------------------------------------------------------------- HWPX / DOCX
def _hwpx(data: bytes) -> str:
    paragraphs: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(
            (n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
            key=lambda n: int(re.findall(r"\d+", n)[-1]),
        )
        for name in names:
            root = ET.fromstring(zf.read(name))
            for para in root.iter():
                if para.tag.endswith("}p"):
                    texts = [t.text or "" for t in para.iter() if t.tag.endswith("}t")]
                    line = "".join(texts)
                    if line.strip():
                        paragraphs.append(line)
    return _normalize("\n".join(paragraphs))


def _docx(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            lines.append("".join(t.text or "" for t in child.iter() if t.tag.endswith("}t")))
        elif tag == "tbl":
            for row in child.iter():
                if row.tag.endswith("}tr"):
                    cells = []
                    for cell in row:
                        if cell.tag.endswith("}tc"):
                            cells.append("".join(t.text or "" for t in cell.iter() if t.tag.endswith("}t")).strip())
                    lines.append(" | ".join(cells))
    return _normalize("\n".join(lines))


# ---------------------------------------------------------------- 외부 도구
def _external_convert(data: bytes, suffix: str) -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"doc{suffix}"
        src.write_bytes(data)
        if shutil.which("hwp5txt"):
            try:
                result = subprocess.run(
                    ["hwp5txt", str(src)], capture_output=True, timeout=120, check=True
                )
                return _normalize(result.stdout.decode("utf-8", errors="ignore"))
            except (subprocess.SubprocessError, OSError):
                pass
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice:
            try:
                subprocess.run(
                    [soffice, "--headless", "--convert-to", "txt:Text", "--outdir", tmp, str(src)],
                    capture_output=True,
                    timeout=180,
                    check=True,
                )
                out = Path(tmp) / "doc.txt"
                if out.exists():
                    return _normalize(out.read_text(encoding="utf-8", errors="ignore"))
            except (subprocess.SubprocessError, OSError):
                pass
    return None


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

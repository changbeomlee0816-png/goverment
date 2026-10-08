"""PDF → 한글(HWPX/HWP) 변환.

PDF에는 "문단"이나 "표"라는 구조가 없고 글자 위치만 있으므로, 위치를 보고 다시 짜 맞춘다.
- 글자: 같은 높이의 단어를 한 줄로 묶고, 줄이 오른쪽 끝까지 차서 넘어간 경우만 한 문단으로 잇는다.
  글자 크기·굵기는 PDF 글꼴 정보에서 가져온다.
- 표: 선으로 그려진 표(pdfplumber find_tables)를 찾아 칸 경계로 셀 병합까지 복원한다.
- 그림: 그림 영역을 이미지로 잘라 넣는다.
- 쪽 나눔: PDF 쪽마다 새 쪽에서 시작한다(선택).
- 스캔본(글자 없는 쪽): 글자 인식(OCR)은 하지 않고 쪽 전체를 그림으로 넣는다.
"""
from __future__ import annotations

import io
import re
import statistics

import pdfplumber
from hwpx import HwpxDocument

from app.docs.docx_to_hwp import ConvertResult

PT_TO_MM = 25.4 / 72
PT_TO_HWP = 100  # 1pt = 100 HWPUNIT
MARGIN_LR_MM = 20
MARGIN_TB_MM = 15
_PAGE_NO = re.compile(r"^[-–—\s]*(\d{1,4}|\d{1,4}\s*/\s*\d{1,4}|[ivxIVX]{1,6})[-–—\s]*$")
# 새 문단을 시작하는 머리 기호(공문서·계획서에서 흔한 것)
_ITEM_HEAD = re.compile(r"^([□■○●◦◎◇◆▶▷►※\-–·•*]|\d{1,2}[.)]|[가-하][.)]|\(\d{1,2}\)|\([가-하]\)|[①-⑳]|제\s*\d+\s*[조장절])")


def convert_pdf(data: bytes, fmt: str = "hwpx", keep_pages: bool = True) -> ConvertResult:
    """PDF 바이트를 받아 HWPX(fmt="hwpx") 또는 HWP 5.0(fmt="hwp") 바이트로 돌려준다."""
    if fmt not in ("hwpx", "hwp"):
        raise ValueError("fmt는 'hwpx' 또는 'hwp'만 가능합니다.")
    conv = _PdfConverter(keep_pages)
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if not pdf.pages:
            raise ValueError("쪽이 없는 PDF입니다.")
        conv.page_setup(pdf.pages[0])
        for i, page in enumerate(pdf.pages):
            conv.page(page, first=i == 0)
    conv.finish()
    out = conv.dst.to_bytes(format=fmt)
    return ConvertResult(out, conv.n_para, conv.n_table, conv.n_image, conv.warnings)


class _PdfConverter:
    def __init__(self, keep_pages: bool):
        self.dst = HwpxDocument.new()
        self.keep_pages = keep_pages
        self.n_para = self.n_table = self.n_image = 0
        self.warnings: list[str] = []
        self._first_unused = True
        self._break_next = False
        self._scanned_pages: list[int] = []
        self._text_width_pt = 0.0

    # ---------- 쪽 ----------
    def page_setup(self, page) -> None:
        w_mm, h_mm = page.width * PT_TO_MM, page.height * PT_TO_MM
        self.dst.page.setup(
            width_mm=round(w_mm, 1), height_mm=round(h_mm, 1),
            margin_left_mm=MARGIN_LR_MM, margin_right_mm=MARGIN_LR_MM,
            margin_top_mm=MARGIN_TB_MM, margin_bottom_mm=MARGIN_TB_MM,
        )
        self._text_width_pt = page.width - 2 * MARGIN_LR_MM / PT_TO_MM

    def page(self, page, first: bool) -> None:
        if not first and self.keep_pages:
            self._break_next = True
        tables = [t for t in page.find_tables() if len(t.rows) >= 1 and len(t.cells) >= 2]
        boxes = [t.bbox for t in tables]

        def outside(obj) -> bool:
            if obj.get("object_type") != "char":
                return True
            cx = (obj["x0"] + obj["x1"]) / 2
            cy = (obj["top"] + obj["bottom"]) / 2
            return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

        chars = [c for c in page.filter(outside).chars if c.get("upright", True)]
        words = [c for c in chars if c["text"].strip()]
        images = [im for im in page.images if (im["x1"] - im["x0"]) > 15 and (im["bottom"] - im["top"]) > 15]

        if not words and not tables:  # 글자 정보가 없는 쪽 = 스캔본
            self._scanned_pages.append(page.page_number)
            self._image(page, (0, 0, page.width, page.height), full_page=True)
            return

        lines = _group_lines(chars)
        lines = [ln for ln in lines if not _is_page_number(ln, page.height)]
        blocks: list[tuple[float, str, object]] = [(ln["top"], "line", ln) for ln in lines]
        blocks += [(t.bbox[1], "table", t) for t in tables]
        blocks += [(im["top"], "image", im) for im in images if not any(_inside(im, b) for b in boxes)]
        blocks.sort(key=lambda b: (b[0], {"table": 0, "image": 1, "line": 2}[b[1]]))

        right_edge = max((ln["x1"] for ln in lines), default=page.width)
        left_edge = min((ln["x0"] for ln in lines), default=0)
        para: list[dict] = []
        for _, kind, obj in blocks:
            if kind == "line":
                if para and not _continues(para[-1], obj, right_edge):
                    self._paragraph(para, left_edge, right_edge, page.width)
                    para = []
                para.append(obj)
                continue
            if para:
                self._paragraph(para, left_edge, right_edge, page.width)
                para = []
            if kind == "table":
                self._table(obj)
            else:
                self._image(page, (obj["x0"], obj["top"], obj["x1"], obj["bottom"]))
        if para:
            self._paragraph(para, left_edge, right_edge, page.width)

    def finish(self) -> None:
        if self._scanned_pages:
            pages = ", ".join(map(str, self._scanned_pages[:10])) + (" 등" if len(self._scanned_pages) > 10 else "")
            self.warnings.append(
                f"{pages}쪽은 글자 정보가 없는 스캔본(그림)이라 쪽 전체를 그림으로 넣었습니다. 글자 인식(OCR)은 하지 않습니다."
            )
        if not self.n_para and not self.n_table:
            return
        self.warnings.append(
            "PDF에는 문단 정보가 없어 글자 위치로 줄·문단을 추정했습니다. 줄이 넘어가던 자리에 띄어쓰기가 "
            "잘못 들어갈 수 있으니(예: '비 용') 한/글에서 확인해 주세요."
        )

    # ---------- 문단 ----------
    def _new_paragraph(self):
        if self._first_unused:
            self._first_unused = False
            return self.dst.paragraphs[0]
        return self.dst.add_paragraph("", include_run=False, inherit_style=False)

    def _apply_break(self, para) -> None:
        if self._break_next:
            self.dst.styles.apply_paragraph_format(paragraphs=[para], page_break_before=True)
            self._break_next = False

    def _paragraph(self, lines: list[dict], left_edge: float, right_edge: float, page_w: float) -> None:
        para = self._new_paragraph()
        runs: list[tuple[str, bool, float]] = []
        for i, ln in enumerate(lines):
            for j, (text, bold, size) in enumerate(ln["segments"]):
                if i > 0 and j == 0:
                    text = " " + text  # 줄이 넘어가는 자리
                if runs and runs[-1][1] == bold and runs[-1][2] == size:
                    runs[-1] = (runs[-1][0] + text, bold, size)
                else:
                    runs.append((text, bold, size))
        for text, bold, size in runs:
            para.add_run(text, char_pr_id_ref=self.dst.styles.ensure_run(bold=bold, size=size))
        self.n_para += 1

        fmt: dict = {}
        width = right_edge - left_edge
        first = lines[0]
        if len(lines) == 1 and width > 0:
            mid = (first["x0"] + first["x1"]) / 2
            short = (first["x1"] - first["x0"]) < width * 0.8
            if short and abs(mid - page_w / 2) < page_w * 0.04 and first["x0"] - left_edge > 6:
                fmt["alignment"] = "CENTER"
            elif first["x0"] - left_edge > width * 0.4 and first["x1"] >= right_edge - 6:
                fmt["alignment"] = "RIGHT"
        indent_pt = first["x0"] - left_edge
        if "alignment" not in fmt and 4 < indent_pt < width * 0.3:
            fmt["indent_left_mm"] = round(indent_pt * PT_TO_MM, 1)
        if self._break_next:
            fmt["page_break_before"] = True
            self._break_next = False
        if fmt:
            self.dst.styles.apply_paragraph_format(paragraphs=[para], **fmt)

    # ---------- 표 ----------
    def _table(self, t) -> None:
        cells = [c for c in t.cells if c]
        xs = _snap(sorted({c[0] for c in cells} | {c[2] for c in cells}))
        ys = _snap(sorted({c[1] for c in cells} | {c[3] for c in cells}))
        n_cols, n_rows = len(xs) - 1, len(ys) - 1
        if n_cols < 1 or n_rows < 1:
            return
        if self._first_unused:  # 첫 문단(구역 정의)은 비워 두고 표를 그 뒤에 둔다
            self._first_unused = False
            self._apply_break(self.dst.paragraphs[0])
        widths_pt = [xs[i + 1] - xs[i] for i in range(n_cols)]
        scale = min(1.0, self._text_width_pt / sum(widths_pt)) if sum(widths_pt) else 1.0
        widths = [max(int(w * scale * PT_TO_HWP), 600) for w in widths_pt]
        ht = self.dst.add_table(n_rows, n_cols, width=sum(widths))
        if self._break_next:
            self.dst.styles.apply_paragraph_format(paragraphs=[ht.paragraph], page_break_before=True)
            self._break_next = False
        try:
            ht.set_column_widths(widths)
        except Exception:  # noqa: BLE001 - 열 너비 실패해도 내용은 넣는다
            pass

        page = t.page
        merges = []
        for c in cells:
            c0, c1 = _index(xs, c[0]), _index(xs, c[2])
            r0, r1 = _index(ys, c[1]), _index(ys, c[3])
            if c1 <= c0 or r1 <= r0:
                continue
            text = _cell_text(page, c)
            if text:
                ht.cell(r0, c0).set_text(text, split_paragraphs=True)
            if r1 - r0 > 1 or c1 - c0 > 1:
                merges.append((r0, c0, r1 - 1, c1 - 1))
        for r0, c0, r1, c1 in sorted(merges, reverse=True):
            try:
                ht.merge_cells(r0, c0, r1, c1)
            except Exception as exc:  # noqa: BLE001
                self.warnings.append(f"표 셀 병합 1건을 적용하지 못했습니다({exc}).")
        self.n_table += 1

    # ---------- 그림 ----------
    def _image(self, page, bbox, full_page: bool = False) -> None:
        x0, top, x1, bottom = (max(bbox[0], 0), max(bbox[1], 0), min(bbox[2], page.width), min(bbox[3], page.height))
        if x1 - x0 < 2 or bottom - top < 2:
            return
        try:
            img = page.crop((x0, top, x1, bottom)).to_image(resolution=200 if full_page else 150)
            buf = io.BytesIO()
            img.original.convert("RGB").save(buf, format="PNG")
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"{page.page_number}쪽 그림 1개를 넣지 못했습니다({exc}).")
            return
        w_mm, h_mm = (x1 - x0) * PT_TO_MM, (bottom - top) * PT_TO_MM
        max_w = self._text_width_pt * PT_TO_MM
        max_h = page.height * PT_TO_MM - 2 * MARGIN_TB_MM - 5
        scale = min(1.0, max_w / w_mm, max_h / h_mm)
        if self._first_unused:
            self._first_unused = False
            self._apply_break(self.dst.paragraphs[0])
        pic = self.dst.add_picture(buf.getvalue(), "png", width_mm=w_mm * scale, height_mm=h_mm * scale, align="CENTER")
        if self._break_next:
            self.dst.styles.apply_paragraph_format(paragraphs=[pic.paragraph], page_break_before=True)
            self._break_next = False
        self.n_image += 1


# ---------- PDF 해석 도우미 ----------
def _group_lines(chars: list[dict]) -> list[dict]:
    """세로 위치가 겹치는 글자를 한 줄로 묶고, 글자 서식이 같은 조각(segment)으로 나눈다.

    띄어쓰기는 PDF에 들어 있는 공백 글자를 그대로 쓴다. 공백 글자가 없는 PDF만 글자 간격으로 추정한다.
    """
    has_spaces = any(c["text"] == " " for c in chars)
    lines: list[dict] = []
    for c in sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"])):
        h = c["bottom"] - c["top"]
        for ln in reversed(lines[-3:]):
            if abs(ln["top"] - c["top"]) <= max(2.0, h * 0.4):
                ln["chars"].append(c)
                break
        else:
            lines.append({"top": c["top"], "chars": [c]})
    out = []
    for ln in lines:
        cs = sorted(ln["chars"], key=lambda c: c["x0"])
        visible = [c for c in cs if c["text"].strip()]
        if not visible:
            continue
        segments: list[list] = []
        prev = None
        pending_space = False
        for c in cs:
            if not c["text"].strip():
                pending_space = prev is not None
                continue
            text = _fix_symbols(c["text"])
            if prev is not None:
                gap = c["x0"] - prev["x1"]
                if pending_space or gap > c["size"] * (0.6 if has_spaces else 0.25):
                    text = " " + text
            bold, size = _is_bold(c.get("fontname", "")), _round_size(c["size"])
            if segments and segments[-1][1] == bold and segments[-1][2] == size:
                segments[-1][0] += text
            else:
                segments.append([text, bold, size])
            prev, pending_space = c, False
        out.append({
            "top": min(c["top"] for c in visible),
            "bottom": max(c["bottom"] for c in visible),
            "x0": visible[0]["x0"],
            "x1": max(c["x1"] for c in visible),
            "size": statistics.median(c["size"] for c in visible),
            "segments": [tuple(sg) for sg in segments],
            "text": "".join(sg[0] for sg in segments),
        })
    out.sort(key=lambda ln: ln["top"])
    return out


def _continues(prev: dict, cur: dict, right_edge: float) -> bool:
    """앞 줄이 오른쪽 끝까지 차서 자연스럽게 넘어온 줄이면 같은 문단으로 본다."""
    size = prev["size"]
    gap = cur["top"] - prev["bottom"]
    if gap > size * 0.9 or gap < -size * 0.5:
        return False
    if abs(cur["size"] - prev["size"]) > 0.6:
        return False
    if prev["x1"] < right_edge - size * 2.5:  # 앞 줄이 짧게 끝남 → 문단 끝
        return False
    if _ITEM_HEAD.match(cur["text"]):
        return False
    return True


# Symbol·Wingdings 글꼴의 글머리표는 사용자 영역(U+F0xx) 글자로 나온다
_SYMBOL_MAP = {"\uf0b7": "•", "\uf0a7": "▪", "\uf0a8": "□", "\uf06e": "■", "\uf0d8": "▶", "\uf0fc": "✓",
               "\uf076": "❖", "\uf0e0": "→", "\uf06c": "●", "\uf071": "❑", "\uf0a1": "○"}


def _fix_symbols(text: str) -> str:
    return "".join(_SYMBOL_MAP.get(ch, "•" if "\uf000" <= ch <= "\uf0ff" else ch) for ch in text)


def _is_page_number(ln: dict, page_h: float) -> bool:
    near_edge = ln["top"] > page_h * 0.9 or ln["bottom"] < page_h * 0.08
    return near_edge and bool(_PAGE_NO.match(ln["text"]))


def _is_bold(fontname: str) -> bool:
    name = (fontname or "").split("+")[-1].lower()
    return any(k in name for k in ("bold", "black", "heavy", "-b", ",b", "extrab", "semib", "demib"))


def _round_size(size: float) -> float:
    return max(6.0, min(72.0, round(size * 2) / 2))


def _inside(obj, box) -> bool:
    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]


def _snap(values: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for v in values:
        if out and v - out[-1] <= tol:
            continue
        out.append(v)
    return out


def _index(edges: list[float], v: float) -> int:
    return min(range(len(edges)), key=lambda i: abs(edges[i] - v))


def _cell_text(page, bbox) -> str:
    x0, top, x1, bottom = bbox
    try:
        crop = page.crop((x0 + 0.5, top + 0.5, x1 - 0.5, bottom - 0.5), strict=False)
        text = crop.extract_text() or ""
    except Exception:  # noqa: BLE001
        return ""
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())

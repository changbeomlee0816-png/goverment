"""워드(DOCX) → 한글(HWPX/HWP) 변환.

한/글 프로그램 없이 python-hwpx로 한/글 문서를 직접 만든다.
옮기는 것: 문단 순서, 제목(개요 1~6), 글자 모양(굵게·기울임·밑줄·취소선·크기·색),
문단 정렬, 목록(글머리표 "• "로 표시), 쪽 나누기, 표(셀 병합 포함), 그림, 용지 크기·여백.
머리말·꼬리말, 각주, 도형, 수식, 변경 추적은 옮기지 않는다(본문 텍스트는 남는다).
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from hwpx import HwpxDocument

EMU_PER_MM = 36000
_ALIGN = {"center": "CENTER", "right": "RIGHT", "both": "JUSTIFY", "distribute": "DISTRIBUTE", "left": "LEFT", "start": "LEFT", "end": "RIGHT"}
_IMAGE_FORMATS = {"png", "jpg", "jpeg", "gif", "bmp"}
_HEADING_PT = {1: 16, 2: 14, 3: 13, 4: 12, 5: 11, 6: 11}


@dataclass
class ConvertResult:
    data: bytes
    paragraphs: int = 0
    tables: int = 0
    images: int = 0
    warnings: list[str] = field(default_factory=list)


def convert_docx(data: bytes, fmt: str = "hwpx") -> ConvertResult:
    """DOCX 바이트를 받아 HWPX(fmt="hwpx") 또는 HWP 5.0(fmt="hwp") 바이트로 돌려준다."""
    if fmt not in ("hwpx", "hwp"):
        raise ValueError("fmt는 'hwpx' 또는 'hwp'만 가능합니다.")
    src = Document(io.BytesIO(data))
    conv = _Converter(src)
    conv.run()
    out = conv.dst.to_bytes(format=fmt)
    return ConvertResult(out, conv.n_para, conv.n_table, conv.n_image, conv.warnings)


class _Converter:
    def __init__(self, src):
        self.src = src
        self.dst = HwpxDocument.new()
        self.n_para = self.n_table = self.n_image = 0
        self.warnings: list[str] = []
        self._first_unused = True  # 새 문서의 첫 빈 문단(구역 정의 포함)을 첫 내용에 재사용
        self._page_break_next = False
        self._skipped: set[str] = set()
        self._counters: dict[str, dict[int, int]] = {}

    # ---------- 전체 흐름 ----------
    def run(self) -> None:
        self._page_setup()
        body = self.src.element.body
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                self._paragraph(Paragraph(child, self.src))
            elif child.tag == qn("w:tbl"):
                self._table(Table(child, self.src))
            elif child.tag == qn("w:sdt"):  # 목차 등 콘텐츠 컨트롤: 안의 문단만 옮긴다
                for p in child.iter(qn("w:p")):
                    self._paragraph(Paragraph(p, self.src))
        for name in sorted(self._skipped):
            self.warnings.append(f"{name}은(는) 옮기지 않았습니다.")

    def _page_setup(self) -> None:
        sec = self.src.sections[0] if self.src.sections else None
        if sec is None or not sec.page_width or not sec.page_height:
            return
        def mm(v):
            return round(v / EMU_PER_MM, 1) if v is not None else None

        try:
            self.dst.page.setup(
                width_mm=mm(sec.page_width),
                height_mm=mm(sec.page_height),
                margin_left_mm=mm(sec.left_margin),
                margin_right_mm=mm(sec.right_margin),
                margin_top_mm=mm(sec.top_margin),
                margin_bottom_mm=mm(sec.bottom_margin),
            )
        except Exception as exc:  # noqa: BLE001 - 용지 설정 실패해도 본문 변환은 계속
            self.warnings.append(f"용지 설정을 옮기지 못했습니다({exc}). 기본 A4로 저장합니다.")
        if len(self.src.sections) > 1:
            self.warnings.append("구역이 여러 개인 문서는 첫 구역의 용지 설정만 적용했습니다.")
        if any(s.header.paragraphs and any(p.text.strip() for p in s.header.paragraphs) for s in self.src.sections):
            self._skipped.add("머리말·꼬리말")

    # ---------- 문단 ----------
    def _paragraph(self, p: Paragraph) -> None:
        el = p._p
        self._note_unsupported(el)
        level = _heading_level(p)
        # 한/글 "개요" 스타일은 자동 번호(1. 가. …)가 붙어 원문과 달라지므로 쓰지 않고
        # 제목은 글자 크기·굵기로 옮긴다.
        images = list(_images(p))
        if images and not p.text.strip() and not self._first_unused:
            # 그림만 있는 문단: 빈 줄을 만들지 않고 그림 문단만 넣는다
            for blob, ext, w, h in images:
                self._picture(blob, ext, w, h, _alignment(p))
            if _has_page_break(el):
                self._page_break_next = True
            return
        para = self._take_first() or self.dst.add_paragraph("", include_run=False, inherit_style=False)
        self._fill_runs(para, p, self._list_prefix(p) if level is None else "", level)
        self.n_para += 1

        fmt: dict = {}
        align = _alignment(p)
        if align:
            fmt["alignment"] = align
        if level is not None:
            fmt["keep_with_next"] = True
            fmt["spacing_before_pt"] = 6
        if self._page_break_next or _page_break_before(p):
            fmt["page_break_before"] = True
            self._page_break_next = False
        if fmt:
            self.dst.styles.apply_paragraph_format(paragraphs=[para], **fmt)

        for blob, ext, w, h in images:
            self._picture(blob, ext, w, h, align)
        if _has_page_break(el):
            self._page_break_next = True

    def _list_prefix(self, p: Paragraph) -> str:
        """목록 문단 앞 기호. 글머리표는 "• ", 번호 목록은 "1. "·"가. " 등으로 직접 적는다."""
        num_pr = p._p.find(f"{qn('w:pPr')}/{qn('w:numPr')}")
        if num_pr is None:
            num_pr = _style_num_pr(p.style)
        if num_pr is None:
            return ""
        num_el = num_pr.find(qn("w:numId"))
        lvl_el = num_pr.find(qn("w:ilvl"))
        num_id = num_el.get(qn("w:val")) if num_el is not None else None
        ilvl = int(lvl_el.get(qn("w:val"), "0")) if lvl_el is not None else 0
        if not num_id or num_id == "0":
            return ""
        fmt, text = _numbering_format(self.src, num_id, ilvl)
        indent = "  " * ilvl
        if fmt in (None, "bullet"):
            return f"{indent}• "
        counters = self._counters.setdefault(num_id, {})
        counters[ilvl] = counters.get(ilvl, 0) + 1
        for deeper in [k for k in counters if k > ilvl]:
            del counters[deeper]
        label = text or f"%{ilvl + 1}."
        for k in range(ilvl + 1):
            label = label.replace(f"%{k + 1}", _format_number(counters.get(k, 1), fmt))
        return f"{indent}{label} "

    def _take_first(self):
        if self._first_unused:
            self._first_unused = False
            return self.dst.paragraphs[0]
        return None

    def _fill_runs(self, para, p: Paragraph, prefix: str = "", level: int | None = None) -> None:
        pieces: list[tuple[str, dict]] = []
        for child in p._p.iterchildren():
            if child.tag == qn("w:r"):
                pieces.append((_run_text(child), self._run_format(Run(child, p), p, level)))
            elif child.tag in (qn("w:hyperlink"), qn("w:ins"), qn("w:smartTag"), qn("w:fldSimple")):
                for r in child.iter(qn("w:r")):
                    fmt = self._run_format(Run(r, p), p, level)
                    if child.tag == qn("w:hyperlink"):
                        fmt.update(underline=True, color="#0563C1")
                    pieces.append((_run_text(r), fmt))
        if prefix and pieces:
            pieces.insert(0, (prefix, pieces[0][1]))
        for text, fmt in pieces:
            if text:
                para.add_run(text, char_pr_id_ref=self.dst.styles.ensure_run(**fmt))

    def _run_format(self, run: Run, p: Paragraph, level: int | None) -> dict:
        """직접 서식 → 글자 스타일 → 문단 스타일 → 문서 기본값 순으로 실제 서식을 구한다."""
        styles = _style_chain(run.style) + _style_chain(p.style)
        fonts = [run.font] + [s.font for s in styles]

        def pick(attr):
            for f in fonts:
                v = getattr(f, attr)
                if v is not None:
                    return v
            return None

        bold = pick("bold")
        size = pick("size")
        size_pt = size.pt if size is not None else self._default_size
        if level is not None:
            bold = True if bold is None else bold
            if size is None:
                size_pt = _HEADING_PT.get(level, size_pt)
        fmt = {
            "bold": bool(bold),
            "italic": bool(pick("italic")),
            "underline": bool(pick("underline")),
            "strike": bool(pick("strike")),
        }
        if size_pt:
            fmt["size"] = round(size_pt * 2) / 2
        for f in fonts:
            c = f.color
            if c is not None and c.type is not None and c.rgb is not None:
                fmt["color"] = f"#{c.rgb}"
                break
        return fmt

    @property
    def _default_size(self) -> float | None:
        if not hasattr(self, "_dsize"):
            sz = self.src.styles.element.find(
                f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}/{qn('w:sz')}"
            )
            self._dsize = int(sz.get(qn("w:val"))) / 2 if sz is not None else None
        return self._dsize

    def _picture(self, blob: bytes, ext: str, w_emu: int | None, h_emu: int | None, align: str | None) -> None:
        if ext not in _IMAGE_FORMATS:
            self._skipped.add(f"{ext.upper()} 형식 그림")
            return
        kw = {}
        if w_emu and h_emu:
            kw = {"width_mm": w_emu / EMU_PER_MM, "height_mm": h_emu / EMU_PER_MM}
        try:
            self.dst.add_picture(blob, "jpg" if ext == "jpeg" else ext, align=align or "CENTER", **kw)
            self.n_image += 1
        except Exception as exc:  # noqa: BLE001
            self.warnings.append(f"그림 1개를 넣지 못했습니다({exc}).")

    # ---------- 표 ----------
    def _table(self, t: Table) -> None:
        grid = _table_grid(t)
        if not grid:
            return
        n_rows = len(grid)
        n_cols = max(len(r) for r in grid)
        if self._first_unused:  # 표가 문서 맨 앞이면 첫 빈 문단은 그대로 둔다
            self._first_unused = False
        widths = _grid_widths(t)
        if not (len(widths) == n_cols and all(widths)):
            widths = []
        kw = {"width": sum(widths) * 5} if widths else {}  # twip(1/1440in) → HWPUNIT(1/7200in): ×5
        try:
            ht = self.dst.add_table(n_rows, n_cols, **kw)
        except Exception:  # noqa: BLE001 - 너비 지정 실패 시 기본 너비
            ht = self.dst.add_table(n_rows, n_cols)
        if widths:
            try:
                ht.set_column_widths([w * 5 for w in widths])
            except Exception:  # noqa: BLE001
                pass

        merges = []
        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                if cell is None:
                    continue
                tc, rs, cs = cell
                self._fill_cell(ht.cell(r, c), tc)
                if rs > 1 or cs > 1:
                    merges.append((r, c, r + rs - 1, c + cs - 1))
        # 뒤에서부터 병합해야 앞 셀 좌표가 흔들리지 않는다
        for r1, c1, r2, c2 in sorted(merges, reverse=True):
            try:
                ht.merge_cells(r1, c1, min(r2, n_rows - 1), min(c2, n_cols - 1))
            except Exception as exc:  # noqa: BLE001
                self.warnings.append(f"표 셀 병합 1건을 적용하지 못했습니다({exc}).")
        self.n_table += 1

    def _fill_cell(self, hcell, tc) -> None:
        paras = [Paragraph(p, self.src) for p in tc.iter(qn("w:p"))]
        if any(True for _ in tc.iter(qn("w:tbl"))):
            self._skipped.add("표 안의 표(안쪽 표는 글자만 옮김)")
        first = True
        for p in paras:
            if first:
                hp = hcell.paragraphs[0]
                first = False
            else:
                hp = hcell.add_paragraph("")
            self._fill_runs(hp, p, self._list_prefix(p), _heading_level(p))
            align = _alignment(p)
            if align:
                self.dst.styles.apply_paragraph_format(paragraphs=[hp], alignment=align)

    def _note_unsupported(self, el) -> None:
        if next(el.iter(qn("w:footnoteReference")), None) is not None:
            self._skipped.add("각주")
        if next(el.iter("{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath"), None) is not None:
            self._skipped.add("수식")
        if next(el.iter("{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}wsp"), None) is not None:
            self._skipped.add("도형·글상자")


# ---------- DOCX 해석 도우미 ----------
def _run_text(r) -> str:
    out = []
    for child in r.iterchildren():
        tag = child.tag
        if tag == qn("w:t"):
            out.append(child.text or "")
        elif tag == qn("w:tab"):
            out.append("\t")
        elif tag in (qn("w:br"), qn("w:cr")) and child.get(qn("w:type")) not in ("page", "column"):
            out.append(" ")
        elif tag == qn("w:noBreakHyphen"):
            out.append("-")
    return "".join(out)


def _heading_level(p: Paragraph) -> int | None:
    name = (p.style.name if p.style is not None else "") or ""
    m = re.match(r"(?:Heading|제목)\s*(\d)", name, re.I)
    if m:
        return min(max(int(m.group(1)), 1), 6)
    if name.lower() == "title" or name == "제목":
        return 1
    lvl = p._p.find(f"{qn('w:pPr')}/{qn('w:outlineLvl')}")
    if lvl is not None:
        v = int(lvl.get(qn("w:val"), "9"))
        if v < 6:
            return v + 1
    return None


def _style_num_pr(style):
    for st in _style_chain(style):
        ppr = st.element.find(qn("w:pPr"))
        num_pr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if num_pr is not None:
            return num_pr
    return None


def _numbering_format(src, num_id: str, ilvl: int) -> tuple[str | None, str | None]:
    """numbering.xml에서 (numFmt, lvlText)를 찾는다."""
    try:
        numbering = src.part.numbering_part.element
    except (KeyError, NotImplementedError, AttributeError):
        return None, None
    num = next((n for n in numbering.findall(qn("w:num")) if n.get(qn("w:numId")) == num_id), None)
    if num is None:
        return None, None
    abs_el = num.find(qn("w:abstractNumId"))
    abs_id = abs_el.get(qn("w:val")) if abs_el is not None else None
    abstract = next((a for a in numbering.findall(qn("w:abstractNum")) if a.get(qn("w:abstractNumId")) == abs_id), None)
    if abstract is None:
        return None, None
    lvl = next((lv for lv in abstract.findall(qn("w:lvl")) if lv.get(qn("w:ilvl")) == str(ilvl)), None)
    if lvl is None:
        return None, None
    fmt = lvl.find(qn("w:numFmt"))
    text = lvl.find(qn("w:lvlText"))
    return (fmt.get(qn("w:val")) if fmt is not None else None, text.get(qn("w:val")) if text is not None else None)


_GANADA = "가나다라마바사아자차카타파하"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _format_number(n: int, fmt: str) -> str:
    if fmt in ("lowerLetter", "upperLetter"):
        s = chr(ord("a") + (n - 1) % 26)
        return s.upper() if fmt == "upperLetter" else s
    if fmt in ("lowerRoman", "upperRoman"):
        vals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
        out, k = "", n
        for v, r in vals:
            while k >= v:
                out, k = out + r, k - v
        return out.upper() if fmt == "upperRoman" else out
    if fmt == "ganada":
        return _GANADA[(n - 1) % len(_GANADA)]
    if fmt in ("decimalEnclosedCircle", "decimalEnclosedCircleChinese") and n <= len(_CIRCLED):
        return _CIRCLED[n - 1]
    return str(n)


def _alignment(p: Paragraph) -> str | None:
    jc = p._p.find(f"{qn('w:pPr')}/{qn('w:jc')}")
    if jc is None:
        style = p.style
        while style is not None and jc is None:
            ppr = style.element.find(qn("w:pPr"))
            jc = ppr.find(qn("w:jc")) if ppr is not None else None
            style = style.base_style
    if jc is None:
        return None
    return _ALIGN.get(jc.get(qn("w:val"), ""))


def _has_page_break(el) -> bool:
    return any(br.get(qn("w:type")) == "page" for br in el.iter(qn("w:br")))


def _page_break_before(p: Paragraph) -> bool:
    return bool(p.paragraph_format.page_break_before)


def _style_chain(style) -> list:
    chain = []
    while style is not None and len(chain) < 20:
        chain.append(style)
        style = style.base_style
    return chain


def _images(p: Paragraph):
    """문단 안 그림: (바이트, 확장자, 너비EMU, 높이EMU)."""
    part = p.part
    for drawing in p._p.iter(qn("w:drawing")):
        blip = next(drawing.iter(qn("a:blip")), None)
        if blip is None:
            continue
        rid = blip.get(qn("r:embed"))
        if not rid or rid not in part.related_parts:
            continue
        img = part.related_parts[rid]
        ext = (img.partname.ext or "").lower()
        extent = next(drawing.iter(qn("wp:extent")), None)
        w = int(extent.get("cx")) if extent is not None else None
        h = int(extent.get("cy")) if extent is not None else None
        yield img.blob, ext, w, h


def _grid_widths(t: Table) -> list[int]:
    grid = t._tbl.find(qn("w:tblGrid"))
    if grid is None:
        return []
    return [int(gc.get(qn("w:w"), "0") or 0) for gc in grid.iter(qn("w:gridCol"))]


def _table_grid(t: Table):
    """표를 격자로 펼친다. 각 칸은 (tc, 행병합수, 열병합수) 또는 가려진 칸이면 None."""
    rows = t._tbl.findall(qn("w:tr"))
    grid: list[list] = []
    anchors: dict[int, tuple[int, int]] = {}  # 열 → (시작 행, 시작 열) : 세로 병합 진행 중
    for r, tr in enumerate(rows):
        row: list = []
        c = 0
        before = tr.find(f"{qn('w:trPr')}/{qn('w:gridBefore')}")
        for _ in range(int(before.get(qn("w:val"), "0")) if before is not None else 0):
            row.append(("", 1, 1))
            c += 1
        for tc in tr.findall(qn("w:tc")):
            tcpr = tc.find(qn("w:tcPr"))
            span_el = tcpr.find(qn("w:gridSpan")) if tcpr is not None else None
            span = int(span_el.get(qn("w:val"), "1")) if span_el is not None else 1
            vm = tcpr.find(qn("w:vMerge")) if tcpr is not None else None
            if vm is not None and vm.get(qn("w:val"), "continue") != "restart" and c in anchors:
                ar, ac = anchors[c]
                tc0, rs, cs = grid[ar][ac]
                grid[ar][ac] = (tc0, rs + 1, cs)
                row.extend([None] * span)
            else:
                row.append((tc, 1, span))
                row.extend([None] * (span - 1))
                if vm is not None:
                    anchors[c] = (r, c)
                else:
                    anchors.pop(c, None)
            c += span
        grid.append(row)
    n_cols = max((len(r) for r in grid), default=0)
    for row in grid:
        row.extend([("", 1, 1)] * (n_cols - len(row)))
    # 빈 칸 자리표시("")는 빈 셀로 처리
    return [[None if cell is None else (cell if cell[0] != "" else (_EmptyTc(), 1, 1)) for cell in row] for row in grid]


class _EmptyTc:
    def iter(self, _tag):
        return iter(())

"""PDF → 한글 변환 테스트: 작은 PDF를 직접 만들어 HWPX/HWP로 바꾸고 다시 열어 확인한다."""
import io

import pytest
from hwpx import HwpxDocument
from PIL import Image

from app.docs.hwp_convert import convert_to_hwp
from app.docs.pdf_to_hwp import convert_pdf


def _pdf(pages: list[str]) -> bytes:
    """페이지별 그리기 명령(content stream)으로 최소 PDF를 만든다. F1=Helvetica, F2=Helvetica-Bold."""
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        None,  # Pages: 아래에서 채움
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    kids = []
    for content in pages:
        stream = content.encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{content}\nendstream")
        content_no = len(objs)
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {content_no} 0 R "
            "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def _text(x, y, s, font="F1", size=11):
    return f"BT /{font} {size} Tf {x} {y} Td ({s}) Tj ET\n"


def make_sample_pdf() -> bytes:
    p1 = _text(240, 780, "Business Plan", "F2", 18)
    # 오른쪽 끝(약 x=540)까지 찬 줄 + 이어지는 줄 → 한 문단
    p1 += _text(56, 740, "This project develops an energy management solution for small manufacturers and")
    p1 += _text(56, 726, "verifies the savings at three pilot sites.")
    p1 += _text(56, 700, "- Second item starts a new paragraph.")
    # 3열 x 3행 표, 첫 행의 2~3열 병합
    xs, ys = [56, 200, 350, 500], [660, 640, 620, 600]
    lines = ""
    for y in ys:
        lines += f"{xs[0]} {y} m {xs[-1]} {y} l S\n"
    for x in xs:
        top = ys[0]
        if x == xs[2]:
            top = ys[1]  # 첫 행에서는 2·3열 사이 세로선 없음(병합)
        lines += f"{x} {top} m {x} {ys[-1]} l S\n"
    p1 += lines
    p1 += _text(60, 646, "Item") + _text(204, 646, "R&D budget")
    p1 += _text(60, 626, "Year 1") + _text(204, 626, "Grant") + _text(354, 626, "100")
    p1 += _text(60, 606, "Year 2") + _text(204, 606, "Matching") + _text(354, 606, "20")
    p1 += _text(285, 40, "- 1 -")
    p2 = _text(56, 780, "Second page text.") + _text(285, 40, "- 2 -")
    return _pdf([p1, p2])


@pytest.fixture
def sample_pdf() -> bytes:
    return make_sample_pdf()


def test_pdf_to_hwpx_text_table_pages(sample_pdf):
    res = convert_pdf(sample_pdf, "hwpx")
    assert res.tables == 1
    doc = HwpxDocument.open(io.BytesIO(res.data))
    assert doc.validate().issues == ()
    text = doc.text.plain()
    assert "Business Plan" in text
    # 줄이 넘어간 문장은 한 문단으로 이어진다
    assert "small manufacturers and verifies the savings at three pilot sites." in text
    assert "- Second item starts a new paragraph." in text
    assert "- 1 -" not in text and "- 2 -" not in text  # 쪽 번호는 뺀다
    assert "Second page text." in text
    paras = [p for p in doc.paragraphs if p.text.strip()]
    assert any(p.text.startswith("- Second item") for p in paras)
    table = [t for p in doc.paragraphs for t in p.tables][0]
    assert table.cell(0, 1).span == (1, 2)  # 병합된 머리글
    assert table.cell(0, 1).text == "R&D budget"
    assert table.cell(2, 2).text == "20"


def test_pdf_title_is_bold_and_centered(sample_pdf):
    doc = HwpxDocument.open(io.BytesIO(convert_pdf(sample_pdf).data))
    title = next(p for p in doc.paragraphs if p.text == "Business Plan")
    run = next(r for r in title.runs if r.text)
    style = doc.styles.char_property(run.char_pr_id_ref)
    assert "bold" in style.child_attributes
    assert style.attributes["height"] == "1800"
    align = doc.styles.paragraph_property(title.para_pr_id_ref)
    assert "CENTER" in str(align)


def test_pdf_to_hwp_binary(sample_pdf):
    res = convert_pdf(sample_pdf, "hwp")
    assert res.data[:8] == bytes.fromhex("D0CF11E0A1B11AE1")
    assert "R&D budget" in HwpxDocument.open(io.BytesIO(res.data)).text.plain()


def test_scanned_pdf_becomes_page_image():
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, "PDF", resolution=72)
    res = convert_pdf(buf.getvalue())
    assert res.images == 1 and res.paragraphs == 0
    assert any("스캔본" in w for w in res.warnings)


def test_dispatch_by_extension(sample_pdf):
    assert convert_to_hwp("a.PDF", sample_pdf).tables == 1
    with pytest.raises(ValueError):
        convert_to_hwp("a.txt", b"x")

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import setup  # noqa: E402

import streamlit as st  # noqa: E402

from app.docs.hwp_convert import SUPPORTED, convert_to_hwp  # noqa: E402

setup("워드·PDF → 한글 변환", "🔁")
st.caption("워드(.docx)나 PDF를 올리면 한/글 문서(.hwpx/.hwp)로 바로 바꿉니다. 한/글 프로그램 없이 서버에서 변환하며, 올린 파일은 저장하지 않습니다.")

col1, col2 = st.columns([2, 1])
fmt_label = col1.radio(
    "저장 형식",
    ["HWPX (한/글 2014 이상, 권장)", "HWP (예전 한/글 버전 호환)"],
    horizontal=True,
)
fmt = "hwpx" if fmt_label.startswith("HWPX") else "hwp"
keep_pages = col2.checkbox("PDF 쪽 나눔 유지", value=True, help="PDF의 각 쪽을 한/글에서도 새 쪽에서 시작합니다.")

files = st.file_uploader("워드·PDF 파일 선택 (여러 개 가능)", type=SUPPORTED, accept_multiple_files=True)
st.caption("옛 형식(.doc)은 워드에서 .docx로 저장한 뒤 올려 주세요. 스캔한 PDF(그림)는 글자 인식 없이 쪽을 그림으로 넣습니다.")

if files:
    results = []
    for f in files:
        name = f"{Path(f.name).stem}.{fmt}"
        try:
            res = convert_to_hwp(f.name, f.getvalue(), fmt, keep_pdf_pages=keep_pages)
        except Exception as exc:  # noqa: BLE001 - 파일별로 실패를 보여주고 나머지는 계속
            results.append({"파일": f.name, "결과": f"실패: {exc}", "문단": "", "표": "", "그림": "", "_data": None, "_warn": []})
            continue
        results.append({
            "파일": f.name, "결과": "완료", "문단": res.paragraphs, "표": res.tables, "그림": res.images,
            "_data": res.data, "_warn": res.warnings, "_name": name,
        })

    st.dataframe(
        [{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
        hide_index=True, use_container_width=True,
    )
    ok = [r for r in results if r["_data"]]
    for i, r in enumerate(ok):
        cols = st.columns([3, 1])
        cols[0].markdown(f"**{r['_name']}**")
        cols[1].download_button("내려받기", r["_data"], file_name=r["_name"], key=f"dl_{i}_{r['_name']}")
        for w in r["_warn"]:
            st.markdown(f"<span class='badge-check'>확인 필요</span> {w}", unsafe_allow_html=True)
    if len(ok) > 1:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for r in ok:
                z.writestr(r["_name"], r["_data"])
        st.download_button("모두 내려받기 (ZIP)", buf.getvalue(), file_name=f"한글변환_{fmt}.zip", type="primary")

with st.expander("변환 범위 안내"):
    st.markdown(
        """
**워드(.docx)**: 본문·제목, 굵게·기울임·밑줄·취소선·글자 크기·색, 정렬, 쪽 나누기, 번호·글머리표 목록,
표(셀 병합·열 너비), 그림, 용지 크기·여백을 옮깁니다. 머리말·꼬리말, 각주, 도형·글상자, 수식, 글꼴 종류는 옮기지 않습니다.

**PDF**: PDF에는 문단·표 구조가 없어 글자 위치로 다시 짜 맞춥니다.
- 글자 크기·굵기, 가운데·오른쪽 정렬, 들여쓰기, 쪽 나눔을 옮깁니다.
- 선으로 그려진 표는 셀 병합까지 표로 되살립니다. 선 없는 표는 일반 글자로 들어갑니다.
- 그림은 해당 영역을 이미지로 잘라 넣습니다. 쪽 번호(예: "- 3 -")는 뺍니다.
- 스캔한 PDF는 글자 인식(OCR)을 하지 않고 쪽 전체를 그림으로 넣습니다.

변환 후 한/글에서 열어 줄바꿈·표 모양·쪽 나눔을 한 번 확인하세요.
"""
    )

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import setup  # noqa: E402

import streamlit as st  # noqa: E402

from app.docs.docx_to_hwp import convert_docx  # noqa: E402

setup("워드 → 한글 변환", "🔁")
st.caption("워드 문서(.docx)를 올리면 한/글 문서(.hwpx/.hwp)로 바로 바꿉니다. 한/글 프로그램 없이 서버에서 변환하며, 올린 파일은 저장하지 않습니다.")

fmt_label = st.radio(
    "저장 형식",
    ["HWPX (한/글 2014 이상, 권장)", "HWP (예전 한/글 버전 호환)"],
    horizontal=True,
)
fmt = "hwpx" if fmt_label.startswith("HWPX") else "hwp"

files = st.file_uploader("워드 파일 선택 (여러 개 가능)", type=["docx"], accept_multiple_files=True)
st.caption("옛 형식(.doc)은 워드에서 '다른 이름으로 저장 → Word 문서(.docx)'로 바꾼 뒤 올려 주세요.")

if files:
    results = []
    for f in files:
        try:
            res = convert_docx(f.getvalue(), fmt)
        except Exception as exc:  # noqa: BLE001 - 파일별로 실패를 보여주고 나머지는 계속
            results.append({"파일": f.name, "결과": f"실패: {exc}", "문단": "", "표": "", "그림": "", "_data": None, "_warn": []})
            continue
        results.append({
            "파일": f.name, "결과": "완료", "문단": res.paragraphs, "표": res.tables, "그림": res.images,
            "_data": res.data, "_warn": res.warnings, "_name": f"{Path(f.name).stem}.{fmt}",
        })

    st.dataframe(
        [{k: v for k, v in r.items() if not k.startswith("_")} for r in results],
        hide_index=True, use_container_width=True,
    )
    ok = [r for r in results if r["_data"]]
    for r in ok:
        cols = st.columns([3, 1])
        cols[0].markdown(f"**{r['_name']}**")
        cols[1].download_button("내려받기", r["_data"], file_name=r["_name"], key=f"dl_{r['_name']}")
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
| 옮겨지는 것 | 옮겨지지 않는 것 |
|---|---|
| 본문 문단 순서, 제목(크기·굵기로 표시) | 머리말·꼬리말, 쪽 번호 |
| 굵게·기울임·밑줄·취소선·글자 크기·글자색 | 각주·미주, 메모, 변경 추적 |
| 문단 정렬, 쪽 나누기 | 도형·글상자·수식·차트 |
| 번호·글머리표 목록(기호를 글자로 적음) | 글꼴 종류(한/글 기본 글꼴 사용) |
| 표(가로·세로 셀 병합, 열 너비) | 표 안의 표(글자만 옮김) |
| 그림(PNG·JPG·GIF·BMP), 용지 크기·여백 | |

변환 후 한/글에서 열어 표 모양과 쪽 나눔을 한 번 확인하세요.
"""
    )

"""워드·PDF → 한글 변환기 (단독 웹앱).

정부지원사업 도우미와 별개로 배포하는 작은 앱이다. DB·API 키·비밀번호가 필요 없다.
Streamlit Community Cloud에서 Main file path를 `word2hwp/app.py`로 지정해 배포한다.
"""
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.docs.hwp_convert import SUPPORTED, convert_to_hwp  # noqa: E402

st.set_page_config(page_title="워드·PDF → 한글 변환기", page_icon="📄", layout="centered")
st.title("워드·PDF → 한글 변환기")
st.write("워드(.docx)나 PDF를 올리면 한/글 문서로 바로 바꿔 드립니다. 한/글 프로그램이 없어도 됩니다.")

fmt_label = st.radio(
    "저장 형식",
    ["HWPX (한/글 2014 이상, 권장)", "HWP (예전 한/글 버전 호환)"],
    horizontal=True,
)
fmt = "hwpx" if fmt_label.startswith("HWPX") else "hwp"
keep_pages = st.checkbox("PDF 쪽 나눔 유지", value=True, help="PDF의 각 쪽을 한/글에서도 새 쪽에서 시작합니다.")

files = st.file_uploader(
    "워드·PDF 파일을 끌어다 놓거나 눌러서 선택하세요 (여러 개 가능)",
    type=SUPPORTED,
    accept_multiple_files=True,
)
st.caption("옛 형식(.doc)은 워드에서 '다른 이름으로 저장 → Word 문서(.docx)'로 바꾼 뒤 올려 주세요. 스캔한 PDF(그림)는 글자 인식 없이 쪽을 그림으로 넣습니다. 올린 파일은 변환에만 쓰고 저장하지 않습니다.")

if files:
    done = []
    for i, f in enumerate(files):
        name = f"{Path(f.name).stem}.{fmt}"
        try:
            res = convert_to_hwp(f.name, f.getvalue(), fmt, keep_pdf_pages=keep_pages)
        except Exception as exc:  # noqa: BLE001 - 파일별로 실패를 보여주고 나머지는 계속
            st.error(f"{f.name}: 변환하지 못했습니다. 정상적으로 열리는 파일인지(암호가 걸린 PDF는 안 됨) 확인해 주세요. ({exc})")
            continue
        done.append((name, res.data))
        with st.container(border=True):
            cols = st.columns([3, 1])
            cols[0].markdown(f"**{name}**  \n문단 {res.paragraphs} · 표 {res.tables} · 그림 {res.images}")
            cols[1].download_button("내려받기", res.data, file_name=name, key=f"dl_{i}_{name}", use_container_width=True)
            for w in res.warnings:
                st.caption(f"⚠️ {w}")
    if len(done) > 1:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in done:
                z.writestr(name, data)
        st.download_button("모두 내려받기 (ZIP)", buf.getvalue(), file_name=f"한글변환_{fmt}.zip", type="primary", use_container_width=True)

with st.expander("무엇이 옮겨지나요?"):
    st.markdown(
        """
**워드(.docx)**
- 옮겨지는 것: 본문과 제목, 굵게·기울임·밑줄·취소선·글자 크기·글자색, 정렬, 쪽 나누기,
  번호·글머리표 목록, 표(셀 병합·열 너비), 그림(PNG·JPG·GIF·BMP), 용지 크기·여백
- 옮겨지지 않는 것: 머리말·꼬리말, 각주, 도형·글상자, 수식, 글꼴 종류(한/글 기본 글꼴 사용)

**PDF** — PDF에는 문단·표 구조가 없어 글자 위치로 다시 짜 맞춥니다.
- 글자 크기·굵기, 정렬, 들여쓰기, 쪽 나눔을 옮깁니다. 쪽 번호(예: "- 3 -")는 뺍니다.
- 선으로 그려진 표는 셀 병합까지 표로 되살립니다. 선 없는 표는 일반 글자로 들어갑니다.
- 그림은 해당 영역을 이미지로 잘라 넣습니다.
- 스캔한 PDF는 글자 인식(OCR)을 하지 않고 쪽 전체를 그림으로 넣습니다.

변환 후 한/글에서 열어 줄바꿈·표 모양·쪽 나눔을 한 번 확인해 주세요.
"""
    )

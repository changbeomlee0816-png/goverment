import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import db, select_obj, session_scope, setup  # noqa: E402

from datetime import date  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.collectors.base import SIDO  # noqa: E402
from app.collectors.manual_upload import save_upload  # noqa: E402
from app.db.models import Company, Document, PriorResearch  # noqa: E402
from app.docs.company_extract import extract_company_fields  # noqa: E402
from app.docs.extract import ExtractError, extract_text  # noqa: E402

setup("기업정보", "🏢")
CERTS = ["벤처", "이노비즈", "메인비즈", "여성기업", "장애인기업", "사회적기업", "소부장", "강소기업", "뿌리기업", "ISO9001", "ISO14001"]
CEO = ["여성", "청년", "장애인", "외국인", "재창업"]
DOC_TYPES = ["사업자등록증", "재무제표", "표준재무제표증명", "국세납세증명서", "지방세납세증명서", "4대보험 가입자명부", "중소기업확인서", "벤처기업확인서", "기업부설연구소 인정서", "이노비즈 확인서", "메인비즈 확인서", "법인등기부등본", "기타"]

s = db()
companies = s.scalars(select(Company).order_by(Company.id)).all()
choice = select_obj("편집할 기업", companies, lambda c: c.name, none_label="➕ 새 기업 등록")

with st.expander("📄 사업자등록증·재무제표 업로드로 자동 입력 (추출값은 확인 후 저장)"):
    up = st.file_uploader("PDF/HWP/DOCX/TXT", type=["pdf", "hwp", "hwpx", "docx", "txt"], key="bizcert")
    if up:
        try:
            fields = extract_company_fields(extract_text(up.name, up.getvalue()))
            st.session_state["prefill"] = fields
            st.json({k: str(v) for k, v in fields.items()} or {"결과": "추출된 값 없음"})
            st.caption("아래 폼에 미리 채워졌습니다. 확인 후 저장하세요.")
        except ExtractError as exc:
            st.error(str(exc))

pre = st.session_state.get("prefill", {}) if choice is None else {}
c = choice


def v(attr, default=None):
    if c is not None:
        return getattr(c, attr)
    return pre.get(attr, default)


with st.form("company"):
    col1, col2, col3 = st.columns(3)
    name = col1.text_input("기업명*", v("name", ""))
    biz_no = col2.text_input("사업자등록번호", v("biz_no", "") or "")
    founded = col3.date_input("설립일(개업연월일)", v("founded_date"), min_value=date(1950, 1, 1), max_value=date.today())
    col1, col2, col3 = st.columns(3)
    sido_opts = [""] + SIDO
    sido = col1.selectbox("소재지(시·도)", sido_opts, index=sido_opts.index(v("region_sido") or ""))
    sigungu = col2.text_input("시·군·구", v("region_sigungu", "") or "")
    industry_code = col3.text_input("업종코드(KSIC)", v("industry_code", "") or "")
    industry_name = st.text_input("업종명", v("industry_name", "") or "")
    col1, col2, col3, col4 = st.columns(4)
    revenue = col1.number_input("전년도 매출(원)", min_value=0, value=int(v("revenue_last_year") or 0), step=10_000_000)
    employees = col2.number_input("상시근로자(명)", min_value=0, value=int(v("employees") or 0))
    rnd_staff = col3.number_input("연구인력(명)", min_value=0, value=int(v("rnd_staff") or 0))
    rnd_ratio = col4.number_input("연구개발비 비율(%)", min_value=0.0, value=float(v("rnd_ratio") or 0.0))
    col1, col2, col3 = st.columns(3)
    has_lab = col1.checkbox("기업부설연구소(전담부서) 보유", bool(v("has_rnd_lab", False)))
    export_amount = col2.number_input("수출액(원)", min_value=0, value=int(v("export_amount") or 0), step=10_000_000)
    patents = col3.number_input("보유 특허(건)", min_value=0, value=int(v("patents") or 0))
    certs = st.multiselect("인증", CERTS + [x for x in (v("certifications") or []) if x not in CERTS], default=v("certifications") or [])
    ceo = st.multiselect("대표자 특성", CEO, default=[x for x in (v("ceo_attributes") or []) if x in CEO])
    saved = st.form_submit_button("저장", type="primary")

if saved:
    if not name.strip():
        st.error("기업명을 입력하세요.")
    else:
        with session_scope() as w:
            obj = w.get(Company, c.id) if c else Company()
            obj.name, obj.biz_no, obj.founded_date = name.strip(), biz_no or None, founded
            obj.region_sido, obj.region_sigungu = sido or None, sigungu or None
            obj.industry_code, obj.industry_name = industry_code or None, industry_name or None
            obj.revenue_last_year, obj.employees, obj.rnd_staff, obj.rnd_ratio = int(revenue), int(employees), int(rnd_staff), float(rnd_ratio)
            obj.has_rnd_lab, obj.export_amount, obj.patents = has_lab, int(export_amount), int(patents)
            obj.certifications, obj.ceo_attributes = certs, ceo
            if not c:
                w.add(obj)
            w.flush()
            st.session_state["company_id"] = obj.id
        st.session_state.pop("prefill", None)
        st.success("저장했습니다.")
        st.rerun()

if c is None:
    st.stop()

if st.button("🗑️ 이 기업 삭제", help="아이템·선행연구·서류가 함께 삭제됩니다"):
    with session_scope() as w:
        w.delete(w.get(Company, c.id))
    st.rerun()

st.subheader("선행연구·실적")
rows = [{"id": p.id, "과제명": p.title, "구분": p.type, "기간": p.period, "결과": p.result, "지재권": p.ip, "연관성": p.relevance} for p in c.prior_research]
df = pd.DataFrame(rows or [], columns=["id", "과제명", "구분", "기간", "결과", "지재권", "연관성"])
edited = st.data_editor(
    df, num_rows="dynamic", hide_index=True, width="stretch", key="prior",
    column_config={"id": None, "구분": st.column_config.SelectboxColumn(options=["국가R&D", "자체", "수요처"])},
)
if st.button("선행연구 저장"):
    with session_scope() as w:
        comp = w.get(Company, c.id)
        comp.prior_research.clear()
        w.flush()
        for _, r in edited.iterrows():
            if str(r.get("과제명") or "").strip():
                comp.prior_research.append(PriorResearch(title=r["과제명"], type=r.get("구분") or "자체", period=r.get("기간"), result=r.get("결과"), ip=r.get("지재권"), relevance=r.get("연관성")))
    st.success("저장했습니다.")
    st.rerun()

st.subheader("서류 보관함")
today = date.today()
docs = [{"id": d.id, "서류": d.doc_type, "발급일": d.issued_date, "만료일": d.expires_date,
         "상태": ("만료" if d.expires_date and d.expires_date < today else f"D-{(d.expires_date - today).days}" if d.expires_date else "-"),
         "파일": d.file_name or (Path(d.file_path).name if d.file_path else "")} for d in c.documents]
st.dataframe(pd.DataFrame(docs), hide_index=True, width="stretch")
with st.form("doc"):
    col1, col2, col3 = st.columns(3)
    doc_type = col1.selectbox("서류 종류", DOC_TYPES)
    issued = col2.date_input("발급일", today)
    expires = col3.date_input("만료일(없으면 비움)", None)
    f = st.file_uploader("파일(선택, 10MB 이하 — DB에 함께 저장)")
    if st.form_submit_button("서류 추가"):
        if f and f.size > 10 * 1024 * 1024:
            st.error("10MB 이하 파일만 보관할 수 있습니다.")
            st.stop()
        path = str(save_upload(f.name, f.getvalue(), subdir="documents")) if f else None
        with session_scope() as w:
            w.add(Document(company_id=c.id, doc_type=doc_type, issued_date=issued, expires_date=expires, file_path=path,
                           file_name=f.name if f else None, file_data=f.getvalue() if f else None))
        st.rerun()
sel_id = st.selectbox("선택한 서류", [None] + [d["id"] for d in docs], format_func=lambda i: "-" if i is None else next(f"{d['서류']} {d['파일']}" for d in docs if d["id"] == i))
if sel_id:
    col1, col2 = st.columns(2)
    doc = s.get(Document, sel_id)
    if doc.file_data:
        col1.download_button("파일 다운로드", doc.file_data, doc.file_name or "document")
    if col2.button("서류 삭제"):
        with session_scope() as w:
            w.delete(w.get(Document, sel_id))
        st.rerun()

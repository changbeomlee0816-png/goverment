import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import llm_status, need_check, pick_company, pick_item, session_scope, setup  # noqa: E402

import io  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.db.models import Application  # noqa: E402
from app.matching.report import DISCLAIMER, run_matching, to_dataframe, to_markdown  # noqa: E402

setup("매칭", "🎯")
llm_on = llm_status()
company = pick_company()
if not company:
    st.stop()
item = pick_item(company.id)
col1, col2 = st.columns(2)
use_llm = col1.checkbox("추천 이유 AI 생성(상위 N건)", value=llm_on, disabled=not llm_on)
include_closed = col2.checkbox("마감 공고 포함", False)

if st.button("매칭 실행", type="primary"):
    with st.spinner("하드필터 → 점수화 → 설명 생성..."):
        with session_scope() as w:
            rows = run_matching(w, company.id, item.id if item else None, use_llm=use_llm, include_closed=include_closed)
            st.session_state["match"] = {
                "df": to_dataframe(rows),
                "md": to_markdown(rows, company.name, item.name if item else None),
                "rows": [
                    {"match_id": r.match_id, "ann_id": r.announcement.id, "title": r.announcement.title, "eligible": r.eligible,
                     "detail": r.score_detail, "due": r.announcement.apply_end, "total": r.score_total}
                    for r in rows
                ],
            }

m = st.session_state.get("match")
if not m:
    st.stop()
df: pd.DataFrame = m["df"]
if df.empty:
    st.info("대상 공고가 없습니다. [공고]에서 수집·등록하세요.")
    st.stop()

ok = df[df["자격"] == "충족"]
for header, key in (("① 부처(중앙정부)", "①부처"), ("② 지자체·지역기관", "②지자체·지역기관")):
    st.subheader(header)
    part = ok[ok["구분"] == key]
    if part.empty:
        st.caption("해당 없음")
    for _, r in part.iterrows():
        with st.container(border=True):
            st.markdown(f"**[{r['유형']}] {r['사업명']}** — **{r['점수']}점**")
            st.markdown(f"접수기간: {r['접수기간']} · 지원규모: {r['지원규모']} · 기관: {r['기관']}")
            st.markdown(f"이유: {r['이유']}")
            if r["확인 필요"]:
                st.markdown(need_check("확인 필요") + " " + r["확인 필요"], unsafe_allow_html=True)
            if r["원문링크"]:
                st.markdown(f"[원문]({r['원문링크']})" if str(r["원문링크"]).startswith("http") else f"원문: {r['원문링크']}")

st.subheader("요약표")
st.dataframe(ok[["구분", "유형", "사업명", "접수기간", "지원규모", "점수"]], hide_index=True, width="stretch")

with st.expander("차원별 점수표"):
    detail_rows = []
    for r in m["rows"]:
        if not r["eligible"]:
            continue
        row = {"사업명": r["title"], "총점": r["total"]}
        for k, d in r["detail"].items():
            row[d["label"]] = f"{d['points']} ({d['note']})"
        detail_rows.append(row)
    st.dataframe(pd.DataFrame(detail_rows), hide_index=True, width="stretch")

with st.expander(f"자격 불충족 {len(df) - len(ok)}건"):
    st.dataframe(df[df["자격"] == "불충족"][["구분", "사업명", "이유"]], hide_index=True, width="stretch")

st.caption(DISCLAIMER)

col1, col2 = st.columns(2)
col1.download_button("보고서(Markdown)", m["md"].encode("utf-8"), "매칭보고서.md")
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as xw:
    df.to_excel(xw, index=False, sheet_name="매칭결과")
col2.download_button("결과(Excel)", buf.getvalue(), "매칭결과.xlsx")

st.subheader("신청 관리에 추가")
eligible_rows = [r for r in m["rows"] if r["eligible"]]
if eligible_rows:
    pick_i = st.selectbox("사업", range(len(eligible_rows)), format_func=lambda i: f"{eligible_rows[i]['title']} ({eligible_rows[i]['total']}점)")
    pick = eligible_rows[pick_i]
    if st.button("신청 관리에 추가 → 계획서 작성"):
        with session_scope() as w:
            app = Application(match_id=pick["match_id"], announcement_id=pick["ann_id"], company_id=company.id,
                              item_id=item.id if item else None, title=pick["title"], status="검토", due_date=pick["due"])
            w.add(app)
            w.flush()
            st.session_state["application_id"] = app.id
        st.success("추가했습니다. [계획서] 페이지에서 작성하세요.")

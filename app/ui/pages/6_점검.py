import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import db, llm_status, pick_company, select_obj, session_scope, setup  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.models import Application, Item, PlanTemplate  # noqa: E402
from app.docs.extract import ExtractError, extract_text  # noqa: E402
from app.review.checklist import ReviewInput, from_text, rule_checks, virtual_scoring  # noqa: E402
from app.writer.context import build_reference  # noqa: E402
from app.writer.export import ordered_drafts  # noqa: E402

setup("자체 점검(레드팀)", "🔍")
llm_on = llm_status()
s = db()

mode = st.radio("점검 대상", ["작성 중인 초안", "외부 계획서 업로드(PDF/HWP)"], horizontal=True)
inp, reference, app = None, "", None

if mode == "작성 중인 초안":
    company = pick_company()
    if not company:
        st.stop()
    apps = s.scalars(select(Application).where(Application.company_id == company.id).order_by(Application.id.desc())).all()
    apps = [a for a in apps if a.drafts]
    if not apps:
        st.info("초안이 있는 신청건이 없습니다. [계획서]에서 먼저 작성하세요.")
        st.stop()
    app = select_obj("신청건", apps, lambda a: f"#{a.id} {a.title}")
    sections_meta = {x["key"]: x for x in app.template.sections}
    sections = [{"key": d.section_key, "title": d.section_title or d.section_key, "content": d.content,
                 "eval_item": sections_meta.get(d.section_key, {}).get("eval_item"),
                 "max_score": sections_meta.get(d.section_key, {}).get("max_score")} for d in ordered_drafts(app)]
    item = s.get(Item, app.item_id) if app.item_id else None
    inp = ReviewInput(sections=sections, eval_items=app.template.eval_items or [], indicator_names=[i.name for i in item.indicators] if item else [])
    reference = build_reference(app)
else:
    up = st.file_uploader("계획서 파일", type=["pdf", "hwp", "hwpx", "docx", "txt"])
    templates = s.scalars(select(PlanTemplate).order_by(PlanTemplate.id.desc())).all()
    tpl = select_obj("평가표 기준(양식)", templates, lambda t: f"{t.year} {t.name} {t.version}", none_label="(일반 R&D 기준)")
    if up:
        try:
            inp = from_text(extract_text(up.name, up.getvalue()), tpl.eval_items if tpl else [])
            st.caption(f"인식된 섹션 {len(inp.sections)}개")
        except ExtractError as exc:
            st.error(str(exc))

if inp and st.button("점검 실행", type="primary"):
    findings = rule_checks(inp)
    with st.spinner("가상 채점 중..."):
        scoring = virtual_scoring(inp, findings, reference, use_llm=llm_on)
    st.session_state["review"] = {"findings": findings, "scoring": scoring}

res = st.session_state.get("review")
if res:
    st.subheader("규칙 점검")
    if res["findings"]:
        st.dataframe(pd.DataFrame([{"중요도": f.severity, "점검": f.check, "섹션/항목": f.section, "내용": f.detail} for f in res["findings"]]),
                     hide_index=True, width="stretch")
    else:
        st.success("규칙 점검에서 지적사항이 없습니다.")
    sc = res["scoring"]
    st.subheader(f"가상 채점 — 총 {sc.get('total', '?')}점 ({'AI 평가위원' if sc.get('method') == 'llm' else '규칙 기반 추정'})")
    st.dataframe(pd.DataFrame(sc.get("items", [])).rename(columns={"eval_item": "평가항목", "max_score": "배점", "grade": "등급", "score": "점수",
                                                                  "evidence": "근거", "weakness": "감점 사유", "suggestion": "수정 제안"}),
                 hide_index=True, width="stretch")
    st.info(sc.get("overall", ""))

if app:
    st.subheader("부서별 검토 요청")
    dept = dict(app.dept_review or {})
    cols = st.columns(3)
    new = {d: cols[i].checkbox(f"{d} 검토 완료", dept.get(d, False), key=f"dept_{d}") for i, d in enumerate(["개발", "생산", "영업"])}
    if new != dept and st.button("검토 상태 저장"):
        with session_scope() as w:
            w.get(Application, app.id).dept_review = new
        st.success("저장했습니다.")

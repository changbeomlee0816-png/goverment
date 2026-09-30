import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import db, highlight_unsourced, llm_status, need_check, pick_company, pick_item, select_obj, session_scope, setup  # noqa: E402

from datetime import datetime  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.collectors.manual_upload import save_upload  # noqa: E402
from app.db.models import Announcement, Application, PlanDraft, PlanTemplate  # noqa: E402
from app.docs.extract import ExtractError, extract_text  # noqa: E402
from app.llm.claude_client import LLMRefused  # noqa: E402
from app.writer import planner, tools  # noqa: E402
from app.writer.export import export_docx, plain_text_for_hwp  # noqa: E402
from app.writer.template_parser import parse_template  # noqa: E402

setup("사업계획서 작성", "✍️")
llm_on = llm_status()
s = db()

# ------------------------------------------------------------ 0. 신청건 선택/생성
company = pick_company()
if not company:
    st.stop()
apps = s.scalars(select(Application).where(Application.company_id == company.id).order_by(Application.id.desc())).all()
app = select_obj("신청건", apps, lambda a: f"#{a.id} {a.title} [{a.status}]", none_label="➕ 새 계획서",
                 default_id=st.session_state.get("application_id"))

if app is None:
    with st.form("new_app"):
        anns = s.scalars(select(Announcement).order_by(Announcement.id.desc())).all()
        ann = select_obj("대상 공고(선택)", anns, lambda a: a.title, none_label="(공고 없이 작성)")
        item = pick_item(company.id, key="new_item")
        title = st.text_input("계획서 제목", "")
        if st.form_submit_button("만들기", type="primary"):
            with session_scope() as w:
                tpl = planner.ensure_default_template(w)
                new = Application(company_id=company.id, announcement_id=ann.id if ann else None, item_id=item.id if item else None,
                                  title=title or (ann.title if ann else (item.name if item else "사업계획서")), status="작성중",
                                  due_date=ann.apply_end if ann else None, template_id=tpl.id)
                w.add(new)
                w.flush()
                st.session_state["application_id"] = new.id
            st.rerun()
    st.stop()

st.session_state["application_id"] = app.id
if app.template_id is None:
    with session_scope() as w:
        w.get(Application, app.id).template_id = planner.ensure_default_template(w).id
    st.rerun()

step1, step2, step3, step4, step5 = st.tabs(["① 양식·평가표", "② 섹션별 요구사항", "③ 인터뷰", "④ 보조도구", "⑤ 초안 작성·내보내기"])

# ------------------------------------------------------------ ① 양식
with step1:
    st.markdown(f"현재 양식: **{app.template.name}** ({app.template.version}, 파싱: {app.template.parsed_by}) · 섹션 {len(app.template.sections)}개 · 평가항목 {len(app.template.eval_items or [])}개")
    st.markdown("공고에 첨부된 **사업계획서 양식(HWP/HWPX/DOCX/PDF)**과 **평가표**를 올리면, 섹션 구조와 ※작성 지시문, 배점을 인식해 그 순서·지시에 맞춰 초안을 씁니다.")
    col1, col2 = st.columns(2)
    tpl_file = col1.file_uploader("사업계획서 양식", type=["hwp", "hwpx", "docx", "pdf", "txt"], key="tpl")
    eval_file = col2.file_uploader("평가표(선택)", type=["hwp", "hwpx", "docx", "pdf", "txt"], key="evl")
    col1, col2, col3 = st.columns(3)
    tpl_name = col1.text_input("양식 이름", tpl_file.name if tpl_file else "")
    tpl_year = col2.number_input("연도", 2000, 2100, datetime.now().year)
    use_llm_parse = col3.checkbox("AI로 구조화(표 안 지시문까지)", value=llm_on, disabled=not llm_on)
    if tpl_file and st.button("양식 분석·적용", type="primary"):
        try:
            tpl_text = extract_text(tpl_file.name, tpl_file.getvalue())
            eval_text = extract_text(eval_file.name, eval_file.getvalue()) if eval_file else None
            with st.spinner("양식 분석 중..."):
                sections, eval_items, parsed_by = parse_template(tpl_text, eval_text, use_llm=use_llm_parse)
            if not sections:
                st.error("섹션을 찾지 못했습니다. 번호 체계(1., 가., □ 등)가 있는 양식인지 확인하거나 AI 구조화를 사용하세요.")
            else:
                with session_scope() as w:
                    count = len(w.scalars(select(PlanTemplate).where(PlanTemplate.name == tpl_name)).all())
                    t = PlanTemplate(name=tpl_name or tpl_file.name, year=int(tpl_year), version=f"v{count + 1}",
                                     announcement_id=app.announcement_id,
                                     source_file=str(save_upload(tpl_file.name, tpl_file.getvalue(), "templates")),
                                     eval_source_file=str(save_upload(eval_file.name, eval_file.getvalue(), "templates")) if eval_file else None,
                                     raw_text=tpl_text, eval_raw_text=eval_text, sections=sections, eval_items=eval_items, parsed_by=parsed_by)
                    w.add(t)
                    w.flush()
                    w.get(Application, app.id).template_id = t.id
                st.success(f"섹션 {len(sections)}개, 평가항목 {len(eval_items)}개 인식. ② 탭에서 확인·수정하세요.")
                st.rerun()
        except ExtractError as exc:
            st.error(str(exc))
    templates = s.scalars(select(PlanTemplate).order_by(PlanTemplate.year.desc(), PlanTemplate.id.desc())).all()
    other = select_obj("저장된 양식으로 교체(연도별 버전)", templates, lambda t: f"{t.year} · {t.name} · {t.version}", default_id=app.template_id)
    if other.id != app.template_id and st.button("이 양식 사용"):
        with session_scope() as w:
            w.get(Application, app.id).template_id = other.id
        st.rerun()

# ------------------------------------------------------------ ② 요구사항
with step2:
    tpl = app.template
    st.markdown("섹션 제목·지시문·평가항목 연결을 확인하고 필요하면 수정하세요. (지시문은 `|`로 구분)")
    eval_opts = [""] + [e["key"] for e in tpl.eval_items or []]
    sec_df = pd.DataFrame([{"key": x["key"], "섹션": x["title"], "작성 지시문": " | ".join(x.get("instructions", [])),
                            "평가항목": x.get("eval_item") or "", "배점": x.get("max_score"), "분량": x.get("page_limit") or ""} for x in tpl.sections])
    sec_edit = st.data_editor(sec_df, num_rows="dynamic", hide_index=True, width="stretch", key=f"sec_{tpl.id}",
                              column_config={"평가항목": st.column_config.SelectboxColumn(options=eval_opts)})
    ev_df = pd.DataFrame(tpl.eval_items or [], columns=["key", "name", "max_score", "criteria"])
    ev_edit = st.data_editor(ev_df, num_rows="dynamic", hide_index=True, width="stretch", key=f"ev_{tpl.id}",
                             column_config={"key": "key", "name": "평가항목", "max_score": "배점", "criteria": "세부 기준"})
    if st.button("요구사항 저장"):
        new_sections = []
        for i, r in sec_edit.reset_index(drop=True).iterrows():
            if not str(r.get("섹션") or "").strip():
                continue
            new_sections.append({"key": r.get("key") or f"s{i + 1}", "title": r["섹션"], "level": 2,
                                 "instructions": [x.strip() for x in str(r.get("작성 지시문") or "").split("|") if x.strip()],
                                 "eval_item": r.get("평가항목") or None, "max_score": None if pd.isna(r.get("배점")) else r.get("배점"),
                                 "page_limit": r.get("분량") or None,
                                 "sample": next((x.get("sample", "") for x in tpl.sections if x["key"] == r.get("key")), "")})
        new_eval = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for _, r in ev_edit.iterrows() if str(r.get("name") or "").strip()]
        scores = {e["key"]: e.get("max_score") for e in new_eval}
        for x in new_sections:
            if x["eval_item"] and not x["max_score"]:
                x["max_score"] = scores.get(x["eval_item"])
        with session_scope() as w:
            t = w.get(PlanTemplate, tpl.id)
            t.sections, t.eval_items = new_sections, new_eval
        st.success("저장했습니다.")
        st.rerun()

# ------------------------------------------------------------ ③ 인터뷰
with step3:
    st.markdown("평가항목·지시문 대비 **부족한 정보**를 질문합니다. 답변은 초안 작성의 근거자료로만 쓰입니다(출처가 있으면 함께 적어주세요).")
    if st.button("질문 생성" + (" (AI)" if llm_on else " (규칙 기반)")):
        with st.spinner("질문 생성 중..."):
            with session_scope() as w:
                new = planner.generate_questions(w, w.get(Application, app.id), use_llm=llm_on)
        st.success(f"질문 {len(new)}개 추가")
        st.rerun()
    titles = {x["key"]: x["title"] for x in app.template.sections}
    answers = []
    for n, q in enumerate(app.interview or []):
        st.markdown(f"**Q{n + 1}. [{titles.get(q.get('section_key'), q.get('section_key'))}]** {q['question']}")
        if q.get("why"):
            st.caption(q["why"])
        answers.append(st.text_area("답변", q.get("answer", ""), key=f"ans_{app.id}_{n}", label_visibility="collapsed"))
    if app.interview:
        col1, col2 = st.columns(2)
        if col1.button("답변 저장", type="primary"):
            with session_scope() as w:
                a = w.get(Application, app.id)
                a.interview = [{**q, "answer": answers[i]} for i, q in enumerate(a.interview)]
            st.success("저장했습니다.")
        if col2.button("미답변 질문 삭제"):
            with session_scope() as w:
                a = w.get(Application, app.id)
                a.interview = [q for i, q in enumerate(a.interview) if answers[i].strip()]
            st.rerun()

# ------------------------------------------------------------ ④ 보조도구
with step4:
    extras = dict(app.extras or {})
    st.markdown("#### 시장규모 계산 (TAM-SAM-SOM)")
    m = extras.get("market", {})
    col1, col2, col3 = st.columns(3)
    tam = col1.number_input("TAM(원)", 0.0, value=float(m.get("tam", 0)), step=1e9, format="%.0f")
    sam_ratio = col2.number_input("SAM 비율(TAM 대비 %)", 0.0, 100.0, float(m.get("sam_ratio", 10)))
    som_ratio = col3.number_input("SOM 비율(SAM 대비 %)", 0.0, 100.0, float(m.get("som_ratio", 5)))
    tam_source = st.text_input("TAM 출처(필수)", m.get("tam_source", ""))
    col1, col2 = st.columns(2)
    sam_basis = col1.text_input("SAM 산출 근거", m.get("sam_basis", ""))
    som_basis = col2.text_input("SOM 산출 근거", m.get("som_basis", ""))
    market = tools.MarketSize(tam, sam_ratio, som_ratio, tam_source, sam_basis, som_basis)
    if tam:
        st.markdown(tools.market_table(market))

    st.markdown("#### 5개년 매출 계획 (A=B+D, C=B/A×100)")
    f = extras.get("forecast", {"start_year": datetime.now().year + 1, "rows": [{"B": 0, "D": 0, "export": 0} for _ in range(5)]})
    start_year = st.number_input("시작 연도", 2000, 2100, int(f["start_year"]))
    fdf = pd.DataFrame(f["rows"]).rename(columns={"B": "본 기술 매출 B(원)", "D": "기존 매출 D(원)", "export": "수출(원)"})
    fdf.index = [start_year + i for i in range(len(fdf))]
    fedit = st.data_editor(fdf, width="stretch", key=f"fc_{app.id}")
    rows = [{"B": r["본 기술 매출 B(원)"], "D": r["기존 매출 D(원)"], "export": r["수출(원)"]} for _, r in fedit.iterrows()]
    st.markdown(tools.revenue_table(tools.revenue_forecast(rows, int(start_year))))

    st.markdown("#### 업무분담표")
    rdf = pd.DataFrame(extras.get("roles", []), columns=["주체", "업무", "인력", "기간"])
    redit = st.data_editor(rdf, num_rows="dynamic", width="stretch", hide_index=True, key=f"roles_{app.id}")

    if st.button("보조도구 결과 저장", type="primary"):
        with session_scope() as w:
            a = w.get(Application, app.id)
            new_extras = dict(a.extras or {})
            if tam:
                new_extras["market"] = market.__dict__
            new_extras["forecast"] = {"start_year": int(start_year), "rows": rows}
            new_extras["roles"] = [r for r in redit.fillna("").to_dict("records") if any(str(v).strip() for v in r.values())]
            a.extras = new_extras
        st.success("저장했습니다. 초안 작성 시 사실자료로 반영됩니다.")

# ------------------------------------------------------------ ⑤ 초안
with step5:
    drafts = {d.section_key: d for d in s.scalars(select(PlanDraft).where(PlanDraft.application_id == app.id)).all()}
    col1, col2 = st.columns([1, 3])
    use_llm = col1.checkbox("AI 작성", value=llm_on, disabled=not llm_on, help="끄면 지시문 기반 작성 골격을 만듭니다")
    if col2.button("전체 섹션 초안 생성", type="primary"):
        progress = st.progress(0.0)
        for n, sec in enumerate(app.template.sections):
            try:
                with session_scope() as w:
                    planner.draft_section(w, w.get(Application, app.id), sec["key"], use_llm=use_llm)
            except LLMRefused as exc:
                st.warning(f"{sec['title']}: {exc}")
            progress.progress((n + 1) / len(app.template.sections))
        st.rerun()

    for sec in app.template.sections:
        d = drafts.get(sec["key"])
        req = planner.section_requirements(app.template, sec)
        header = sec["title"] + (f"  ·  {req['eval_item']} {req['max_score']}점" if req.get("eval_item") else "")
        with st.expander(header, expanded=False):
            if sec.get("instructions"):
                st.caption("작성 지시문: " + " / ".join(sec["instructions"]))
            extra = st.text_input("추가 요청(선택)", key=f"req_{app.id}_{sec['key']}", placeholder="예: 표를 하나 더 넣고 분량을 1페이지로")
            if st.button("이 섹션 초안 생성", key=f"gen_{app.id}_{sec['key']}"):
                with st.spinner("작성 중..."):
                    try:
                        with session_scope() as w:
                            planner.draft_section(w, w.get(Application, app.id), sec["key"], use_llm=use_llm, extra_request=extra)
                    except LLMRefused as exc:
                        st.warning(str(exc))
                st.rerun()
            if d:
                content = st.text_area("본문(Markdown, 직접 수정 가능)", d.content, height=320, key=f"c_{app.id}_{sec['key']}")
                col1, col2 = st.columns(2)
                if col1.button("수정 저장", key=f"save_{app.id}_{sec['key']}"):
                    with session_scope() as w:
                        w.get(PlanDraft, d.id).content = content
                    st.success("저장했습니다.")
                unsourced = planner.unsourced_sentences(content)
                missing = planner.missing_items(content)
                if unsourced or missing:
                    st.markdown(need_check(f"출처 없는 수치 {len(unsourced)} · 확인 필요 {len(missing)}"), unsafe_allow_html=True)
                with st.popover("미리보기(노란색=출처 없음/확인 필요)"):
                    st.markdown(highlight_unsourced(content), unsafe_allow_html=True)
                with col2.popover("HWP 붙여넣기용 텍스트"):
                    st.code(plain_text_for_hwp(content), language=None)
                if d.sources:
                    st.caption("출처: " + "; ".join(f"{x.get('claim', '')[:30]} → {x.get('source', '')}" for x in d.sources))

    st.divider()
    s.expire_all()
    fresh = s.get(Application, app.id)
    if fresh.drafts:
        st.download_button("📄 DOCX 내보내기(양식 순서)", export_docx(fresh), f"사업계획서_{app.id}.docx",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import db, llm_status, need_check, select_obj, session_scope, setup  # noqa: E402

import json  # noqa: E402
from datetime import date  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.collectors.eligibility import extract_for_announcement  # noqa: E402
from app.collectors.manual_upload import annual_candidates, register_announcement  # noqa: E402
from app.collectors.run import collect_once  # noqa: E402
from app.db.models import Announcement, EligibilityRule  # noqa: E402
from app.docs.extract import ExtractError, extract_text  # noqa: E402

setup("공고", "📢")
llm_on = llm_status()
tab_list, tab_collect, tab_upload, tab_rules, tab_annual = st.tabs(["공고 목록", "자동 수집", "공고문 업로드", "자격요건 추출·확인", "연간 후보 리스트"])

s = db()
today = date.today()

with tab_list:
    col1, col2, col3, col4 = st.columns(4)
    kw = col1.text_input("검색어")
    level = col2.multiselect("구분", ["부처", "지자체", "지역기관"])
    kind = col3.multiselect("유형", ["R&D", "비R&D"])
    open_only = col4.checkbox("접수 중·예정만", True)
    anns = s.scalars(select(Announcement).order_by(Announcement.apply_end.is_(None), Announcement.apply_end)).all()
    rows = []
    for a in anns:
        if kw and kw not in (a.title + (a.summary or "")):
            continue
        if level and a.level not in level:
            continue
        if kind and ("R&D" if a.is_rnd else "비R&D") not in kind:
            continue
        if open_only and a.apply_end and a.apply_end < today:
            continue
        rows.append({
            "id": a.id, "구분": a.level, "유형": "R&D" if a.is_rnd else "비R&D", "분야": a.category, "사업명": a.title,
            "기관": a.agency or a.exec_agency or "확인 필요", "접수시작": a.apply_start, "마감": a.apply_end,
            "D-day": (a.apply_end - today).days if a.apply_end else None, "지역": a.region, "출처": a.source,
            "자격요건": f"{sum(r.verified for r in a.rules)}/{len(a.rules)} 확인", "링크": a.url,
        })
    st.caption(f"{len(rows)}건")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"링크": st.column_config.LinkColumn(), "id": None})
    st.caption("마감일이 비어 있는 공고는 '확인 필요' — 원문을 확인하세요.")

with tab_collect:
    st.markdown("기업마당·K-Startup API를 호출해 원본을 `data/snapshots/YYYYMMDD/`에 저장하고 DB에 반영합니다(제목+기관+접수기간 기준 중복 제거).")
    st.code("python -m app.collectors.run --schedule --extract   # 설정 주기마다 자동 수집\n# 또는 cron: 10 6 * * * cd <프로젝트> && python -m app.collectors.run --extract", language="bash")
    extract = st.checkbox("신규 공고 자격요건 자동 추출", value=False)
    if st.button("지금 수집", type="primary"):
        with st.spinner("수집 중..."):
            results = collect_once(extract=extract)
        for r in results:
            if r["ok"]:
                st.success(f"{r['source']}: {r['fetched']}건 수신 · 신규 {r['created']} · 갱신 {r['updated']}")
            else:
                st.error(f"{r['source']}: {r['error']}")

with tab_upload:
    st.markdown("공고문(PDF/HWP/HWPX/DOCX)을 올리면 텍스트를 추출해 공고로 등록합니다. 제목·기관·기간은 규칙으로 추정하므로 확인 후 수정하세요.")
    up = st.file_uploader("공고문 파일", type=["pdf", "hwp", "hwpx", "docx", "txt"], key="ann_up")
    col1, col2, col3 = st.columns(3)
    o_title = col1.text_input("사업명(비우면 자동 추정)")
    o_agency = col2.text_input("기관(비우면 자동 추정)")
    o_url = col3.text_input("원문 URL")
    if up and st.button("등록"):
        try:
            with session_scope() as w:
                ann = register_announcement(w, up.name, up.getvalue(), {"title": o_title, "agency": o_agency, "url": o_url})
                st.success(f"등록: {ann.title} (마감 {ann.apply_end or '확인 필요'})")
                st.text_area("추출 텍스트 미리보기", (ann.full_text or "")[:3000], height=240)
        except ExtractError as exc:
            st.error(str(exc))

with tab_rules:
    anns = s.scalars(select(Announcement).order_by(Announcement.id.desc())).all()
    if not anns:
        st.info("공고가 없습니다.")
    else:
        a = select_obj("공고", anns, lambda a: f"[{a.level}] {a.title}")
        st.markdown(f"**기관** {a.agency or '-'} / {a.exec_agency or '-'} · **접수** {a.apply_start or '?'} ~ {a.apply_end or need_check()} · **지원규모** {a.budget_text or need_check()}", unsafe_allow_html=True)
        with st.expander("공고 내용"):
            st.write(a.eligibility_text or "")
            st.write(a.summary or "")
            if a.url:
                st.markdown(f"[원문 링크]({a.url})")
        if st.button("자격요건 추출" + (" (AI)" if llm_on else " (규칙 기반)")):
            with st.spinner("추출 중..."):
                with session_scope() as w:
                    res = extract_for_announcement(w, w.get(Announcement, a.id))
            st.success(f"{res['count']}개 요건 추출({res['method']}). 근거 문장을 확인하고 '확인' 체크하세요.")
            st.rerun()
        rules = s.scalars(select(EligibilityRule).where(EligibilityRule.announcement_id == a.id)).all()
        df = pd.DataFrame([{"id": r.id, "확인": r.verified, "항목": r.field, "조건": r.operator, "값": r.value, "근거 문장": r.evidence_text} for r in rules],
                          columns=["id", "확인", "항목", "조건", "값", "근거 문장"])
        edited = st.data_editor(
            df, hide_index=True, width="stretch", num_rows="dynamic", key=f"rules_{a.id}",
            column_config={
                "id": None,
                "항목": st.column_config.SelectboxColumn(options=["years_in_business", "region_sido", "revenue_krw", "employees", "industry", "certification", "has_rnd_lab", "ceo_attribute", "trl", "other"]),
                "조건": st.column_config.SelectboxColumn(options=["<=", ">=", "<", ">", "==", "between", "in", "not_in", "has_any", "has_all", "note"]),
            },
        )
        st.caption('값 예: 7 / ["충남","대전"] / [3,6] / true. 근거 문장이 없는 요건은 매칭 시 "확인 필요"로 표시됩니다.')
        if st.button("자격요건 저장"):
            with session_scope() as w:
                for r in w.scalars(select(EligibilityRule).where(EligibilityRule.announcement_id == a.id)).all():
                    w.delete(r)
                w.flush()
                for _, r in edited.iterrows():
                    if not r.get("항목"):
                        continue
                    value = r.get("값")
                    try:
                        json.loads(value)
                    except (TypeError, ValueError):
                        value = json.dumps(value, ensure_ascii=False) if value not in (None, "") else None
                    w.add(EligibilityRule(announcement_id=a.id, field=r["항목"], operator=r.get("조건") or "note", value=value,
                                          evidence_text=r.get("근거 문장"), verified=bool(r.get("확인"))))
            st.success("저장했습니다.")
            st.rerun()

with tab_annual:
    st.markdown("연초 **예산기금운용계획 사업설명자료**·**부처 합동설명회 자료**를 올리면 3월 이후 사업, 신규·단상·단하 사업, 수혜자 키워드로 걸러 연간 후보 리스트를 만듭니다.")
    up = st.file_uploader("자료 파일", type=["pdf", "hwp", "hwpx", "docx", "txt"], key="annual")
    kws = st.text_input("수혜자·분야 키워드(쉼표)", "중소기업, 에너지, 탄소")
    min_month = st.slider("공고 예정월(이후)", 1, 12, 3)
    if up and st.button("후보 추출"):
        try:
            text = extract_text(up.name, up.getvalue())
            cands = annual_candidates(text, [k.strip() for k in kws.split(",") if k.strip()], min_month)
            st.caption(f"{len(cands)}건 — 근거 문장은 원문 그대로입니다.")
            df = pd.DataFrame(cands)
            st.dataframe(df, hide_index=True, width="stretch")
            if not df.empty:
                st.download_button("CSV 다운로드", df.to_csv(index=False).encode("utf-8-sig"), "연간후보.csv")
        except ExtractError as exc:
            st.error(str(exc))

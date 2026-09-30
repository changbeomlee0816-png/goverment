import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import db, pick_company, select_obj, session_scope, setup  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.collectors import ntis  # noqa: E402
from app.collectors.bizinfo import CollectorError  # noqa: E402
from app.db.models import Item, PerformanceIndicator  # noqa: E402

setup("아이템 포트폴리오", "🧩")
company = pick_company()
if not company:
    st.stop()

s = db()
items = s.scalars(select(Item).where(Item.company_id == company.id).order_by(Item.priority, Item.id)).all()

st.subheader("포트폴리오 요약")
if items:
    st.dataframe(
        pd.DataFrame([{"우선순위": i.priority, "아이템": i.name, "구분": i.portfolio_type, "TRL": f"{i.trl_current or '?'}→{i.trl_target or '?'}",
                       "기간(월)": i.dev_period_months, "예산(억)": round((i.budget_krw or 0) / 1e8, 2), "선호유형": i.preferred_type, "성능지표 수": len(i.indicators)} for i in items]),
        hide_index=True, width="stretch",
    )
    st.caption("Discovery: 탐색 단계 아이디어 · Project: 과제화 대상 · Asset: 사업화·보유 자산")

item = select_obj("편집할 아이템", items, lambda i: i.name, none_label="➕ 새 아이템")

st.markdown("#### ① 요약맵 — 이슈 → 성능지표 → 측정방식 순서로 입력")
with st.form("item"):
    name = st.text_input("아이템명*", item.name if item else "")
    issue = st.text_area("해결하려는 이슈(문제)", item.issue if item else "", help="현장의 문제와 그로 인한 비용·손실")
    summary = st.text_area("아이템 요약", item.summary if item else "")
    keywords = st.text_input("키워드(쉼표 구분)", ", ".join(item.keywords) if item else "", help="매칭 목적 적합도 계산에 사용")
    col1, col2, col3, col4 = st.columns(4)
    ptype = col1.selectbox("포트폴리오 구분", ["Discovery", "Project", "Asset"], index=["Discovery", "Project", "Asset"].index(item.portfolio_type) if item else 1)
    pref = col2.selectbox("선호 유형", ["R&D", "비R&D", "바우처"], index=["R&D", "비R&D", "바우처"].index(item.preferred_type) if item else 0)
    trl_cur = col3.number_input("현재 TRL", 1, 9, int(item.trl_current or 3) if item else 3)
    trl_tgt = col4.number_input("목표 TRL", 1, 9, int(item.trl_target or 6) if item else 6)
    col1, col2, col3, col4 = st.columns(4)
    period = col1.number_input("개발기간(개월)", 0, 120, int(item.dev_period_months or 12) if item else 12)
    budget = col2.number_input("필요 예산(원)", 0, value=int(item.budget_krw or 0) if item else 0, step=10_000_000)
    staff = col3.number_input("투입 인력(명)", 0, 500, int(item.staff_count or 0) if item else 0)
    priority = col4.number_input("우선순위(1=높음)", 1, 9, int(item.priority) if item else 3)
    scope = st.text_area("개발 범위", item.scope if item else "")
    saved = st.form_submit_button("저장", type="primary")

if saved and name.strip():
    with session_scope() as w:
        obj = w.get(Item, item.id) if item else Item(company_id=company.id)
        obj.name, obj.issue, obj.summary = name.strip(), issue, summary
        obj.keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        obj.portfolio_type, obj.preferred_type = ptype, pref
        obj.trl_current, obj.trl_target = int(trl_cur), int(trl_tgt)
        obj.dev_period_months, obj.budget_krw, obj.staff_count, obj.priority = int(period), int(budget), int(staff), int(priority)
        obj.scope = scope
        if not item:
            w.add(obj)
    st.success("저장했습니다.")
    st.rerun()

if not item:
    st.stop()

st.markdown("#### ② 성능지표 · ③ 측정방식")
ind_df = pd.DataFrame(
    [{"성능지표": x.name, "단위": x.unit, "현재 수준": x.baseline, "최종 목표": x.target, "측정방법": x.measure_method, "공인시험기관": x.test_org, "근거·출처": x.source} for x in item.indicators],
    columns=["성능지표", "단위", "현재 수준", "최종 목표", "측정방법", "공인시험기관", "근거·출처"],
)
edited = st.data_editor(ind_df, num_rows="dynamic", hide_index=True, width="stretch", key="ind")
col1, col2 = st.columns(2)
if col1.button("성능지표 저장"):
    with session_scope() as w:
        obj = w.get(Item, item.id)
        obj.indicators.clear()
        w.flush()
        for _, r in edited.iterrows():
            if str(r.get("성능지표") or "").strip():
                obj.indicators.append(PerformanceIndicator(name=r["성능지표"], unit=r.get("단위"), baseline=r.get("현재 수준"), target=r.get("최종 목표"),
                                                           measure_method=r.get("측정방법"), test_org=r.get("공인시험기관"), source=r.get("근거·출처")))
    st.success("저장했습니다.")
    st.rerun()
if col2.button("🗑️ 아이템 삭제"):
    with session_scope() as w:
        w.delete(w.get(Item, item.id))
    st.rerun()

st.markdown("#### NTIS 연관과제 검색 (벤치마킹 참고용 — 자동 입력하지 않음)")
q = st.text_input("검색어", " ".join(item.keywords[:3]) if item.keywords else item.name)
if st.button("NTIS 검색"):
    try:
        results = ntis.search_projects(q)
        st.dataframe(pd.DataFrame(results), hide_index=True, width="stretch")
        st.caption("참고용입니다. 유사 과제의 성능목표를 벤치마킹하되, 수치는 직접 검증 후 입력하세요.")
    except CollectorError as exc:
        st.warning(str(exc))
    except Exception as exc:  # noqa: BLE001
        st.error(f"NTIS 조회 실패: {type(exc).__name__}")

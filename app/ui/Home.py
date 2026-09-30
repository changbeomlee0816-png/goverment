"""정부지원사업 매칭·사업계획서 도우미 — 홈(대시보드).

실행: streamlit run app/ui/Home.py
"""
import common  # noqa: F401  (경로 설정)
from common import db, need_check, setup

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from app.collectors.run import collect_once
from app.config import env, load_settings
from app.db.models import Announcement, Application, Company
from app.manage.alerts import deadline_alerts, document_alerts

setup("정부지원사업 매칭·사업계획서 도우미", "🏛️")
s = db()

# 공고 자동 갱신: 마지막 수집이 수집 주기보다 오래됐으면 앱을 열 때 수집(키가 있는 소스만)
cfg = load_settings()["collect"]
last = s.scalar(select(func.max(Announcement.collected_at)).where(Announcement.source != "manual"))
stale = last is None or datetime.now() - last > timedelta(hours=float(cfg["interval_hours"]))
has_key = env("BIZINFO_API_KEY") or env("DATA_GO_KR_KEY")
if cfg.get("auto_on_open", True) and stale and has_key and not st.session_state.get("_auto_collected"):
    st.session_state["_auto_collected"] = True
    with st.spinner("최신 공고를 수집하는 중..."):
        results = collect_once(extract=False)
    st.toast(" / ".join(f"{r['source']}: 신규 {r['created']}건" if r["ok"] else f"{r['source']}: 실패" for r in results))

if not s.scalar(select(func.count(Company.id))):
    st.info("등록된 기업이 없습니다. [기업정보]에서 등록하거나, 샘플 데이터로 먼저 둘러보세요.")
    if st.button("샘플 데이터 불러오기(에너지 관리 솔루션 기업·공고 3건)"):
        from app.db.seed import seed
        from app.db.session import session_scope

        with session_scope() as w:
            seed(w)
        st.rerun()

c1, c2, c3, c4 = st.columns(4)
c1.metric("등록 기업", s.scalar(select(func.count(Company.id))))
c2.metric("수집 공고", s.scalar(select(func.count(Announcement.id))))
c3.metric("최근 수집", last.strftime("%m-%d %H:%M") if last else "-")
c4.metric("진행 중 신청", s.scalar(select(func.count(Application.id)).where(Application.status.in_(["검토", "작성중", "내부검토"]))))

st.subheader("알림")
alerts = deadline_alerts(s) + document_alerts(s)
if alerts:
    st.dataframe(
        pd.DataFrame([{"구분": a.kind, "대상": a.title, "기한": a.due, "D-day": f"D-{a.days_left}" if a.days_left >= 0 else f"D+{-a.days_left} (경과)"} for a in alerts]),
        hide_index=True, width="stretch",
    )
else:
    st.caption("마감 임박 신청건·만료 예정 서류가 없습니다.")

st.subheader("설정 상태")
keys = {
    "ANTHROPIC_API_KEY (AI 작성·채점)": env("ANTHROPIC_API_KEY"),
    "BIZINFO_API_KEY (기업마당)": env("BIZINFO_API_KEY"),
    "DATA_GO_KR_KEY (K-Startup)": env("DATA_GO_KR_KEY"),
    "NTIS_API_KEY (NTIS)": env("NTIS_API_KEY"),
}
for name, value in keys.items():
    st.markdown(f"- {name}: " + ("✅ 설정됨" if value else need_check("미설정")), unsafe_allow_html=True)
st.caption(f"공고 자동 수집 주기: {load_settings()['collect']['interval_hours']}시간 — `python -m app.collectors.run --schedule --extract`")

st.subheader("사용 순서")
st.markdown(
    """
1. **기업정보** — 기업·선행연구·서류 보관함 등록
2. **포트폴리오** — 아이템(이슈 → 성능지표 → 측정방식) 등록
3. **공고** — 기업마당·K-Startup 수집 또는 공고문(PDF/HWP) 업로드, 자격요건 추출·확인
4. **매칭** — 자격 하드필터 + 점수화 → 부처/지자체 분리 보고서
5. **계획서** — 양식(HWP/HWPX/DOCX/PDF)·평가표 업로드 → 인터뷰 → 섹션 초안 → DOCX
6. **점검** — 규칙 점검 + 평가위원 가상 채점
7. **캘린더** — 칸반/리스트/캘린더, 제출서류 체크리스트
"""
)

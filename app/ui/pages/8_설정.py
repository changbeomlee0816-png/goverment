import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import setup  # noqa: E402

import streamlit as st  # noqa: E402

from app.config import PROMPT_DIR, load_settings, save_settings  # noqa: E402
from app.matching.scoring import DIM_LABELS  # noqa: E402

setup("설정", "⚙️")
cfg = load_settings()

st.subheader("매칭 가중치")
cols = st.columns(len(DIM_LABELS))
weights = {k: cols[i].number_input(label, 0, 100, int(cfg["matching"]["weights"].get(k, 0))) for i, (k, label) in enumerate(DIM_LABELS.items())}
st.caption(f"합계 {sum(weights.values())} (합계가 100이 아니어도 100점 만점으로 환산)")
top_n = st.number_input("AI 추천 이유 생성 상위 N건", 0, 100, int(cfg["matching"].get("llm_reason_top_n", 10)))

st.subheader("공고 수집")
col1, col2, col3 = st.columns(3)
interval = col1.number_input("수집 주기(시간)", 1, 168, int(cfg["collect"]["interval_hours"]))
auto_open = col3.checkbox("앱을 열 때 주기가 지났으면 자동 수집", bool(cfg["collect"].get("auto_on_open", True)))
sources = col2.multiselect("수집 소스", ["bizinfo", "kstartup"], default=cfg["collect"]["sources"])
col1, col2, col3 = st.columns(3)
biz_cnt = col1.number_input("기업마당 조회 건수", 1, 500, int(cfg["collect"]["bizinfo"].get("searchCnt", 100)))
hashtags = col2.text_input("기업마당 해시태그(예: 금융,서울)", cfg["collect"]["bizinfo"].get("hashtags", ""))
ks_pages = col3.number_input("K-Startup 페이지 수(100건/페이지)", 1, 20, int(cfg["collect"]["kstartup"].get("pages", 2)))

st.subheader("관심 지역·분야 / 알림")
regions = st.text_input("관심 지역(쉼표)", ",".join(cfg["interest"].get("regions", [])))
tags = st.text_input("관심 분야 해시태그(쉼표)", ",".join(cfg["interest"].get("hashtags", [])))
days = st.text_input("마감 알림 D-day(쉼표)", ",".join(map(str, cfg["alerts"].get("deadline_days", [14, 7, 3]))))
exp_days = st.number_input("서류 만료 알림(일 전)", 1, 365, int(cfg["alerts"].get("document_expiry_days", 30)))
recipients = st.text_input("알림 수신자 이메일(쉼표, 향후 메일 발송용)", ",".join(cfg["alerts"].get("recipients", [])))

st.subheader("AI 모델")
col1, col2, col3 = st.columns(3)
model = col1.text_input("모델", cfg["llm"].get("model", "claude-opus-5-5"))
effort = col2.selectbox("effort", ["low", "medium", "high", "xhigh", "max"], ["low", "medium", "high", "xhigh", "max"].index(cfg["llm"].get("effort", "high")))
fallbacks = col3.checkbox("거절 시 자동 대체 모델(fallback)", bool(cfg["llm"].get("use_fallbacks", True)))

if st.button("설정 저장", type="primary"):
    cfg["matching"]["weights"] = weights
    cfg["matching"]["llm_reason_top_n"] = int(top_n)
    cfg["collect"].update({"interval_hours": int(interval), "sources": sources, "auto_on_open": auto_open})
    cfg["collect"]["bizinfo"].update({"searchCnt": int(biz_cnt), "hashtags": hashtags})
    cfg["collect"]["kstartup"].update({"pages": int(ks_pages)})
    cfg["interest"] = {"regions": [x.strip() for x in regions.split(",") if x.strip()], "hashtags": [x.strip() for x in tags.split(",") if x.strip()]}
    cfg["alerts"] = {"deadline_days": [int(x) for x in days.split(",") if x.strip().isdigit()], "document_expiry_days": int(exp_days),
                     "recipients": [x.strip() for x in recipients.split(",") if x.strip()]}
    cfg["llm"] = {"model": model, "effort": effort, "use_fallbacks": fallbacks}
    save_settings(cfg)
    st.success("저장했습니다 (config/settings.json).")

st.subheader("프롬프트 파일 (app/llm/prompts/*.md — git으로 버전 관리)")
files = sorted(PROMPT_DIR.glob("*.md"))
f = st.selectbox("파일", files, format_func=lambda p: p.name)
text = st.text_area("내용", f.read_text(encoding="utf-8"), height=360)
if st.button("프롬프트 저장"):
    f.write_text(text, encoding="utf-8")
    st.success(f"{f.name} 저장")

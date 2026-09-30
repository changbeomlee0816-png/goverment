import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402,F401
from common import db, select_obj, session_scope, setup  # noqa: E402

import calendar  # noqa: E402
from datetime import date  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db.models import Application  # noqa: E402
from app.manage.alerts import APPLICATION_STATUSES, build_checklist, deadline_alerts, document_alerts  # noqa: E402

setup("신청 관리", "🗓️")
s = db()
today = date.today()

for a in deadline_alerts(s):
    st.warning(f"⏰ 마감 D-{a.days_left}: {a.title} ({a.due})")
for a in document_alerts(s):
    st.warning(f"📄 서류 {'만료' if a.days_left < 0 else f'만료 D-{a.days_left}'}: {a.title} ({a.due})")

apps = s.scalars(select(Application).order_by(Application.due_date.is_(None), Application.due_date)).all()
view = st.radio("보기", ["칸반", "리스트", "캘린더"], horizontal=True)

if view == "칸반":
    cols = st.columns(len(APPLICATION_STATUSES))
    for col, status in zip(cols, APPLICATION_STATUSES):
        col.markdown(f"**{status}**")
        for a in [x for x in apps if x.status == status]:
            with col.container(border=True):
                st.markdown(f"<small>{a.title}</small>", unsafe_allow_html=True)
                if a.due_date:
                    st.caption(f"마감 {a.due_date} (D{(a.due_date - today).days:+d})".replace("D+", "D+").replace("D-", "D-"))
                new = st.selectbox("상태", APPLICATION_STATUSES, APPLICATION_STATUSES.index(status), key=f"st_{a.id}", label_visibility="collapsed")
                if new != status:
                    with session_scope() as w:
                        w.get(Application, a.id).status = new
                    st.rerun()
elif view == "리스트":
    df = pd.DataFrame([{"id": a.id, "사업": a.title, "상태": a.status, "마감": a.due_date, "담당": a.owner or "", "메모": a.memo or ""} for a in apps],
                      columns=["id", "사업", "상태", "마감", "담당", "메모"])
    edited = st.data_editor(df, hide_index=True, width="stretch", disabled=["id", "사업"],
                            column_config={"상태": st.column_config.SelectboxColumn(options=APPLICATION_STATUSES), "마감": st.column_config.DateColumn()})
    if st.button("저장"):
        with session_scope() as w:
            for _, r in edited.iterrows():
                a = w.get(Application, int(r["id"]))
                a.status, a.owner, a.memo = r["상태"], r["담당"] or None, r["메모"] or None
                a.due_date = r["마감"] if pd.notna(r["마감"]) else None
        st.rerun()
else:
    col1, col2 = st.columns(2)
    year = col1.number_input("연도", 2000, 2100, today.year)
    month = col2.number_input("월", 1, 12, today.month)
    by_day: dict[int, list[str]] = {}
    for a in apps:
        if a.due_date and a.due_date.year == year and a.due_date.month == month:
            by_day.setdefault(a.due_date.day, []).append(a.title)
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(int(year), int(month))
    html = ["<table style='width:100%;border-collapse:collapse;table-layout:fixed'><tr>"]
    html += [f"<th style='border:1px solid #ddd;padding:4px'>{d}</th>" for d in ["일", "월", "화", "수", "목", "금", "토"]]
    html.append("</tr>")
    for week in weeks:
        html.append("<tr>")
        for d in week:
            items = "".join(f"<div style='font-size:0.75em;background:#e8f0fb;margin:2px 0;padding:1px 3px'>{t[:24]}</div>" for t in by_day.get(d, []))
            mark = "font-weight:bold;color:#1f5fbf" if (d == today.day and month == today.month and year == today.year) else ""
            html.append(f"<td style='border:1px solid #ddd;vertical-align:top;height:80px;padding:4px'><div style='{mark}'>{d or ''}</div>{items}</td>")
        html.append("</tr>")
    html.append("</table>")
    st.markdown("".join(html), unsafe_allow_html=True)

st.subheader("제출서류 체크리스트")
if apps:
    a = select_obj("신청건", apps, lambda x: f"#{x.id} {x.title}")
    checklist = build_checklist(s, a)
    if not checklist:
        st.caption("공고에서 추출된 제출서류가 없습니다. 공고 자격요건 추출(AI) 후 다시 확인하세요.")
    else:
        df = pd.DataFrame([{"완료": c["done"], "서류": c["doc_type"], "보관함": "보유(유효)" if c["vault_valid"] else ("보유(만료)" if c["in_vault"] else "없음"), "발급처": c["issuer"]} for c in checklist])
        edited = st.data_editor(df, hide_index=True, width="stretch", disabled=["서류", "보관함", "발급처"])
        if st.button("체크리스트 저장"):
            with session_scope() as w:
                w.get(Application, a.id).checklist = [{**c, "done": bool(edited.iloc[i]["완료"])} for i, c in enumerate(checklist)]
            st.success("저장했습니다.")

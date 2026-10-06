"""Streamlit 공통 유틸."""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.db.models import Company, Item  # noqa: E402
from app.db.session import make_session_factory, session_scope  # noqa: E402,F401
from app.llm import claude_client  # noqa: E402

ACCENT = "#1f5fbf"


def load_cloud_secrets() -> None:
    """Streamlit Cloud의 Secrets(st.secrets) 최상위 값을 환경변수로 옮긴다(.env와 같은 방식으로 읽도록)."""
    try:
        items = dict(st.secrets)
    except Exception:  # noqa: BLE001 - secrets.toml이 없으면 .env만 사용
        return
    for key, value in items.items():
        if isinstance(value, (str, int, float, bool)) and not os.environ.get(key):
            os.environ[key] = str(value)


def require_password() -> None:
    """APP_PASSWORD가 설정돼 있으면 접속 비밀번호를 요구한다(공개 URL 배포 시 사내 정보 보호)."""
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected or st.session_state.get("_authed"):
        return
    st.title("정부지원사업 도우미")
    pw = st.text_input("접속 비밀번호", type="password")
    if pw:
        if hmac.compare_digest(pw, expected):
            st.session_state["_authed"] = True
            st.rerun()
        st.error("비밀번호가 올바르지 않습니다.")
    st.stop()


def setup(title: str, icon: str = "📋") -> None:
    old = st.session_state.pop("_db", None)
    if old is not None:
        old.close()  # 이전 실행의 조회 세션 연결 반환
    st.set_page_config(page_title=f"{title} · 지원사업 도우미", page_icon=icon, layout="wide")
    load_cloud_secrets()
    require_password()
    st.markdown(
        f"""<style>
        .badge-check {{background:#fff3b0;color:#6b5500;padding:1px 6px;border-radius:4px;font-size:0.8em;}}
        .badge-ok {{background:{ACCENT};color:white;padding:1px 6px;border-radius:4px;font-size:0.8em;}}
        mark {{background:#fff3b0;}}
        </style>""",
        unsafe_allow_html=True,
    )
    st.title(title)


def db():
    """실행(rerun)마다 하나씩 쓰는 조회용 세션. 변경은 session_scope() 사용."""
    if "_db" not in st.session_state:
        try:
            st.session_state["_db"] = make_session_factory()()
        except OperationalError as exc:
            show_db_error(exc)
    return st.session_state["_db"]


def show_db_error(exc: Exception) -> None:
    """DB 접속 실패 원인을 비밀번호를 가린 채 보여주고 실행을 멈춘다."""
    from app.config import database_url
    from app.db.session import describe_url, diagnose_url, redact

    url = database_url()
    st.error("데이터베이스에 접속하지 못했습니다. Streamlit Secrets의 DATABASE_URL을 확인하세요.")
    for hint in diagnose_url(url):
        st.warning(hint)
    st.markdown("**접속 정보(비밀번호 제외)**")
    st.json(describe_url(url))
    st.markdown("**원인 메시지**")
    st.code(redact(str(getattr(exc, "orig", exc)), url), language=None)
    st.caption("자주 있는 원인: 비밀번호 오타 · Session pooler가 아닌 주소 · 호스트의 aws-0/aws-1 차이 · 비밀번호 특수문자(@ → %40)")
    st.stop()


def need_check(text: str = "확인 필요") -> str:
    return f'<span class="badge-check">{text}</span>'


def ok_badge(text: str) -> str:
    return f'<span class="badge-ok">{text}</span>'


def llm_status() -> bool:
    ok = claude_client.is_available()
    if not ok:
        st.caption("ℹ️ ANTHROPIC_API_KEY 미설정 — 규칙 기반 모드로 동작합니다(.env 설정 시 AI 작성·채점 활성화).")
    return ok


def pick_company(key: str = "company") -> Company | None:
    s = db()
    companies = s.scalars(select(Company).order_by(Company.id)).all()
    if not companies:
        st.warning("먼저 [기업정보] 페이지에서 기업을 등록하세요.")
        return None
    c = select_obj("기업", companies, lambda c: c.name, key=key, default_id=st.session_state.get("company_id"))
    st.session_state["company_id"] = c.id
    return c


def pick_item(company_id: int, key: str = "item", allow_none: bool = True) -> Item | None:
    s = db()
    items = s.scalars(select(Item).where(Item.company_id == company_id).order_by(Item.priority, Item.id)).all()
    if not items and not allow_none:
        st.info("등록된 아이템이 없습니다. [포트폴리오]에서 추가하세요.")
        return None
    return select_obj("아이템", items, lambda i: f"{i.name} [{i.portfolio_type}]", none_label="(아이템 선택 안 함)" if allow_none else None, key=key)


def highlight_unsourced(text: str) -> str:
    """출처 없는 수치 문장·[확인 필요]를 노란색으로 표시한 HTML."""
    import html
    import re

    from app.writer.planner import MISSING, unsourced_sentences

    out = html.escape(text)
    for sentence in sorted(set(unsourced_sentences(text)), key=len, reverse=True):
        esc = html.escape(sentence)
        out = out.replace(esc, f"<mark>{esc}</mark>")
    out = MISSING.sub(lambda m: f"<mark><b>{m.group(0)}</b></mark>", out)
    return out.replace("\n", "<br>")


def select_obj(label: str, objs: list, fmt, none_label: str | None = None, key: str | None = None, default_id=None):
    """ORM 객체 선택. Streamlit이 이전 실행의 객체를 돌려주지 않도록 id로 고르고 현재 목록에서 찾는다."""
    by_id = {o.id: o for o in objs}
    ids = ([None] if none_label is not None else []) + list(by_id)
    index = ids.index(default_id) if default_id in ids else 0
    chosen = st.selectbox(
        label, ids, index=index, key=key,
        format_func=lambda i: none_label if i is None else fmt(by_id[i]),
    )
    return by_id.get(chosen)

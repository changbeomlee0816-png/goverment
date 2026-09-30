"""신청 관리 보조: 마감 D-day 알림, 서류 유효기간 알림, 제출서류 체크리스트·발급처 안내."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db.models import Announcement, Application, Document

APPLICATION_STATUSES = ["검토", "작성중", "내부검토", "제출", "발표대기", "선정", "탈락"]

# 서류명 → 발급처 안내
ISSUERS = {
    "사업자등록증": "국세청 홈택스(hometax.go.kr) > 민원증명",
    "표준재무제표증명": "국세청 홈택스 > 민원증명 > 표준재무제표증명",
    "재무제표": "국세청 홈택스 > 표준재무제표증명 또는 외부감사 보고서",
    "국세납세증명서": "국세청 홈택스 또는 정부24(gov.kr)",
    "지방세납세증명서": "위택스(wetax.go.kr) 또는 정부24",
    "4대보험 가입자명부": "4대사회보험 정보연계센터(4insure.or.kr)",
    "중소기업확인서": "중소기업현황정보시스템(sminfo.mss.go.kr)",
    "벤처기업확인서": "벤처확인종합관리시스템(smes.go.kr/venturein)",
    "기업부설연구소 인정서": "한국산업기술진흥협회 RND 전자신청(rnd.or.kr)",
    "연구개발전담부서 인정서": "한국산업기술진흥협회 RND 전자신청(rnd.or.kr)",
    "이노비즈 확인서": "이노비즈넷(innobiz.net)",
    "메인비즈 확인서": "메인비즈넷(mainbiz.or.kr)",
    "법인등기부등본": "대법원 인터넷등기소(iros.go.kr)",
    "주주명부": "자체 작성(법인 인감 날인)",
    "여성기업확인서": "여성기업종합정보포털(wbiz.or.kr)",
    "특허등록원부": "특허로(patent.go.kr)",
}
DOC_PATTERNS = {name: re.compile(re.sub(r"\s+", r"\\s*", name)) for name in ISSUERS}


@dataclass
class Alert:
    kind: str  # 마감/서류
    title: str
    due: date
    days_left: int


def deadline_alerts(session: Session, today: date | None = None) -> list[Alert]:
    today = today or date.today()
    marks = sorted(load_settings()["alerts"].get("deadline_days", [14, 7, 3]), reverse=True)
    max_mark = marks[0] if marks else 14
    out = []
    apps = session.scalars(select(Application).where(Application.status.in_(["검토", "작성중", "내부검토"]))).all()
    for app in apps:
        due = app.due_date or (app.announcement.apply_end if app.announcement else None)
        if not due:
            continue
        left = (due - today).days
        if 0 <= left <= max_mark:
            out.append(Alert("마감", app.title or (app.announcement.title if app.announcement else "신청건"), due, left))
    return sorted(out, key=lambda a: a.days_left)


def document_alerts(session: Session, today: date | None = None) -> list[Alert]:
    today = today or date.today()
    window = int(load_settings()["alerts"].get("document_expiry_days", 30))
    out = []
    for doc in session.scalars(select(Document).where(Document.expires_date.is_not(None))).all():
        left = (doc.expires_date - today).days
        if left <= window:
            out.append(Alert("서류", doc.doc_type, doc.expires_date, left))
    return sorted(out, key=lambda a: a.days_left)


def required_documents(ann: Announcement) -> list[str]:
    meta = (ann.raw_json or {}).get("_llm_meta") or {}
    docs = list(meta.get("required_documents") or [])
    text = " ".join(filter(None, [ann.full_text, ann.summary, ann.eligibility_text]))
    for name, pattern in DOC_PATTERNS.items():
        if pattern.search(text) and name not in docs:
            docs.append(name)
    return docs


def build_checklist(session: Session, app: Application) -> list[dict]:
    """공고 필수서류 × 서류 보관함 자동 매칭."""
    if not app.announcement:
        return app.checklist or []
    existing = {c["doc_type"]: c for c in app.checklist or []}
    vault = session.scalars(select(Document).where(Document.company_id == app.company_id)).all() if app.company_id else []
    today = date.today()
    out = []
    for name in required_documents(app.announcement):
        held = next((d for d in vault if d.doc_type in name or name in d.doc_type), None)
        valid = held is not None and (held.expires_date is None or held.expires_date >= today)
        out.append(
            {
                "doc_type": name,
                "done": existing.get(name, {}).get("done", False) or valid,
                "in_vault": held is not None,
                "vault_valid": valid,
                "issuer": next((v for k, v in ISSUERS.items() if k in name or name in k), "공고문 확인"),
            }
        )
    return out

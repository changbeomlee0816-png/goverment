"""수집기 공통: 스냅샷 저장, 날짜 파싱, 기관 구분, 중복 제거, DB 반영.

원칙(CLAUDE.md 3): 공공 API는 이 스크립트에서만 호출하고, 원본을 data/snapshots/YYYYMMDD/에 저장한 뒤
UI는 DB/스냅샷만 읽는다. API 키는 URL 로그에 남기지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SNAPSHOT_DIR
from app.db.models import Announcement

SIDO = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]
SIDO_FULL = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
    "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
    "경기도": "경기", "강원도": "강원", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남",
    "전라북도": "전북", "전북특별자치도": "전북", "전라남도": "전남", "경상북도": "경북",
    "경상남도": "경남", "제주특별자치도": "제주",
}
REGIONAL_ORG = re.compile(r"(테크노파크|진흥원|경제진흥|창조경제혁신센터|산업진흥|지원센터|재단)")
LOCAL_GOV = re.compile(
    r"(특별시|광역시|특별자치시|특별자치도|도청|시청|군청|구청|^[가-힣]{1,4}(시|군|구)$|^("
    + "|".join(SIDO + list(SIDO_FULL))
    + r")$)"
)
RND_PATTERN = re.compile(r"(R&D|R＆D|연구개발|기술개발|기술혁신|TRL)", re.I)

CATEGORY_KEYWORDS = [
    ("R&D", ["R&D", "연구개발", "기술개발", "기술혁신"]),
    ("시제품", ["시제품", "제품화", "시작품"]),
    ("인증", ["인증", "특허", "지식재산", "IP"]),
    ("판로", ["판로", "수출", "해외", "마케팅", "전시", "박람회"]),
    ("시험분석", ["시험", "분석", "검사", "테스트베드"]),
    ("멘토링", ["멘토링", "컨설팅", "코칭", "교육", "액셀러레이팅"]),
    ("자금", ["융자", "보증", "자금", "투자", "대출"]),
]


@dataclass
class AnnouncementData:
    source: str
    source_id: str | None
    title: str
    agency: str | None = None
    exec_agency: str | None = None
    apply_start: date | None = None
    apply_end: date | None = None
    budget_text: str | None = None
    eligibility_text: str | None = None
    summary: str | None = None
    region: str | None = None
    hashtags: str | None = None
    url: str | None = None
    category_hint: str | None = None
    raw: dict = field(default_factory=dict)


def snapshot_path(source: str, when: datetime | None = None) -> Path:
    when = when or datetime.now()
    folder = SNAPSHOT_DIR / when.strftime("%Y%m%d")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{source}_{when.strftime('%H%M%S')}.json"


def save_snapshot(source: str, payload, when: datetime | None = None) -> Path:
    path = snapshot_path(source, when)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    digits = re.sub(r"\D", "", str(value))
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def parse_period(text: str | None) -> tuple[date | None, date | None]:
    """'20260101 ~ 20260131', '2026-01-01~2026-01-31', '2026.01.01 ~ 2026.01.31' 등."""
    if not text:
        return None, None
    text = str(text)
    full = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
    dates, last_end = [], 0
    for m in full.finditer(text):
        try:
            dates.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
            last_end = m.end()
        except ValueError:
            continue
    if len(dates) == 1:
        # '2026년 4월 1일 ~ 4월 15일'처럼 종료일에 연도가 없는 경우
        rest = text[last_end:]
        m = re.search(r"[~∼\-]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", rest)
        if m:
            try:
                return dates[0], date(dates[0].year, int(m.group(1)), int(m.group(2)))
            except ValueError:
                pass
        return None, dates[0]
    if not dates:
        m = re.search(r"(\d{8})\D+(\d{8})", text) or re.search(r"(\d{8})", text)
        if not m:
            return None, None
        parsed = [parse_date(g) for g in m.groups()]
        return (parsed[0], parsed[1]) if len(parsed) == 2 else (None, parsed[0])
    return dates[0], dates[1]


def classify_level(agency: str | None, exec_agency: str | None = None) -> str:
    """부처(중앙정부) / 지자체 / 지역기관."""
    names = [n.strip() for n in (agency, exec_agency) if n and n.strip()]
    for name in names:
        if LOCAL_GOV.search(name):
            return "지자체"
    for name in names:
        if REGIONAL_ORG.search(name) and any(s in name for s in SIDO + list(SIDO_FULL)):
            return "지역기관"
    return "부처"


def normalize_region(text: str | None) -> str | None:
    if not text:
        return None
    found = []
    for full, short in SIDO_FULL.items():
        if full in text and short not in found:
            found.append(short)
    for short in SIDO:
        if short in text and short not in found:
            found.append(short)
    if "전국" in text:
        return "전국"
    return ",".join(found) or None


def guess_category(*texts: str | None) -> str:
    joined = " ".join(t for t in texts if t)
    for category, words in CATEGORY_KEYWORDS:
        if any(w.lower() in joined.lower() for w in words):
            return category
    return "기타"


def parse_amount_krw(text: str | None) -> int | None:
    """'최대 2억원', '5,000만원', '3억 5천만원' → 원. 가장 큰 값을 과제당 지원금으로 본다."""
    if not text:
        return None
    best = None
    for m in re.finditer(r"(\d[\d,\.]*)\s*억\s*(?:(\d[\d,]*)\s*천)?\s*(?:(\d[\d,]*)\s*만)?\s*원?", text):
        value = float(m.group(1).replace(",", "")) * 1e8
        if m.group(2):
            value += float(m.group(2).replace(",", "")) * 1e7
        if m.group(3):
            value += float(m.group(3).replace(",", "")) * 1e4
        best = max(best or 0, int(value))
    for m in re.finditer(r"(\d[\d,\.]*)\s*천\s*만\s*원", text):
        best = max(best or 0, int(float(m.group(1).replace(",", "")) * 1e7))
    for m in re.finditer(r"(?<![억\d])(\d[\d,\.]*)\s*만\s*원", text):
        best = max(best or 0, int(float(m.group(1).replace(",", "")) * 1e4))
    return best


def dedup_key(title: str, agency: str | None, start: date | None, end: date | None) -> str:
    """제목+기관+접수기간 기준 중복 제거 키."""
    norm_title = re.sub(r"[\s\[\]\(\)「」『』<>·ㆍ,.\-_]", "", title or "").lower()
    base = f"{norm_title}|{(agency or '').strip()}|{start or ''}|{end or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def upsert_announcements(session: Session, items: list[AnnouncementData]) -> tuple[int, int]:
    """(신규, 갱신) 건수 반환."""
    created = updated = 0
    for data in items:
        key = dedup_key(data.title, data.agency, data.apply_start, data.apply_end)
        existing = session.scalar(select(Announcement).where(Announcement.dedup_key == key))
        category = data.category_hint or guess_category(data.title, data.summary)
        is_rnd = bool(RND_PATTERN.search(" ".join(filter(None, [data.title, data.category_hint, data.summary]))))
        if is_rnd:
            category = "R&D"
        fields = dict(
            source=data.source,
            source_id=data.source_id,
            title=data.title.strip(),
            agency=data.agency,
            exec_agency=data.exec_agency,
            level=classify_level(data.agency, data.exec_agency),
            category=category,
            is_rnd=is_rnd,
            apply_start=data.apply_start,
            apply_end=data.apply_end,
            budget_text=data.budget_text,
            support_amount_krw=parse_amount_krw(" ".join(filter(None, [data.budget_text, data.summary]))),
            eligibility_text=data.eligibility_text,
            summary=data.summary,
            region=normalize_region(" ".join(filter(None, [data.region, data.hashtags]))) or data.region,
            hashtags=data.hashtags,
            url=data.url,
            raw_json=data.raw,
            collected_at=datetime.now(),
        )
        if existing:
            for k, v in fields.items():
                if v is not None:
                    setattr(existing, k, v)
            updated += 1
        else:
            session.add(Announcement(dedup_key=key, **fields))
            created += 1
        session.flush()
    return created, updated


def pick(record: dict, *keys, default=None):
    """API 응답 필드명이 바뀌어도 동작하도록 후보 키 중 첫 값을 고른다."""
    for key in keys:
        value = record.get(key)
        if value not in (None, "", []):
            return value
    return default


def strip_html(text: str | None) -> str | None:
    if not text:
        return text
    text = re.sub(r"<br\s*/?>", "\n", str(text), flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return re.sub(r"[ \t]+", " ", text).strip()

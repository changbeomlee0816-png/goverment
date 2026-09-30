"""공고문 수동 업로드(PDF/HWP/HWPX/DOCX) → 텍스트 추출 → 공고 등록.

연초 자료(예산기금운용계획 사업설명자료, 부처 합동설명회)에서 '연간 후보 리스트'를 뽑는 필터도 제공한다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import AnnouncementData, dedup_key, parse_period, upsert_announcements
from app.config import UPLOAD_DIR
from app.db.models import Announcement
from app.docs.extract import extract_text


def save_upload(filename: str, data: bytes, subdir: str = "announcements") -> Path:
    folder = UPLOAD_DIR / subdir / datetime.now().strftime("%Y%m%d")
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w가-힣.\-]", "_", Path(filename).name)
    path = folder / f"{datetime.now().strftime('%H%M%S')}_{safe}"
    path.write_bytes(data)
    return path


def guess_fields(text: str) -> dict:
    """공고문 텍스트에서 제목·기관·접수기간·지원규모 문장을 규칙으로 찾는다(근거 문장 포함)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = next((l for l in lines[:15] if "공고" in l and len(l) < 120), lines[0] if lines else "제목 확인 필요")
    agency = None
    for l in lines[:40] + lines[-20:]:
        m = re.search(r"([가-힣A-Za-z()]+(부|청|처|위원회|진흥원|테크노파크|재단|센터|시|도))\s*(장|공고)?\s*$", l)
        if m and len(l) < 40:
            agency = m.group(1)
            break
    period_line = next(
        (l for l in lines if re.search(r"(접수|신청)\s*(기간|기한|일정)", l) and re.search(r"\d{4}", l)), None
    )
    start, end = parse_period(period_line)
    budget_line = next((l for l in lines if re.search(r"(지원\s*(규모|금액|한도|내용)|정부출연금|최대\s*\d)", l) and re.search(r"(억|만)\s*원", l)), None)
    target_lines = [l for l in lines if re.search(r"(신청\s*자격|지원\s*대상|참여\s*자격|신청\s*대상)", l)]
    target_idx = lines.index(target_lines[0]) if target_lines else None
    eligibility = "\n".join(lines[target_idx : target_idx + 8]) if target_idx is not None else None
    return {
        "title": title,
        "agency": agency,
        "apply_start": start,
        "apply_end": end,
        "period_evidence": period_line,
        "budget_text": budget_line,
        "eligibility_text": eligibility,
    }


def register_announcement(session: Session, filename: str, data: bytes, overrides: dict | None = None) -> Announcement:
    path = save_upload(filename, data)
    text = extract_text(path, data)
    fields = guess_fields(text)
    fields.update({k: v for k, v in (overrides or {}).items() if v})
    ann_data = AnnouncementData(
        source="manual",
        source_id=path.name,
        title=fields["title"],
        agency=fields.get("agency"),
        apply_start=fields.get("apply_start"),
        apply_end=fields.get("apply_end"),
        budget_text=fields.get("budget_text"),
        eligibility_text=fields.get("eligibility_text"),
        summary=text[:1500],
        url=fields.get("url"),
        raw={"period_evidence": fields.get("period_evidence"), "file": str(path)},
    )
    upsert_announcements(session, [ann_data])
    ann = session.scalar(
        select(Announcement).where(
            Announcement.dedup_key == dedup_key(ann_data.title, ann_data.agency, ann_data.apply_start, ann_data.apply_end)
        )
    )
    ann.file_path = str(path)
    ann.full_text = text
    session.flush()
    return ann


ANNUAL_NEW = re.compile(r"(신규|단상|단하|신설)")
MONTH = re.compile(r"(\d{1,2})\s*월")


def annual_candidates(text: str, keywords: list[str], min_month: int = 3) -> list[dict]:
    """예산기금운용계획·합동설명회 자료에서 연간 후보 사업을 거른다.

    조건: (신규/단상/단하 표기) 또는 (min_month월 이후 공고 예정) + 수혜자 키워드 1개 이상.
    각 후보는 근거 문장(원문 줄)과 함께 반환한다.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out = []
    for i, line in enumerate(lines):
        window = " ".join(lines[i : i + 3])
        hit_keywords = [k for k in keywords if k and k in window]
        if keywords and not hit_keywords:
            continue
        is_new = bool(ANNUAL_NEW.search(line))
        months = [int(m) for m in MONTH.findall(window) if 1 <= int(m) <= 12]
        late = any(m >= min_month for m in months)
        if not (is_new or late):
            continue
        if "사업" not in window and "과제" not in window:
            continue
        out.append(
            {
                "근거문장": line,
                "신규·단상·단하": "예" if is_new else "",
                "예정월": ",".join(map(str, sorted(set(months)))) or "확인 필요",
                "키워드": ",".join(hit_keywords),
            }
        )
    seen, unique = set(), []
    for row in out:
        if row["근거문장"] not in seen:
            seen.add(row["근거문장"])
            unique.append(row)
    return unique

"""매칭 실행 + 보고서.

출력 규칙(CLAUDE.md 5): ①부처(중앙정부) / ②지자체·지역기관 분리, R&D/비R&D 태그, 마지막에 요약표, 하단 고지.
3단계 LLM 설명은 상위 N건에만, 점수표를 입력으로 1~2줄 이유만 생성(점수 변경 금지).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db.models import Announcement, Company, Item, MatchResult
from app.llm import claude_client
from app.matching.profiles import announcement_profile, company_profile, item_profile
from app.matching.rules import hard_filter
from app.matching.scoring import score

DISCLAIMER = "※ 본 결과는 참고용입니다. 최종 자격 확인은 공고 원문과 주관기관 기준을 따르십시오."


@dataclass
class MatchRow:
    match_id: int
    announcement: Announcement
    eligible: bool
    score_total: float
    score_detail: dict
    fail_reasons: list
    warnings: list
    reason: str | None


def fallback_reason(detail: dict) -> str:
    """LLM 미사용 시 점수표에서 규칙으로 만든 이유."""
    ranked = sorted(detail.items(), key=lambda kv: kv[1]["score"])
    best, worst = ranked[-1][1], ranked[0][1]
    return f"강점: {best['label']}({best['note']}). 보완: {worst['label']}({worst['note']})."


def run_matching(
    session: Session,
    company_id: int,
    item_id: int | None = None,
    today: date | None = None,
    use_llm: bool = True,
    include_closed: bool = False,
) -> list[MatchRow]:
    today = today or date.today()
    settings = load_settings()["matching"]
    company = session.get(Company, company_id)
    item = session.get(Item, item_id) if item_id else None
    cp, ip = company_profile(company), item_profile(item)

    session.execute(
        delete(MatchResult).where(MatchResult.company_id == company_id, MatchResult.item_id.is_(item_id) if item_id is None else MatchResult.item_id == item_id)
    )
    anns = session.scalars(select(Announcement)).all()
    rows: list[MatchRow] = []
    for ann in anns:
        ap = announcement_profile(ann)
        rr = hard_filter(cp, ap, today)
        if not include_closed and any(r.startswith("접수 마감") for r in rr.fail_reasons):
            continue
        sr = score(cp, ip, ap, settings.get("weights"))
        m = MatchResult(
            company_id=company_id,
            item_id=item_id,
            announcement_id=ann.id,
            eligible=rr.eligible,
            fail_reasons=rr.fail_reasons,
            score_total=sr.total if rr.eligible else 0.0,
            score_detail={**sr.detail, "_warnings": rr.warnings},
        )
        session.add(m)
        session.flush()
        rows.append(MatchRow(m.id, ann, rr.eligible, m.score_total, sr.detail, rr.fail_reasons, rr.warnings, None))

    rows.sort(key=lambda r: (not r.eligible, -r.score_total))
    top = [r for r in rows if r.eligible][: int(settings.get("llm_reason_top_n", 10))]
    reasons: dict[int, str] = {}
    if use_llm and top and claude_client.is_available():
        table = [
            {
                "announcement_id": r.announcement.id,
                "사업명": r.announcement.title,
                "총점": r.score_total,
                "차원별": {v["label"]: {"점수(0~1)": v["score"], "설명": v["note"]} for v in r.score_detail.values()},
            }
            for r in top
        ]
        try:
            data = claude_client.ClaudeClient(effort="low").complete_json(
                "match_reason", json.dumps(table, ensure_ascii=False), max_tokens=4000
            )
            reasons = {int(x["announcement_id"]): x["reason"] for x in data.get("reasons", [])}
        except Exception:  # noqa: BLE001 - 설명 실패 시 규칙 이유로 대체
            reasons = {}
    for r in rows:
        if r.eligible:
            r.reason = reasons.get(r.announcement.id) or fallback_reason(r.score_detail)
        else:
            r.reason = "자격 불충족: " + "; ".join(r.fail_reasons)
        m = session.get(MatchResult, r.match_id)
        m.reason_summary = r.reason
    session.flush()
    return rows


def _period(a: Announcement) -> str:
    if not a.apply_start and not a.apply_end:
        return "확인 필요"
    return f"{a.apply_start or '?'} ~ {a.apply_end or '?'}"


def _scale(a: Announcement) -> str:
    if a.support_amount_krw:
        return f"최대 {a.support_amount_krw / 1e8:.2f}억원".replace(".00억", "억")
    return (a.budget_text or "확인 필요")[:60]


def to_dataframe(rows: list[MatchRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "구분": "①부처" if r.announcement.level == "부처" else "②지자체·지역기관",
                "유형": "R&D" if r.announcement.is_rnd else "비R&D",
                "사업명": r.announcement.title,
                "기관": r.announcement.agency or r.announcement.exec_agency or "확인 필요",
                "접수기간": _period(r.announcement),
                "지원규모": _scale(r.announcement),
                "자격": "충족" if r.eligible else "불충족",
                "점수": r.score_total,
                "이유": r.reason,
                "확인 필요": "; ".join(r.warnings),
                "원문링크": r.announcement.url or r.announcement.file_path or "",
            }
            for r in rows
        ]
    )


def to_markdown(rows: list[MatchRow], company_name: str, item_name: str | None = None) -> str:
    lines = [f"# 지원사업 매칭 보고서 — {company_name}" + (f" / {item_name}" if item_name else ""), ""]
    eligible = [r for r in rows if r.eligible]
    for header, level_filter in (("① 부처(중앙정부)", lambda a: a.level == "부처"), ("② 지자체·지역기관", lambda a: a.level != "부처")):
        lines.append(f"## {header}")
        group = [r for r in eligible if level_filter(r.announcement)]
        if not group:
            lines.append("- 해당 없음")
        for r in group:
            a = r.announcement
            tag = "R&D" if a.is_rnd else "비R&D"
            lines.append(f"### [{tag}] {a.title}")
            lines.append(f"- 접수기간: {_period(a)}")
            lines.append(f"- 지원규모: {_scale(a)}")
            lines.append(f"- 점수: {r.score_total}점")
            lines.append(f"- 이유: {r.reason}")
            if r.warnings:
                lines.append(f"- 확인 필요: {'; '.join(r.warnings)}")
            lines.append(f"- 원문: {a.url or a.file_path or '확인 필요'}")
            lines.append("")
        lines.append("")
    lines.append("## 요약표")
    lines.append("| 구분 | 유형 | 사업명 | 접수마감 | 점수 |")
    lines.append("|---|---|---|---|---|")
    for r in eligible:
        a = r.announcement
        lines.append(
            f"| {'부처' if a.level == '부처' else '지자체·지역'} | {'R&D' if a.is_rnd else '비R&D'} | {a.title} | {a.apply_end or '확인 필요'} | {r.score_total} |"
        )
    lines += ["", DISCLAIMER]
    return "\n".join(lines)

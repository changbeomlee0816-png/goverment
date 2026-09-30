"""공고 원문 → 자격요건(EligibilityRule) 추출.

LLM(extract_eligibility.md)이 근거 문장과 함께 추출하고, 사람이 UI에서 '확인'(verified) 체크한다.
LLM을 쓸 수 없으면 규칙 기반으로 업력·지역·매출·인원만 추출한다(근거 문장 포함).
"""
from __future__ import annotations

import json
import re

from sqlalchemy.orm import Session

from app.collectors.base import normalize_region, parse_amount_krw
from app.db.models import Announcement, EligibilityRule
from app.llm import claude_client

ALLOWED_FIELDS = {
    "years_in_business", "region_sido", "revenue_krw", "employees", "industry",
    "certification", "has_rnd_lab", "ceo_attribute", "trl", "other",
}


def announcement_text(ann: Announcement) -> str:
    parts = [
        f"공고명: {ann.title}",
        f"소관기관: {ann.agency or ''} / 수행기관: {ann.exec_agency or ''}",
        f"접수기간: {ann.apply_start or '?'} ~ {ann.apply_end or '?'}",
        f"지원대상: {ann.eligibility_text or ''}",
        f"지원내용: {ann.budget_text or ''}",
        f"사업개요: {ann.summary or ''}",
    ]
    if ann.full_text:
        parts.append("공고 원문:\n" + ann.full_text)
    return "\n".join(parts)


def rule_based_extract(text: str) -> list[dict]:
    rules: list[dict] = []
    lines = [l.strip() for l in re.split(r"[\n。]", text) if l.strip()]
    for line in lines:
        m = re.search(r"(업력|창업)\s*(\d+)\s*년\s*(이내|미만|이하)", line)
        if m:
            rules.append({"field": "years_in_business", "operator": "<=", "value": int(m.group(2)), "evidence_text": line})
        m = re.search(r"(업력|창업)\s*(\d+)\s*년\s*(이상|초과)", line)
        if m:
            rules.append({"field": "years_in_business", "operator": ">=", "value": int(m.group(2)), "evidence_text": line})
        if re.search(r"(소재|본사|사업장).{0,15}(기업|중소기업|두고)", line):
            region = normalize_region(line)
            if region and region != "전국":
                rules.append({"field": "region_sido", "operator": "in", "value": region.split(","), "evidence_text": line})
        m = re.search(r"매출(액)?\s*[^\n]{0,10}?(\d[\d,\.]*\s*(억|천만|만)\s*원?)\s*(이하|미만|이내)", line)
        if m:
            amount = parse_amount_krw(m.group(2) + ("원" if "원" not in m.group(2) else ""))
            if amount:
                rules.append({"field": "revenue_krw", "operator": "<=", "value": amount, "evidence_text": line})
        m = re.search(r"(상시\s*근로자|종업원|직원)\s*(수)?\s*(\d+)\s*(명|인)\s*(이상)", line)
        if m:
            rules.append({"field": "employees", "operator": ">=", "value": int(m.group(3)), "evidence_text": line})
        m = re.search(r"(상시\s*근로자|종업원|직원)\s*(수)?\s*(\d+)\s*(명|인)\s*(미만|이하)", line)
        if m:
            rules.append({"field": "employees", "operator": "<=", "value": int(m.group(3)), "evidence_text": line})
        if re.search(r"(기업부설연구소|연구개발전담부서).{0,10}(보유|설립|인정)", line) and re.search(r"(필수|기업|보유한)", line):
            rules.append({"field": "has_rnd_lab", "operator": "==", "value": True, "evidence_text": line})
        certs = [c for c in ("벤처", "이노비즈", "메인비즈") if c in line]
        if certs and re.search(r"(인증|확인).{0,10}(기업|필수|보유)", line) and "우대" not in line and "가점" not in line:
            rules.append({"field": "certification", "operator": "has_any", "value": certs, "evidence_text": line})
    # 같은 field/operator 중복 제거
    seen, unique = set(), []
    for r in rules:
        key = (r["field"], r["operator"], json.dumps(r["value"], ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def extract_for_announcement(session: Session, ann: Announcement, use_llm: bool = True) -> dict:
    """자격요건을 추출해 저장. 기존 미확인 규칙은 교체, 사람이 확인한 규칙은 유지."""
    text = announcement_text(ann)
    meta: dict = {}
    if use_llm and claude_client.is_available():
        client = claude_client.ClaudeClient()
        data = client.complete_json(
            "extract_eligibility", "위 공고의 자격요건과 사업 개요를 추출해 주세요.", reference=text, max_tokens=8000
        )
        rules = [r for r in data.get("rules", []) if r.get("field") in ALLOWED_FIELDS]
        meta = {k: data.get(k) for k in ("category", "is_rnd", "support_amount_krw", "dev_period_months", "purpose_keywords", "required_documents", "evidence")}
        method = "llm"
    else:
        rules = rule_based_extract(text)
        method = "rule"

    for old in list(ann.rules):
        if not old.verified:
            session.delete(old)
    session.flush()
    for r in rules:
        value = r.get("value")
        session.add(
            EligibilityRule(
                announcement_id=ann.id,
                field=r["field"],
                operator=r.get("operator", "note"),
                value=json.dumps(value, ensure_ascii=False) if value is not None else None,
                evidence_text=r.get("evidence_text"),
                verified=False,
            )
        )
    if meta:
        if meta.get("category"):
            ann.category = meta["category"]
        if meta.get("is_rnd") is not None:
            ann.is_rnd = bool(meta["is_rnd"])
        if meta.get("support_amount_krw"):
            ann.support_amount_krw = int(meta["support_amount_krw"])
        raw = dict(ann.raw_json or {})
        raw["_llm_meta"] = meta
        ann.raw_json = raw
    session.flush()
    return {"method": method, "count": len(rules)}

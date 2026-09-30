"""1단계 하드필터: 업력·소재지·매출·인원·업종·필수 인증·접수 마감 여부.

LLM은 사용하지 않는다(CLAUDE.md 규칙 1). 불충족 시 사유를, 판단 불가 시 '확인 필요'를 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.matching.profiles import AnnouncementProfile, CompanyProfile, Rule


@dataclass
class RuleResult:
    eligible: bool
    fail_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # 확인 필요

    def as_dict(self) -> dict:
        return {"eligible": self.eligible, "fail_reasons": self.fail_reasons, "warnings": self.warnings}


def _compare(actual: float, operator: str, value) -> bool | None:
    try:
        if operator == "<=":
            return actual <= float(value)
        if operator == "<":
            return actual < float(value)
        if operator == ">=":
            return actual >= float(value)
        if operator == ">":
            return actual > float(value)
        if operator == "==":
            return actual == float(value)
        if operator == "between":
            lo, hi = value
            return (lo is None or actual >= float(lo)) and (hi is None or actual <= float(hi))
    except (TypeError, ValueError):
        return None
    return None


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


def _label(rule: Rule) -> str:
    tag = "" if rule.verified else " [미확인 규칙]"
    ev = f' (근거: "{rule.evidence_text}")' if rule.evidence_text else ""
    return f"{tag}{ev}"


def check_rule(company: CompanyProfile, rule: Rule, today: date) -> tuple[bool | None, str]:
    """(통과 여부 or None=판단불가, 설명)"""
    f, op, v = rule.field, rule.operator, rule.value
    if f == "years_in_business":
        years = company.years_in_business(today)
        if years is None:
            return None, "설립일 미입력으로 업력 확인 필요"
        ok = _compare(years, op, v)
        return ok, f"업력 {years:.1f}년 / 요건 {op} {v}년"
    if f == "region_sido":
        allowed = _as_list(v)
        if not company.region_sido:
            return None, "소재지 미입력으로 지역 요건 확인 필요"
        ok = company.region_sido in allowed if op == "in" else company.region_sido not in allowed
        return ok, f"소재지 {company.region_sido} / 요건 {','.join(allowed)}"
    if f == "revenue_krw":
        if company.revenue_last_year is None:
            return None, "매출 미입력으로 확인 필요"
        return _compare(company.revenue_last_year, op, v), f"전년 매출 {company.revenue_last_year:,}원 / 요건 {op} {v}"
    if f == "employees":
        if company.employees is None:
            return None, "상시근로자 수 미입력으로 확인 필요"
        return _compare(company.employees, op, v), f"상시근로자 {company.employees}명 / 요건 {op} {v}"
    if f == "industry":
        words = _as_list(v)
        name = " ".join(filter(None, [company.industry_name, company.industry_code]))
        if not name:
            return None, "업종 미입력으로 확인 필요"
        hit = any(w in name for w in words)
        return (hit if op == "in" else not hit), f"업종 {name} / 요건 {op} {','.join(words)}"
    if f == "certification":
        need = _as_list(v)
        have = set(company.certifications)
        ok = all(n in have for n in need) if op == "has_all" else any(n in have for n in need)
        return ok, f"보유 인증 {','.join(have) or '없음'} / 요건 {','.join(need)}"
    if f == "has_rnd_lab":
        want = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "예", "y")
        return company.has_rnd_lab == want, f"기업부설연구소 {'보유' if company.has_rnd_lab else '미보유'}"
    if f == "ceo_attribute":
        need = _as_list(v)
        ok = any(n in company.ceo_attributes for n in need)
        return ok, f"대표자 요건 {','.join(need)}"
    # trl은 점수화에서, other는 사람이 확인
    return None, f"요건 확인 필요: {rule.evidence_text or v}"


def hard_filter(company: CompanyProfile, ann: AnnouncementProfile, today: date | None = None) -> RuleResult:
    today = today or date.today()
    result = RuleResult(eligible=True)

    if ann.apply_end and ann.apply_end < today:
        result.eligible = False
        result.fail_reasons.append(f"접수 마감 ({ann.apply_end})")
    elif ann.apply_end is None:
        result.warnings.append("접수 마감일 확인 필요")
    if ann.recruiting == "N":
        result.eligible = False
        result.fail_reasons.append("모집 종료(모집진행여부 N)")

    # 지자체·지역기관 공고의 지역 필드 (규칙이 따로 없을 때)
    has_region_rule = any(r.field == "region_sido" for r in ann.rules)
    if not has_region_rule and ann.level in ("지자체", "지역기관") and ann.region and ann.region != "전국":
        allowed = _as_list(ann.region)
        if company.region_sido and company.region_sido not in allowed:
            result.eligible = False
            result.fail_reasons.append(f"지역 불일치: 소재지 {company.region_sido} / 공고 지역 {ann.region} (근거: 공고 지역 필드)")
        elif not company.region_sido:
            result.warnings.append("소재지 미입력으로 지역 요건 확인 필요")

    for rule in ann.rules:
        if rule.field in ("trl", "other"):
            if rule.field == "other":
                result.warnings.append(f"요건 확인 필요: {rule.evidence_text or rule.value}")
            continue
        ok, desc = check_rule(company, rule, today)
        if ok is None:
            result.warnings.append(desc + _label(rule))
        elif not ok:
            result.eligible = False
            result.fail_reasons.append(desc + _label(rule))
    return result

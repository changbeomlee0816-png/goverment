"""매칭 입력용 순수 데이터 구조. ORM과 분리해 규칙·점수 코드를 단위 테스트할 수 있게 한다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from app.db.models import Announcement, Company, Item


@dataclass
class CompanyProfile:
    name: str
    founded_date: date | None = None
    region_sido: str | None = None
    industry_name: str | None = None
    industry_code: str | None = None
    revenue_last_year: int | None = None
    employees: int | None = None
    rnd_staff: int | None = None
    has_rnd_lab: bool = False
    certifications: list[str] = field(default_factory=list)
    ceo_attributes: list[str] = field(default_factory=list)
    patents: int = 0
    national_rnd_count: int = 0  # 선행 국가R&D 수행 건수

    def years_in_business(self, today: date) -> float | None:
        if not self.founded_date:
            return None
        return (today - self.founded_date).days / 365.25


@dataclass
class ItemProfile:
    name: str
    keywords: list[str] = field(default_factory=list)
    summary: str = ""
    issue: str = ""
    trl_current: int | None = None
    trl_target: int | None = None
    dev_period_months: int | None = None
    budget_krw: int | None = None
    preferred_type: str = "R&D"


@dataclass
class Rule:
    field: str
    operator: str
    value: object
    evidence_text: str | None = None
    verified: bool = False


@dataclass
class AnnouncementProfile:
    id: int
    title: str
    level: str = "부처"
    is_rnd: bool = False
    category: str | None = None
    apply_start: date | None = None
    apply_end: date | None = None
    region: str | None = None
    support_amount_krw: int | None = None
    dev_period_months: int | None = None
    text: str = ""  # 목적 적합도 계산용(제목+개요+대상)
    purpose_keywords: list[str] = field(default_factory=list)
    recruiting: str | None = None  # 'Y'/'N'
    rules: list[Rule] = field(default_factory=list)


def company_profile(c: Company) -> CompanyProfile:
    return CompanyProfile(
        name=c.name,
        founded_date=c.founded_date,
        region_sido=c.region_sido,
        industry_name=c.industry_name,
        industry_code=c.industry_code,
        revenue_last_year=c.revenue_last_year,
        employees=c.employees,
        rnd_staff=c.rnd_staff,
        has_rnd_lab=bool(c.has_rnd_lab),
        certifications=list(c.certifications or []),
        ceo_attributes=list(c.ceo_attributes or []),
        patents=c.patents or 0,
        national_rnd_count=sum(1 for p in c.prior_research if p.type == "국가R&D"),
    )


def item_profile(i: Item | None) -> ItemProfile | None:
    if i is None:
        return None
    return ItemProfile(
        name=i.name,
        keywords=list(i.keywords or []),
        summary=i.summary or "",
        issue=i.issue or "",
        trl_current=i.trl_current,
        trl_target=i.trl_target,
        dev_period_months=i.dev_period_months,
        budget_krw=i.budget_krw,
        preferred_type=i.preferred_type or "R&D",
    )


def announcement_profile(a: Announcement) -> AnnouncementProfile:
    meta = (a.raw_json or {}).get("_llm_meta") or {}
    rules = []
    for r in a.rules:
        try:
            value = json.loads(r.value) if r.value is not None else None
        except (json.JSONDecodeError, TypeError):
            value = r.value
        rules.append(Rule(r.field, r.operator, value, r.evidence_text, bool(r.verified)))
    return AnnouncementProfile(
        id=a.id,
        title=a.title,
        level=a.level or "부처",
        is_rnd=bool(a.is_rnd),
        category=a.category,
        apply_start=a.apply_start,
        apply_end=a.apply_end,
        region=a.region,
        support_amount_krw=a.support_amount_krw,
        dev_period_months=meta.get("dev_period_months"),
        text=" ".join(filter(None, [a.title, a.summary, a.eligibility_text, a.budget_text, a.hashtags])),
        purpose_keywords=list(meta.get("purpose_keywords") or []),
        recruiting=(a.raw_json or {}).get("_recruiting"),
        rules=rules,
    )

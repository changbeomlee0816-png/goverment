"""데이터 모델 (docs/REQUIREMENTS.md 3장). SQLAlchemy 2.0 ORM."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    """기업정보"""

    __tablename__ = "company"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    biz_no: Mapped[str | None] = mapped_column(String(20))
    founded_date: Mapped[date | None] = mapped_column(Date)
    region_sido: Mapped[str | None] = mapped_column(String(20))
    region_sigungu: Mapped[str | None] = mapped_column(String(40))
    industry_code: Mapped[str | None] = mapped_column(String(20))
    industry_name: Mapped[str | None] = mapped_column(String(100))
    revenue_last_year: Mapped[int | None] = mapped_column(BigInteger)  # 원
    employees: Mapped[int | None] = mapped_column(Integer)
    rnd_staff: Mapped[int | None] = mapped_column(Integer)
    rnd_ratio: Mapped[float | None] = mapped_column(Float)  # 매출 대비 연구개발비 비율(%)
    has_rnd_lab: Mapped[bool] = mapped_column(Boolean, default=False)
    certifications: Mapped[list] = mapped_column(JSON, default=list)  # 벤처/이노비즈/메인비즈/여성기업...
    ceo_attributes: Mapped[list] = mapped_column(JSON, default=list)  # 여성/청년...
    export_amount: Mapped[int | None] = mapped_column(BigInteger)
    patents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    items: Mapped[list["Item"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    prior_research: Mapped[list["PriorResearch"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(back_populates="company", cascade="all, delete-orphan")

    def years_in_business(self, today: date | None = None) -> float | None:
        if not self.founded_date:
            return None
        today = today or date.today()
        return (today - self.founded_date).days / 365.25


class Item(Base):
    """아이템(프로젝트 요약맵)"""

    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    name: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    issue: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    portfolio_type: Mapped[str] = mapped_column(String(20), default="Project")  # Discovery/Project/Asset
    trl_current: Mapped[int | None] = mapped_column(Integer)
    trl_target: Mapped[int | None] = mapped_column(Integer)
    dev_period_months: Mapped[int | None] = mapped_column(Integer)
    budget_krw: Mapped[int | None] = mapped_column(BigInteger)
    staff_count: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    preferred_type: Mapped[str] = mapped_column(String(20), default="R&D")  # R&D/비R&D/바우처

    company: Mapped[Company] = relationship(back_populates="items")
    indicators: Mapped[list["PerformanceIndicator"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class PerformanceIndicator(Base):
    """성능지표"""

    __tablename__ = "performance_indicator"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"))
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(40))
    measure_method: Mapped[str | None] = mapped_column(Text)
    test_org: Mapped[str | None] = mapped_column(String(200))  # 공인시험기관
    baseline: Mapped[str | None] = mapped_column(String(100))
    target: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(Text)

    item: Mapped[Item] = relationship(back_populates="indicators")


class PriorResearch(Base):
    """선행연구·실적"""

    __tablename__ = "prior_research"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    title: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(20), default="자체")  # 국가R&D/자체/수요처
    period: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    relevance: Mapped[str | None] = mapped_column(Text)

    company: Mapped[Company] = relationship(back_populates="prior_research")


class Announcement(Base):
    """공고"""

    __tablename__ = "announcement"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # bizinfo/kstartup/manual/...
    source_id: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500))
    agency: Mapped[str | None] = mapped_column(String(200))  # 소관기관
    exec_agency: Mapped[str | None] = mapped_column(String(200))  # 수행(주관)기관
    level: Mapped[str | None] = mapped_column(String(20))  # 부처/지자체/지역기관
    category: Mapped[str | None] = mapped_column(String(40))  # R&D/시제품/인증/판로/...
    is_rnd: Mapped[bool] = mapped_column(Boolean, default=False)
    apply_start: Mapped[date | None] = mapped_column(Date)
    apply_end: Mapped[date | None] = mapped_column(Date)
    budget_text: Mapped[str | None] = mapped_column(Text)
    support_amount_krw: Mapped[int | None] = mapped_column(BigInteger)  # 과제당 최대 지원금(추출 시)
    eligibility_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(String(100))
    hashtags: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    file_path: Mapped[str | None] = mapped_column(String(1000))
    full_text: Mapped[str | None] = mapped_column(Text)  # 첨부 공고문 추출 텍스트
    dedup_key: Mapped[str | None] = mapped_column(String(64), index=True, unique=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    rules: Mapped[list["EligibilityRule"]] = relationship(
        back_populates="announcement", cascade="all, delete-orphan"
    )


class EligibilityRule(Base):
    """공고에서 추출한 자격요건 (LLM 추출 + 사람이 확인)"""

    __tablename__ = "eligibility_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcement.id"))
    field: Mapped[str] = mapped_column(String(40))
    operator: Mapped[str] = mapped_column(String(20))
    value: Mapped[str | None] = mapped_column(Text)  # JSON 문자열 또는 단일 값
    evidence_text: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    announcement: Mapped[Announcement] = relationship(back_populates="rules")


class MatchResult(Base):
    """매칭 결과"""

    __tablename__ = "match_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcement.id"))
    eligible: Mapped[bool] = mapped_column(Boolean)
    fail_reasons: Mapped[list] = mapped_column(JSON, default=list)
    score_total: Mapped[float] = mapped_column(Float, default=0)
    score_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    reason_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    announcement: Mapped[Announcement] = relationship()
    item: Mapped[Item | None] = relationship()


class Application(Base):
    """신청 관리"""

    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("match_result.id"))
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey("announcement.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("company.id"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("plan_template.id"))
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="검토")
    due_date: Mapped[date | None] = mapped_column(Date)
    owner: Mapped[str | None] = mapped_column(String(100))
    memo: Mapped[str | None] = mapped_column(Text)
    checklist: Mapped[list] = mapped_column(JSON, default=list)  # [{"doc_type":..., "done":bool}]
    dept_review: Mapped[dict] = mapped_column(JSON, default=dict)  # {"개발":bool,"생산":bool,"영업":bool}
    interview: Mapped[list] = mapped_column(JSON, default=list)  # [{"section_key","question","answer"}]
    extras: Mapped[dict] = mapped_column(JSON, default=dict)  # 시장규모·매출예측·역할분담 등 보조도구 결과

    announcement: Mapped[Announcement | None] = relationship()
    template: Mapped["PlanTemplate | None"] = relationship()
    drafts: Mapped[list["PlanDraft"]] = relationship(back_populates="application", cascade="all, delete-orphan")


class Document(Base):
    """서류 보관함"""

    __tablename__ = "document"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id"))
    doc_type: Mapped[str] = mapped_column(String(50))
    file_path: Mapped[str | None] = mapped_column(String(1000))
    file_name: Mapped[str | None] = mapped_column(String(300))
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)  # 외부 DB 배포 시 파일 영구 보관
    issued_date: Mapped[date | None] = mapped_column(Date)
    expires_date: Mapped[date | None] = mapped_column(Date)

    company: Mapped[Company] = relationship(back_populates="documents")


class PlanTemplate(Base):
    """사업계획서 양식·평가표 (연도별 버전 관리).

    sections: [{"key","title","level","instructions":[...],"eval_item","max_score","page_limit"}]
    eval_items: [{"key","name","max_score","criteria"}]
    """

    __tablename__ = "plan_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    year: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[str] = mapped_column(String(40), default="v1")
    announcement_id: Mapped[int | None] = mapped_column(ForeignKey("announcement.id"))
    source_file: Mapped[str | None] = mapped_column(String(1000))
    eval_source_file: Mapped[str | None] = mapped_column(String(1000))
    raw_text: Mapped[str | None] = mapped_column(Text)
    eval_raw_text: Mapped[str | None] = mapped_column(Text)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    eval_items: Mapped[list] = mapped_column(JSON, default=list)
    parsed_by: Mapped[str] = mapped_column(String(20), default="rule")  # rule/llm
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PlanDraft(Base):
    """계획서 초안 (섹션 단위)"""

    __tablename__ = "plan_draft"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("application.id"))
    template_version: Mapped[str | None] = mapped_column(String(80))
    section_key: Mapped[str] = mapped_column(String(80))
    section_title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    eval_item_key: Mapped[str | None] = mapped_column(String(80))
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{"claim","source"}]
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    application: Mapped[Application] = relationship(back_populates="drafts")

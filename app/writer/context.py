"""계획서 작성용 '사실자료(fact sheet)' 구성.

LLM에는 이 사실자료 + 인터뷰 답변 + 보조도구 결과만 제공한다(근거 없는 사실 생성 방지).
"""
from __future__ import annotations

from app.db.models import Application, Company, Item
from app.writer import tools


def company_facts(c: Company) -> str:
    lines = [
        f"- 기업명: {c.name}",
        f"- 설립일: {c.founded_date or '확인 필요'}",
        f"- 소재지: {c.region_sido or ''} {c.region_sigungu or ''}".rstrip(),
        f"- 업종: {c.industry_name or ''} ({c.industry_code or ''})",
        f"- 전년도 매출: {tools.fmt_krw(c.revenue_last_year) if c.revenue_last_year else '확인 필요'}",
        f"- 상시근로자: {c.employees if c.employees is not None else '확인 필요'}명, 연구인력: {c.rnd_staff if c.rnd_staff is not None else '확인 필요'}명",
        f"- 연구개발비 비율: {c.rnd_ratio if c.rnd_ratio is not None else '확인 필요'}%",
        f"- 기업부설연구소: {'보유' if c.has_rnd_lab else '미보유'}",
        f"- 인증: {', '.join(c.certifications or []) or '없음'}",
        f"- 수출액: {tools.fmt_krw(c.export_amount) if c.export_amount else '없음/확인 필요'}",
        f"- 보유 특허: {c.patents or 0}건",
    ]
    if c.prior_research:
        lines.append("- 선행연구·실적:")
        for p in c.prior_research:
            lines.append(
                f"  - [{p.type}] {p.title} ({p.period or '기간 확인 필요'}) 결과: {p.result or '-'} / 지재권: {p.ip or '-'} / 연관성: {p.relevance or '-'}"
            )
    return "\n".join(lines)


def item_facts(i: Item) -> str:
    lines = [
        f"- 아이템명: {i.name}",
        f"- 요약: {i.summary or '확인 필요'}",
        f"- 해결하려는 이슈: {i.issue or '확인 필요'}",
        f"- 키워드: {', '.join(i.keywords or [])}",
        f"- 포트폴리오 구분: {i.portfolio_type}, 선호 유형: {i.preferred_type}",
        f"- 기술성숙도(TRL): 현재 {i.trl_current or '?'} → 목표 {i.trl_target or '?'}",
        f"- 개발기간: {i.dev_period_months or '?'}개월, 예산: {tools.fmt_krw(i.budget_krw) if i.budget_krw else '확인 필요'}, 투입인력: {i.staff_count or '?'}명",
        f"- 개발 범위: {i.scope or '확인 필요'}",
    ]
    if i.indicators:
        lines.append("- 성능지표:")
        lines.append(
            tools.indicator_table(
                [
                    {
                        "name": x.name, "unit": x.unit, "baseline": x.baseline, "target": x.target,
                        "measure_method": x.measure_method, "test_org": x.test_org, "source": x.source,
                    }
                    for x in i.indicators
                ]
            )
        )
    return "\n".join(lines)


def extras_facts(extras: dict) -> str:
    parts = []
    if extras.get("market"):
        m = extras["market"]
        parts.append("### 시장규모(TAM-SAM-SOM)\n" + tools.market_table(tools.MarketSize(**m)))
    if extras.get("forecast"):
        f = extras["forecast"]
        parts.append("### 5개년 매출 계획\n" + tools.revenue_table(tools.revenue_forecast(f["rows"], f["start_year"])))
    if extras.get("roles"):
        parts.append("### 업무분담\n" + tools.role_table(extras["roles"]))
    return "\n\n".join(parts)


def interview_facts(app: Application) -> str:
    answered = [q for q in (app.interview or []) if (q.get("answer") or "").strip()]
    if not answered:
        return ""
    return "\n".join(f"- [{q.get('section_key')}] Q: {q['question']}\n  A: {q['answer']}" for q in answered)


def build_fact_sheet(app: Application, company: Company, item: Item | None) -> str:
    blocks = ["## 기업 정보", company_facts(company)]
    if item:
        blocks += ["## 아이템 정보", item_facts(item)]
    extra = extras_facts(app.extras or {})
    if extra:
        blocks += ["## 보조도구 산출 결과", extra]
    iv = interview_facts(app)
    if iv:
        blocks += ["## 인터뷰 답변(사용자 제공)", iv]
    return "\n".join(blocks)


def build_reference(app: Application) -> str:
    """캐시할 긴 참고자료: 공고문 + 양식 + 평가표."""
    parts = []
    ann = app.announcement
    if ann:
        parts.append(f"## 공고: {ann.title}\n기관: {ann.agency or ''}\n접수: {ann.apply_start} ~ {ann.apply_end}\n지원대상: {ann.eligibility_text or ''}\n지원내용: {ann.budget_text or ''}\n{ann.full_text or ann.summary or ''}")
    t = app.template
    if t:
        parts.append("## 사업계획서 양식 섹션과 작성 지시문")
        for s in t.sections:
            parts.append(f"### [{s['key']}] {s['title']}" + (f" (배점 {s['max_score']}점)" if s.get("max_score") else "") + (f" (분량 {s['page_limit']})" if s.get("page_limit") else ""))
            parts.extend(f"- {ins}" for ins in s.get("instructions", []))
            if s.get("sample"):
                parts.append("양식 예시 내용:\n" + s["sample"])
        if t.eval_items:
            parts.append("## 평가표")
            parts.extend(f"- [{e['key']}] {e['name']} ({e.get('max_score', '?')}점): {e.get('criteria', '')}" for e in t.eval_items)
    return "\n\n".join(parts)

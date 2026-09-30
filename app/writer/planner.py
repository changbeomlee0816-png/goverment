"""사업계획서 작성 파이프라인.

① 공고·양식·평가표 로드 → ② 섹션별 요구사항(지시문·평가항목) → ③ 부족 정보 인터뷰 질문
→ ④ 섹션별 초안 → ⑤ 사용자 수정(UI)
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Application, Company, Item, PlanDraft, PlanTemplate
from app.llm import claude_client
from app.writer import context, tools
from app.writer.template_parser import default_template

SOURCE_MARK = re.compile(r"\(출처\s*[:：]")
NUMBER = re.compile(r"\d[\d,.]*\s*(%|억|만|천|조|원|명|건|배|개|톤|kWh|MW|GW|년|개월|℃|점)")
MISSING = re.compile(r"\[확인 필요[^\]]*\]")


def ensure_default_template(session: Session) -> PlanTemplate:
    data = default_template()
    t = session.scalar(select(PlanTemplate).where(PlanTemplate.version == data["version"]))
    if t is None:
        t = PlanTemplate(
            name=data["name"], year=data["year"], version=data["version"],
            sections=data["sections"], eval_items=data["eval_items"], parsed_by="builtin",
        )
        session.add(t)
        session.flush()
    return t


def section_requirements(template: PlanTemplate, section: dict) -> dict:
    ev = next((e for e in template.eval_items or [] if e["key"] == section.get("eval_item")), None)
    return {
        "section": section["title"],
        "instructions": section.get("instructions", []),
        "page_limit": section.get("page_limit"),
        "eval_item": ev["name"] if ev else None,
        "max_score": ev["max_score"] if ev else section.get("max_score"),
        "criteria": ev.get("criteria") if ev else None,
    }


# ------------------------------------------------------------------ 인터뷰
RULE_QUESTIONS = [
    (r"(필요성|배경|문제)", "해결하려는 문제로 인한 사회적·경제적 비용 통계(수치와 출처)는 무엇입니까?"),
    (r"(개요|트렌드|동향)", "이 기술과 연계되는 국내외 기술·정책 트렌드(출처 포함)를 알려주세요."),
    (r"(목표|성능|지표)", "최종 성능지표별 현재 수준·목표치·측정방법·공인시험기관을 알려주세요."),
    (r"(파급|효과|기대)", "도입 시 절감되는 비용·시간·에너지 등 정량 효과(산출 근거 포함)는 얼마입니까?"),
    (r"(방법|절차|추진|일정|체계)", "단계별(3단계 내외) 수행 기간, 수행 주체, 주요 산출물을 알려주세요."),
    (r"(분담|참여기관|수행기관|인력)", "참여 기관·인력별 담당 업무와 참여 기간을 알려주세요."),
    (r"(선행|실적|역량)", "관련 선행연구(과제명·기간·결과·지재권)와 본 과제와의 차별점은 무엇입니까?"),
    (r"(지식재산|특허|IP)", "확보·출원 예정 특허와 선행특허 회피 전략을 알려주세요."),
    (r"(사업화|시장|매출|판매)", "목표 시장규모(TAM·SAM·SOM)와 출처, 5개년 매출 계획, 판매처·구매의향 확보 현황을 알려주세요."),
    (r"(해외|수출|글로벌)", "해외 진출 대상국과 진출 방식, 현재 수출 실적을 알려주세요."),
    (r"(투자|자금)", "후속 투자 유치 계획(시기·규모·대상)을 알려주세요."),
]


def rule_questions(template: PlanTemplate, app: Application, company: Company, item: Item | None) -> list[dict]:
    asked = {q["question"] for q in app.interview or []}
    out = []
    for s in template.sections:
        blob = s["title"] + " " + " ".join(s.get("instructions", []))
        for pattern, question in RULE_QUESTIONS:
            if not re.search(pattern, blob):
                continue
            if "성능지표" in question and item is not None and item.indicators and all(i.target and i.measure_method for i in item.indicators):
                continue
            if "선행연구" in question and company.prior_research:
                continue
            if question in asked:
                continue
            asked.add(question)
            out.append({"section_key": s["key"], "question": question, "why": f"'{s['title']}' 작성 지시문 대응", "answer": ""})
    return out


def generate_questions(session: Session, app: Application, use_llm: bool = True) -> list[dict]:
    company = session.get(Company, app.company_id)
    item = session.get(Item, app.item_id) if app.item_id else None
    template = app.template
    if use_llm and claude_client.is_available():
        facts = context.build_fact_sheet(app, company, item)
        answered = json.dumps(app.interview or [], ensure_ascii=False)
        data = claude_client.ClaudeClient().complete_json(
            "interview",
            f"<보유정보>\n{facts}\n</보유정보>\n<기존질문>\n{answered}\n</기존질문>\n부족한 정보에 대한 질문 목록을 만들어 주세요.",
            reference=context.build_reference(app),
            max_tokens=6000,
        )
        new = [{**q, "answer": ""} for q in data.get("questions", [])]
    else:
        new = rule_questions(template, app, company, item)
    app.interview = list(app.interview or []) + new
    session.flush()
    return new


# ------------------------------------------------------------------ 섹션 초안
def offline_draft(section: dict, req: dict, facts: str, app: Application) -> str:
    """LLM 없이 만드는 작성 골격: 지시문별 소제목 + 관련 사실 + [확인 필요] 자리표시자."""
    lines = []
    if req.get("eval_item"):
        lines.append(f"> 연계 평가항목: {req['eval_item']} ({req.get('max_score') or '?'}점)")
    for ins in section.get("instructions", []) or ["본문"]:
        topic = re.sub(r"^[※*☞▶√\s]+", "", ins)
        lines += ["", f"**{topic}**", "", "[확인 필요: 위 지시문에 맞는 내용 작성]"]
    answers = [q for q in app.interview or [] if q.get("section_key") == section["key"] and (q.get("answer") or "").strip()]
    if answers:
        lines += ["", "**인터뷰 답변 반영 메모**"] + [f"- {q['answer']}" for q in answers]
    title = section["title"]
    extras = app.extras or {}
    if re.search(r"(성능|지표|목표)", title) and "성능지표:" in facts:
        lines += ["", facts.split("- 성능지표:\n", 1)[1].split("\n## ", 1)[0]]
    if re.search(r"(시장|사업화)", title) and extras.get("market"):
        lines += ["", tools.market_table(tools.MarketSize(**extras["market"]))]
    if re.search(r"(매출|사업화)", title) and extras.get("forecast"):
        f = extras["forecast"]
        lines += ["", tools.revenue_table(tools.revenue_forecast(f["rows"], f["start_year"]))]
    if re.search(r"(분담|추진|절차)", title) and extras.get("roles"):
        lines += ["", tools.role_table(extras["roles"])]
    return "\n".join(lines).strip()


def split_sources(text: str) -> tuple[str, dict]:
    """LLM 출력 끝의 ```json {sources, missing}``` 블록을 분리."""
    m = re.search(r"```json\s*(\{.*?\})\s*```\s*$", text, re.S)
    if not m:
        return text.strip(), {}
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError:
        meta = {}
    return text[: m.start()].strip(), meta


def draft_section(session: Session, app: Application, section_key: str, use_llm: bool = True, extra_request: str = "") -> PlanDraft:
    template = app.template
    section = next(s for s in template.sections if s["key"] == section_key)
    req = section_requirements(template, section)
    company = session.get(Company, app.company_id)
    item = session.get(Item, app.item_id) if app.item_id else None
    facts = context.build_fact_sheet(app, company, item)

    sources: list = []
    if use_llm and claude_client.is_available():
        prompt = (
            f"<사실자료>\n{facts}\n</사실자료>\n\n"
            f"<작성대상섹션>\n{json.dumps(req, ensure_ascii=False, indent=1)}\n</작성대상섹션>\n"
            + (f"\n<추가요청>\n{extra_request}\n</추가요청>\n" if extra_request else "")
            + "\n위 섹션의 초안을 작성해 주세요."
        )
        result = claude_client.ClaudeClient().complete("section_writer", prompt, reference=context.build_reference(app), max_tokens=32000)
        content, meta = split_sources(result.text)
        sources = meta.get("sources", [])
    else:
        content = offline_draft(section, req, facts, app)

    draft = session.scalar(
        select(PlanDraft).where(PlanDraft.application_id == app.id, PlanDraft.section_key == section_key)
    )
    if draft is None:
        draft = PlanDraft(application_id=app.id, section_key=section_key)
        session.add(draft)
    draft.section_title = section["title"]
    draft.content = content
    draft.eval_item_key = section.get("eval_item")
    draft.template_version = f"{template.name}:{template.version}"
    draft.sources = sources
    session.flush()
    return draft


def unsourced_sentences(text: str) -> list[str]:
    """수치가 있으나 출처 표기가 없는 문장(UI·DOCX에서 노란색 표시 대상)."""
    out = []
    for sentence in re.split(r"(?<=[.다])\s+|\n", text):
        s = sentence.strip()
        if not s or s.startswith("|"):
            continue
        if NUMBER.search(s) and not SOURCE_MARK.search(s):
            out.append(s)
    return out


def missing_items(text: str) -> list[str]:
    return MISSING.findall(text)

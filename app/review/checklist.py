"""자체 점검(레드팀) — 규칙 점검 + 가상 채점.

규칙 점검: 평가항목 누락, 정량 수치 없는 목표, 성능지표–절차 미연계, 출처 없는 통계, 분량 불균형(배점 대비), [확인 필요] 잔존.
가상 채점: LLM(reviewer.md) 평가위원 페르소나. LLM이 없으면 규칙 기반 추정 점수(참고용).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.llm import claude_client
from app.writer.planner import MISSING, NUMBER, unsourced_sentences
from app.writer.template_parser import parse_template_text

GRADES = [("탁월", 1.0), ("우수", 0.8), ("보통", 0.6), ("미흡", 0.4), ("불량", 0.2)]


@dataclass
class Finding:
    check: str
    section: str
    detail: str
    severity: str = "보완"  # 필수/보완/참고


@dataclass
class ReviewInput:
    sections: list[dict]  # [{"key","title","content","eval_item","max_score"}]
    eval_items: list[dict] = field(default_factory=list)
    indicator_names: list[str] = field(default_factory=list)


def from_text(text: str, eval_items: list[dict] | None = None) -> ReviewInput:
    """외부 계획서(PDF/HWP 추출 텍스트)를 섹션으로 나눠 점검 입력으로 만든다."""
    parsed = parse_template_text(text)
    lines = text.splitlines()
    sections = []
    titles = [s["title"] for s in parsed]
    current_idx, buf = -1, {i: [] for i in range(len(titles))}
    title_set = {t: i for i, t in enumerate(titles)}
    for line in lines:
        s = line.strip()
        if s in title_set:
            current_idx = title_set[s]
            continue
        if current_idx >= 0:
            buf[current_idx].append(s)
    for i, s in enumerate(parsed):
        sections.append({"key": s["key"], "title": s["title"], "content": "\n".join(buf[i]), "eval_item": None, "max_score": None})
    if not sections:
        sections = [{"key": "s1", "title": "전체", "content": text, "eval_item": None, "max_score": None}]
    return ReviewInput(sections=sections, eval_items=eval_items or [])


def rule_checks(inp: ReviewInput) -> list[Finding]:
    findings: list[Finding] = []
    by_eval: dict[str, list[dict]] = {}
    for s in inp.sections:
        if s.get("eval_item"):
            by_eval.setdefault(s["eval_item"], []).append(s)

    for e in inp.eval_items:
        linked = by_eval.get(e["key"], [])
        if not linked or all(len((s.get("content") or "").strip()) < 50 for s in linked):
            findings.append(Finding("평가항목 누락", e["name"], f"배점 {e.get('max_score', '?')}점 항목에 대응하는 작성 내용이 없거나 부족합니다.", "필수"))

    for s in inp.sections:
        content = s.get("content") or ""
        title = s["title"]
        if not content.strip():
            findings.append(Finding("미작성 섹션", title, "내용이 비어 있습니다.", "필수"))
            continue
        if re.search(r"목표", title) and not NUMBER.search(content):
            findings.append(Finding("정량 수치 없는 목표", title, "목표를 수치·단위로 제시하십시오.", "필수"))
        unsourced = unsourced_sentences(content)
        if unsourced:
            findings.append(Finding("출처 없는 통계", title, f"{len(unsourced)}개 문장: " + " / ".join(u[:40] for u in unsourced[:3]), "보완"))
        missing = MISSING.findall(content)
        if missing:
            findings.append(Finding("확인 필요 잔존", title, f"{len(missing)}건: " + ", ".join(m[:30] for m in missing[:3]), "필수"))

    method_text = " ".join(s.get("content") or "" for s in inp.sections if re.search(r"(방법|절차|추진)", s["title"]))
    if inp.indicator_names and method_text:
        unlinked = [n for n in inp.indicator_names if n not in method_text]
        if unlinked:
            findings.append(Finding("성능지표–절차 미연계", "연구개발 방법", "절차별 방법에 언급되지 않은 성능지표: " + ", ".join(unlinked), "보완"))

    scored = [s for s in inp.sections if s.get("max_score") and (s.get("content") or "").strip()]
    if len(scored) >= 2:
        total_len = sum(len(s["content"]) for s in scored)
        total_score = sum(s["max_score"] for s in scored)
        for s in scored:
            share_len = len(s["content"]) / total_len
            share_score = s["max_score"] / total_score
            if share_len < share_score * 0.5:
                findings.append(Finding("분량 불균형", s["title"], f"배점 비중 {share_score:.0%} 대비 분량 {share_len:.0%}로 부족합니다.", "보완"))
            elif share_len > share_score * 2:
                findings.append(Finding("분량 불균형", s["title"], f"배점 비중 {share_score:.0%} 대비 분량 {share_len:.0%}로 과다합니다.", "참고"))
    return findings


def heuristic_scores(inp: ReviewInput, findings: list[Finding]) -> dict:
    """LLM이 없을 때의 규칙 기반 추정 채점(참고용)."""
    eval_items = inp.eval_items or [{"key": "all", "name": "전체", "max_score": 100}]
    items = []
    for e in eval_items:
        linked = [s for s in inp.sections if s.get("eval_item") == e["key"]] or (inp.sections if e["key"] == "all" else [])
        text = "\n".join(s.get("content") or "" for s in linked)
        titles = {s["title"] for s in linked}
        ratio = 1.0
        if len(text.strip()) < 50:
            ratio = 0.2
        else:
            if not NUMBER.search(text):
                ratio -= 0.2
            issues = [f for f in findings if f.section in titles or f.section == e["name"]]
            ratio -= 0.1 * sum(1 for f in issues if f.severity == "필수")
            ratio -= 0.05 * sum(1 for f in issues if f.severity == "보완")
        ratio = max(0.2, min(1.0, ratio))
        grade = next(g for g, r in GRADES if ratio >= r - 1e-9)
        grade_ratio = dict(GRADES)[grade]
        items.append(
            {
                "eval_item": e["name"],
                "max_score": e.get("max_score"),
                "grade": grade,
                "score": round((e.get("max_score") or 0) * grade_ratio, 1),
                "evidence": "규칙 기반 추정",
                "weakness": "; ".join(f.check for f in findings if f.section in titles or f.section == e["name"]) or "-",
                "suggestion": "규칙 점검 항목을 보완하십시오." if ratio < 1 else "-",
            }
        )
    total = round(sum(i["score"] for i in items), 1)
    return {"items": items, "total": total, "overall": "규칙 기반 추정 점수입니다(LLM 미사용). 정확한 가상 채점은 API 키 설정 후 실행하십시오.", "method": "rule"}


def virtual_scoring(inp: ReviewInput, findings: list[Finding], reference: str = "", use_llm: bool = True) -> dict:
    if use_llm and claude_client.is_available():
        plan = "\n\n".join(f"## {s['title']}\n{s.get('content') or ''}" for s in inp.sections)
        ref = reference
        if inp.eval_items:
            ref += "\n\n## 평가표\n" + json.dumps(inp.eval_items, ensure_ascii=False)
        data = claude_client.ClaudeClient().complete_json(
            "reviewer", f"<사업계획서>\n{plan}\n</사업계획서>\n평가표 항목별로 채점해 주세요.", reference=ref or None, max_tokens=16000
        )
        data["method"] = "llm"
        return data
    return heuristic_scores(inp, findings)

"""사업계획서 양식·평가표 → 섹션/작성지시문/평가항목 구조화.

1) 규칙 파서: 번호 체계(Ⅰ., 1., 1-1., 가., □, ① 등)로 섹션을 나누고 ※·* 등 지시문을 모은다.
2) LLM 파서(parse_template.md): 표 안 지시문·평가표 매핑까지 더 정확히 구조화. API 키가 있을 때 선택 사용.
"""
from __future__ import annotations

import json
import re

from app.config import TEMPLATE_DIR
from app.llm import claude_client

ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ"
HEADING_PATTERNS: list[tuple[int, re.Pattern]] = [
    (1, re.compile(rf"^([{ROMAN}]|[IVX]{{1,4}})\s*[.．]\s*\S")),
    (1, re.compile(r"^제\s*\d+\s*[장절]\s*\S")),
    (1, re.compile(r"^\d{1,2}\s*[.．]\s*[가-힣A-Za-z(]")),
    (2, re.compile(r"^\d{1,2}\s*[-－.]\s*\d{1,2}\s*[.)．]?\s+[가-힣A-Za-z(]")),
    (2, re.compile(r"^[가-하]\s*[.．)]\s*[가-힣A-Za-z(]")),
    (2, re.compile(r"^□\s*\S")),
    (3, re.compile(r"^\d{1,2}-\d{1,2}-\d{1,2}\s*[.)]?\s*\S")),
    (3, re.compile(r"^\(\d{1,2}\)\s*[가-힣A-Za-z]")),
    (3, re.compile(r"^[①-⑳]\s*[가-힣A-Za-z]")),
]
INSTRUCTION_START = ("※", "*", "☞", "▶", "√", "<작성", "[작성", "(작성", "작성요령", "작성방법")
INSTRUCTION_WORDS = re.compile(r"(작성|기재|기술하|서술|제시|명시|기입|첨부|포함하여|포함할 것|기술할 것|작성할 것)")
PAGE_LIMIT = re.compile(r"(\d+)\s*(페이지|쪽|page|p|매)\s*(이내|내외|이하|以內)", re.I)
EXCLUDE_TITLES = re.compile(r"(표\s*지|목\s*차|서약서|동의서|확약서|확인서|위임장|제출서류|체크리스트|개인정보)")
EVAL_LINE = re.compile(r"^(?P<name>[^\d|]{2,40}?)\s*(\||\s)\s*(?P<score>\d{1,3})\s*점?\s*(\|.*)?$")
EVAL_INLINE = re.compile(r"(?P<name>[가-힣A-Za-z·\s()]{2,40}?)\s*[\(（]?\s*(?P<score>\d{1,3})\s*점\s*[\)）]?")


def heading_level(line: str) -> int | None:
    if len(line) > 70:
        return None
    for level, pattern in HEADING_PATTERNS:
        if pattern.match(line):
            return level
    return None


def is_instruction(line: str) -> bool:
    s = line.strip()
    if s.startswith(INSTRUCTION_START):
        return True
    return bool(INSTRUCTION_WORDS.search(s)) and (s.startswith(("(", "-", "ㅇ", "○", "·", "•")) or len(s) < 120)


def parse_template_text(text: str, max_level: int = 2) -> list[dict]:
    """규칙 기반 섹션 분할. max_level 이하 제목만 섹션으로, 하위 제목은 지시문 맥락으로 둔다."""
    sections: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        level = heading_level(line)
        if level is not None and level <= max_level:
            current = {
                "key": f"s{len(sections) + 1}",
                "title": line,
                "level": level,
                "instructions": [],
                "sample": [],
                "page_limit": None,
                "eval_item": None,
                "max_score": None,
            }
            sections.append(current)
            m = PAGE_LIMIT.search(line)
            if m:
                current["page_limit"] = m.group(0)
            continue
        if current is None:
            continue
        m = PAGE_LIMIT.search(line)
        if m and not current["page_limit"]:
            current["page_limit"] = m.group(0)
        if level is not None or is_instruction(line):
            current["instructions"].append(line)
        else:
            current["sample"].append(line)

    cleaned = [s for s in sections if not EXCLUDE_TITLES.search(s["title"])]
    # 본문이 전혀 없는 1단계 제목은 하위 섹션의 부모로만 둔다(유지하되 표시용)
    for s in cleaned:
        s["sample"] = "\n".join(s["sample"][:30])
    for i, s in enumerate(cleaned, start=1):
        s["key"] = f"s{i}"
    return cleaned


def parse_eval_text(text: str) -> list[dict]:
    """평가표 텍스트 → [{"key","name","max_score","criteria"}]."""
    items: list[dict] = []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for idx, line in enumerate(lines):
        if re.search(r"(합\s*계|총\s*점|^계\b|소\s*계)", line):
            continue
        m = EVAL_LINE.match(line) or EVAL_INLINE.search(line)
        if not m:
            continue
        name = re.sub(r"^\s*(?:\d+\s*[.)]|[가-하]\s*[.)]|[□○ㅇ●■◦·①-⑳\-])\s*", "", m.group("name")).strip(" |:-")
        score = int(m.group("score"))
        if not name or score <= 0 or score > 100 or len(name) < 2:
            continue
        criteria = []
        for nxt in lines[idx + 1 : idx + 4]:
            if EVAL_LINE.match(nxt) or EVAL_INLINE.search(nxt):
                break
            criteria.append(nxt)
        items.append({"key": f"e{len(items) + 1}", "name": name, "max_score": score, "criteria": " ".join(criteria)[:300]})
    return items


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^가-힣A-Za-z]", "", text)
    return {t[i : i + 2] for i in range(len(t) - 1)}


def link_eval_items(sections: list[dict], eval_items: list[dict]) -> list[dict]:
    """섹션 제목·지시문과 평가항목명·기준의 글자 bigram 유사도로 연결."""
    if not eval_items:
        return sections
    for s in sections:
        sb = _bigrams(s["title"] + " ".join(s["instructions"]))
        best, best_sim = None, 0.0
        for e in eval_items:
            eb = _bigrams(e["name"] + " " + e.get("criteria", ""))
            if not sb or not eb:
                continue
            sim = len(sb & eb) / min(len(sb), len(eb))
            if sim > best_sim:
                best, best_sim = e, sim
        if best and best_sim >= 0.2:
            s["eval_item"] = best["key"]
            s["max_score"] = best["max_score"]
    return sections


def parse_with_llm(template_text: str, eval_text: str | None = None) -> tuple[list[dict], list[dict]]:
    reference = "## 사업계획서 양식\n" + template_text
    if eval_text:
        reference += "\n\n## 평가표\n" + eval_text
    data = claude_client.ClaudeClient().complete_json(
        "parse_template", "양식을 섹션 목록과 평가항목으로 구조화해 주세요.", reference=reference, max_tokens=16000
    )
    sections = data.get("sections", [])
    eval_items = data.get("eval_items", [])
    scores = {e["key"]: e.get("max_score") for e in eval_items}
    for i, s in enumerate(sections, start=1):
        s.setdefault("key", f"s{i}")
        s.setdefault("instructions", [])
        s.setdefault("sample", "")
        s["max_score"] = scores.get(s.get("eval_item"))
    return sections, eval_items


def parse_template(template_text: str, eval_text: str | None = None, use_llm: bool = False) -> tuple[list[dict], list[dict], str]:
    """(sections, eval_items, parsed_by)"""
    if use_llm and claude_client.is_available():
        sections, eval_items = parse_with_llm(template_text, eval_text)
        return sections, eval_items, "llm"
    sections = parse_template_text(template_text)
    eval_items = parse_eval_text(eval_text) if eval_text else []
    return link_eval_items(sections, eval_items), eval_items, "rule"


def default_template() -> dict:
    """양식 파일이 없을 때 쓰는 교육 기준 R&D 표준 섹션(data/templates/default_rnd.json)."""
    return json.loads((TEMPLATE_DIR / "default_rnd.json").read_text(encoding="utf-8"))

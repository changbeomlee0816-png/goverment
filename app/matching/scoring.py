"""2단계 점수화(0~100). 가중치는 config/settings.json의 matching.weights.

차원: 목적 적합도(purpose) · TRL 적합도(trl) · 규모·기간 적합도(scale) · 역량(capability) · 가점(bonus)
각 차원은 0~1 점수와 설명(note)을 만들고, 가중치를 곱해 합산한다. LLM 미사용.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.matching.profiles import AnnouncementProfile, CompanyProfile, ItemProfile

DEFAULT_WEIGHTS = {"purpose": 30, "trl": 20, "scale": 15, "capability": 20, "bonus": 15}
DIM_LABELS = {
    "purpose": "목적 적합도",
    "trl": "TRL 적합도",
    "scale": "규모·기간 적합도",
    "capability": "역량",
    "bonus": "가점",
}
# 사업유형별 통상 TRL 범위(공고에 명시 요건이 없을 때의 추정치)
CATEGORY_TRL = {
    "R&D": (3, 7),
    "시제품": (5, 7),
    "시험분석": (5, 8),
    "인증": (6, 9),
    "판로": (7, 9),
}
STOPWORDS = {"지원", "사업", "기업", "공고", "모집", "및", "등", "위한", "년도", "참여", "신청", "대상", "개발", "기술"}


@dataclass
class ScoreResult:
    total: float
    detail: dict = field(default_factory=dict)  # {dim: {"label","score","points","weight","note"}}

    def top_and_bottom(self) -> tuple[str, str]:
        ranked = sorted(self.detail.items(), key=lambda kv: kv[1]["score"])
        return ranked[-1][0], ranked[0][0]


def tokens(text: str) -> set[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text or "")
    return {w.lower() for w in words if w not in STOPWORDS}


def bigrams(text: str) -> set[str]:
    compact = re.sub(r"[^가-힣A-Za-z0-9]", "", text or "").lower()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def purpose_score(item: ItemProfile | None, ann: AnnouncementProfile) -> tuple[float, str]:
    if item is None:
        return 0.5, "아이템 미선택(중립 0.5)"
    ann_text = " ".join([ann.text, " ".join(ann.purpose_keywords)])
    ann_lower = ann_text.lower()
    kws = [k for k in item.keywords if k]
    hits = [k for k in kws if k.lower() in ann_lower]
    kw_ratio = len(hits) / len(kws) if kws else 0.0
    item_text = " ".join([item.name, item.summary, item.issue, " ".join(kws)])
    a, b = bigrams(item_text), bigrams(ann_text)
    overlap = len(a & b) / min(len(a), len(b)) if a and b else 0.0
    score = min(1.0, 0.6 * min(1.0, kw_ratio * 1.5) + 0.4 * min(1.0, overlap * 2))
    note = f"키워드 일치 {len(hits)}/{len(kws)}" + (f" ({', '.join(hits[:5])})" if hits else "")
    return round(score, 3), note


def required_trl(ann: AnnouncementProfile) -> tuple[tuple[int, int] | None, str]:
    for r in ann.rules:
        if r.field == "trl" and isinstance(r.value, (list, tuple)) and len(r.value) == 2:
            return (int(r.value[0]), int(r.value[1])), "공고 명시"
    if ann.is_rnd:
        return CATEGORY_TRL["R&D"], "R&D 통상범위(추정)"
    if ann.category in CATEGORY_TRL:
        return CATEGORY_TRL[ann.category], f"{ann.category} 통상범위(추정)"
    return None, "요구 TRL 정보 없음"


def trl_score(item: ItemProfile | None, ann: AnnouncementProfile) -> tuple[float, str]:
    req, basis = required_trl(ann)
    if item is None or item.trl_current is None or req is None:
        return 0.5, f"확인 필요 ({basis})"
    lo, hi = req
    cur = item.trl_current
    tgt = item.trl_target or cur
    if cur <= hi and tgt >= lo:
        return 1.0, f"아이템 TRL {cur}→{tgt}, 요구 {lo}~{hi} ({basis})"
    gap = lo - tgt if tgt < lo else cur - hi
    score = max(0.0, 1.0 - 0.25 * gap)
    return score, f"아이템 TRL {cur}→{tgt}, 요구 {lo}~{hi}, 차이 {gap}단계 ({basis})"


def _ratio(a: float | None, b: float | None) -> float | None:
    if not a or not b:
        return None
    return min(a, b) / max(a, b)


def scale_score(item: ItemProfile | None, ann: AnnouncementProfile) -> tuple[float, str]:
    if item is None:
        return 0.5, "아이템 미선택(중립 0.5)"
    parts, notes = [], []
    r = _ratio(item.budget_krw, ann.support_amount_krw)
    if r is not None:
        parts.append(r)
        notes.append(f"지원금 {ann.support_amount_krw / 1e8:.1f}억 vs 필요예산 {item.budget_krw / 1e8:.1f}억")
    r = _ratio(item.dev_period_months, ann.dev_period_months)
    if r is not None:
        parts.append(r)
        notes.append(f"기간 {ann.dev_period_months}개월 vs 개발기간 {item.dev_period_months}개월")
    if not parts:
        return 0.5, "지원규모·기간 확인 필요"
    return round(sum(parts) / len(parts), 3), ", ".join(notes)


def capability_score(company: CompanyProfile) -> tuple[float, str]:
    score, notes = 0.0, []
    if company.has_rnd_lab:
        score += 0.3
        notes.append("부설연구소")
    if company.rnd_staff:
        score += min(0.2, 0.05 * company.rnd_staff)
        notes.append(f"연구인력 {company.rnd_staff}명")
    if company.national_rnd_count:
        score += min(0.25, 0.125 * company.national_rnd_count)
        notes.append(f"국가R&D {company.national_rnd_count}건")
    if company.patents:
        score += min(0.25, 0.05 * company.patents)
        notes.append(f"특허 {company.patents}건")
    return round(min(1.0, score), 3), ", ".join(notes) or "역량 정보 없음"


BONUS_CERTS = ("벤처", "이노비즈", "메인비즈", "여성기업", "장애인기업", "사회적기업", "소부장", "강소기업", "뿌리기업")


def bonus_score(company: CompanyProfile, item: ItemProfile | None, ann: AnnouncementProfile) -> tuple[float, str]:
    score, notes = 0.0, []
    region = ann.region or ""
    if company.region_sido and (company.region_sido in region):
        score += 0.4
        notes.append(f"지역({company.region_sido})")
    elif region == "전국" or not region:
        score += 0.2
    certs = [c for c in company.certifications if any(b in c for b in BONUS_CERTS)]
    if certs:
        score += min(0.3, 0.1 * len(certs))
        notes.append("인증 " + ",".join(certs))
    if company.ceo_attributes:
        score += 0.15
        notes.append("대표자 " + ",".join(company.ceo_attributes))
    if item is not None:
        wants_rnd = item.preferred_type == "R&D"
        if wants_rnd == ann.is_rnd:
            score += 0.15
            notes.append(f"선호유형 일치({item.preferred_type})")
    return round(min(1.0, score), 3), ", ".join(notes) or "해당 가점 없음"


def score(
    company: CompanyProfile,
    item: ItemProfile | None,
    ann: AnnouncementProfile,
    weights: dict | None = None,
) -> ScoreResult:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    weight_sum = sum(weights.values()) or 1
    dims = {
        "purpose": purpose_score(item, ann),
        "trl": trl_score(item, ann),
        "scale": scale_score(item, ann),
        "capability": capability_score(company),
        "bonus": bonus_score(company, item, ann),
    }
    detail, total = {}, 0.0
    for key, (value, note) in dims.items():
        points = value * weights[key] * 100 / weight_sum
        total += points
        detail[key] = {
            "label": DIM_LABELS[key],
            "score": round(value, 3),
            "weight": weights[key],
            "points": round(points, 1),
            "note": note,
        }
    return ScoreResult(total=round(total, 1), detail=detail)

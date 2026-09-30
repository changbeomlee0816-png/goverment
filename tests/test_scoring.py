from datetime import date

from app.matching.profiles import AnnouncementProfile, CompanyProfile, ItemProfile, Rule
from app.matching.scoring import DEFAULT_WEIGHTS, capability_score, score, trl_score


def company(**kw):
    base = dict(name="c", region_sido="충남", has_rnd_lab=True, rnd_staff=4, patents=2, national_rnd_count=1, certifications=["벤처"])
    base.update(kw)
    return CompanyProfile(**base)


def item(**kw):
    base = dict(name="AI 공장 에너지 관리 FEMS", keywords=["에너지", "FEMS", "탄소중립"], summary="전력 피크 예측",
                trl_current=4, trl_target=7, dev_period_months=24, budget_krw=300_000_000, preferred_type="R&D")
    base.update(kw)
    return ItemProfile(**base)


def ann(**kw):
    base = dict(id=1, title="탄소중립 에너지효율화 기술개발(R&D)", is_rnd=True, category="R&D", region="전국",
                support_amount_krw=300_000_000, dev_period_months=24, text="중소기업 에너지 효율화 FEMS 탄소중립 기술개발")
    base.update(kw)
    return AnnouncementProfile(**base)


def test_total_in_range_and_weights_sum():
    r = score(company(), item(), ann())
    assert 0 <= r.total <= 100
    assert abs(sum(d["points"] for d in r.detail.values()) - r.total) < 0.5
    assert {d["weight"] for d in r.detail.values()} <= set(DEFAULT_WEIGHTS.values())


def test_relevant_scores_higher_than_irrelevant():
    good = score(company(), item(), ann())
    bad = score(company(), item(), ann(title="관광 콘텐츠 판로 지원", is_rnd=False, category="판로", text="관광 콘텐츠 전시 마케팅",
                                       support_amount_krw=20_000_000, dev_period_months=None))
    assert good.total > bad.total
    assert good.detail["purpose"]["score"] > bad.detail["purpose"]["score"]


def test_trl_overlap_and_gap():
    assert trl_score(item(), ann())[0] == 1.0
    # 판로(7~9) vs 아이템 2→3: 4단계 차이 → 0
    assert trl_score(item(trl_current=2, trl_target=3), ann(is_rnd=False, category="판로"))[0] == 0.0
    # 명시 TRL 규칙 우선
    s, note = trl_score(item(trl_current=4, trl_target=5), ann(rules=[Rule("trl", "between", [6, 8])]))
    assert s == 0.75 and "공고 명시" in note


def test_trl_unknown_neutral():
    s, note = trl_score(item(trl_current=None), ann())
    assert s == 0.5 and "확인 필요" in note


def test_scale_ratio():
    r = score(company(), item(budget_krw=600_000_000), ann(support_amount_krw=300_000_000, dev_period_months=None))
    assert r.detail["scale"]["score"] == 0.5


def test_capability_caps_at_one():
    assert capability_score(company(rnd_staff=100, patents=100, national_rnd_count=10))[0] == 1.0
    assert capability_score(company(has_rnd_lab=False, rnd_staff=0, patents=0, national_rnd_count=0))[0] == 0.0


def test_custom_weights_normalized():
    r = score(company(), item(), ann(), {"purpose": 100, "trl": 0, "scale": 0, "capability": 0, "bonus": 0})
    assert abs(r.total - r.detail["purpose"]["score"] * 100) < 0.2


def test_no_item_is_neutral():
    r = score(company(), None, ann())
    assert r.detail["purpose"]["score"] == 0.5

from datetime import date

from app.matching.profiles import AnnouncementProfile, CompanyProfile, Rule
from app.matching.rules import hard_filter

TODAY = date(2026, 9, 30)


def company(**kw):
    base = dict(name="테스트", founded_date=date(2020, 3, 1), region_sido="충남", revenue_last_year=4_000_000_000,
                employees=28, rnd_staff=9, has_rnd_lab=True, certifications=["벤처"], industry_name="응용 소프트웨어 개발")
    base.update(kw)
    return CompanyProfile(**base)


def ann(**kw):
    base = dict(id=1, title="t", apply_end=date(2026, 10, 20))
    base.update(kw)
    return AnnouncementProfile(**base)


def test_passes_without_rules():
    r = hard_filter(company(), ann(), TODAY)
    assert r.eligible and not r.fail_reasons


def test_deadline_passed():
    r = hard_filter(company(), ann(apply_end=date(2026, 9, 1)), TODAY)
    assert not r.eligible
    assert r.fail_reasons[0].startswith("접수 마감")


def test_missing_deadline_is_warning():
    r = hard_filter(company(), ann(apply_end=None), TODAY)
    assert r.eligible and "접수 마감일 확인 필요" in r.warnings


def test_recruiting_closed():
    assert not hard_filter(company(), ann(recruiting="N"), TODAY).eligible


def test_years_in_business():
    rule = Rule("years_in_business", "<=", 7, "업력 7년 이내", True)
    assert hard_filter(company(), ann(rules=[rule]), TODAY).eligible
    r = hard_filter(company(founded_date=date(2015, 1, 1)), ann(rules=[rule]), TODAY)
    assert not r.eligible
    assert "업력 7년 이내" in r.fail_reasons[0]


def test_years_unknown_is_warning():
    rule = Rule("years_in_business", "<=", 7, "업력 7년 이내", True)
    r = hard_filter(company(founded_date=None), ann(rules=[rule]), TODAY)
    assert r.eligible and any("업력" in w for w in r.warnings)


def test_region_rule_and_region_field():
    rule = Rule("region_sido", "in", ["서울"], "서울 소재", True)
    assert not hard_filter(company(), ann(rules=[rule]), TODAY).eligible
    # 규칙이 없어도 지자체 공고 지역 필드로 판정
    assert not hard_filter(company(), ann(level="지자체", region="서울"), TODAY).eligible
    assert hard_filter(company(), ann(level="지자체", region="충남,대전"), TODAY).eligible
    # 부처 공고는 지역 필드로 거르지 않음
    assert hard_filter(company(), ann(level="부처", region="서울"), TODAY).eligible


def test_revenue_employees():
    rules = [Rule("revenue_krw", "<=", 1_000_000_000), Rule("employees", ">=", 5)]
    r = hard_filter(company(), ann(rules=rules), TODAY)
    assert not r.eligible and len(r.fail_reasons) == 1
    assert "[미확인 규칙]" in r.fail_reasons[0]


def test_between_and_industry():
    assert hard_filter(company(), ann(rules=[Rule("employees", "between", [10, 50])]), TODAY).eligible
    assert not hard_filter(company(), ann(rules=[Rule("industry", "in", ["제조업"])]), TODAY).eligible
    assert hard_filter(company(), ann(rules=[Rule("industry", "not_in", ["제조업"])]), TODAY).eligible


def test_certification_lab_ceo():
    assert hard_filter(company(), ann(rules=[Rule("certification", "has_any", ["벤처", "이노비즈"])]), TODAY).eligible
    assert not hard_filter(company(), ann(rules=[Rule("certification", "has_all", ["벤처", "이노비즈"])]), TODAY).eligible
    assert not hard_filter(company(has_rnd_lab=False), ann(rules=[Rule("has_rnd_lab", "==", True)]), TODAY).eligible
    assert not hard_filter(company(), ann(rules=[Rule("ceo_attribute", "has_any", ["여성"])]), TODAY).eligible


def test_other_rule_is_warning_only():
    r = hard_filter(company(), ann(rules=[Rule("other", "note", None, "국세 체납 없는 기업")]), TODAY)
    assert r.eligible and any("국세 체납" in w for w in r.warnings)

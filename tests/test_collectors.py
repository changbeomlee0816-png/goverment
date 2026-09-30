from datetime import date

from app.collectors import bizinfo, kstartup
from app.collectors.base import classify_level, dedup_key, normalize_region, parse_amount_krw, parse_period, upsert_announcements
from app.collectors.manual_upload import annual_candidates, guess_fields


def test_parse_period_formats():
    assert parse_period("20260101 ~ 20260131") == (date(2026, 1, 1), date(2026, 1, 31))
    assert parse_period("2026.03.02 ~ 2026.03.20") == (date(2026, 3, 2), date(2026, 3, 20))
    assert parse_period("2026년 4월 1일(수) ~ 4월 15일") == (date(2026, 4, 1), date(2026, 4, 15))
    assert parse_period("마감 2026-10-20") == (None, date(2026, 10, 20))
    assert parse_period(None) == (None, None)


def test_amounts():
    assert parse_amount_krw("과제당 최대 3억원 이내") == 300_000_000
    assert parse_amount_krw("기업당 최대 5,000만원") == 50_000_000
    assert parse_amount_krw("최대 1억 5천만원") == 150_000_000
    assert parse_amount_krw("지원 없음") is None


def test_classify_level():
    assert classify_level("중소벤처기업부", "중소기업기술정보진흥원") == "부처"
    assert classify_level("충청남도", "충남테크노파크") == "지자체"
    assert classify_level("서울특별시") == "지자체"
    assert classify_level("천안시") == "지자체"
    assert classify_level(None, "경기테크노파크") == "지역기관"


def test_normalize_region():
    assert normalize_region("충청남도 천안시") == "충남"
    assert normalize_region("전국") == "전국"


def test_dedup_key_ignores_spacing():
    a = dedup_key("[2026] 기술개발 사업", "중기부", date(2026, 1, 1), None)
    b = dedup_key("2026 기술개발사업", "중기부", date(2026, 1, 1), None)
    assert a == b


def test_bizinfo_parse_candidate_fields():
    payload = {"jsonArray": [{
        "pblancId": "PBLN_1", "pblancNm": "2026년 R&D 기술개발 지원", "jrsdInsttNm": "중소벤처기업부",
        "excInsttNm": "중소기업기술정보진흥원", "reqstBeginEndDe": "20261001 ~ 20261031",
        "pblancUrl": "/web/lay1/bbs/S1T122C128/AS/74/view.do?pblancId=PBLN_1", "bsnsSumryCn": "<p>기술개발 지원</p>",
        "hashTags": "기술,충남", "pldirSportRealmLclasCodeNm": "기술",
    }]}
    items = bizinfo.parse(payload)
    assert len(items) == 1
    a = items[0]
    assert a.title == "2026년 R&D 기술개발 지원" and a.apply_end == date(2026, 10, 31)
    assert a.url.startswith("https://www.bizinfo.go.kr/") and a.summary == "기술개발 지원"


def test_kstartup_parse():
    payload = {"currentCount": 1, "data": [{
        "pbanc_sn": 1234, "biz_pbanc_nm": "예비창업패키지", "pbanc_rcpt_bgng_dt": "20261001", "pbanc_rcpt_end_dt": "20261020",
        "sprv_inst": "창업진흥원", "supt_regin": "전국", "detl_pg_url": "https://www.k-startup.go.kr/x", "rcrt_prgs_yn": "Y",
    }]}
    items = kstartup.parse(payload)
    assert items[0].title == "예비창업패키지" and items[0].apply_start == date(2026, 10, 1)
    assert items[0].raw["_recruiting"] == "Y"


def test_upsert_dedup(session):
    items = bizinfo.parse({"jsonArray": [{"pblancNm": "A 사업", "jrsdInsttNm": "산업부", "reqstBeginEndDe": "20261001 ~ 20261031"}]})
    assert upsert_announcements(session, items) == (1, 0)
    assert upsert_announcements(session, items) == (0, 1)


def test_guess_fields_from_notice():
    text = "2026년 스마트공장 지원사업 공고\n충청남도\n1. 신청자격\n충남 소재 중소기업\n접수기간: 2026. 10. 1. ~ 2026. 10. 20.\n지원규모: 최대 5,000만원"
    f = guess_fields(text)
    assert f["title"] == "2026년 스마트공장 지원사업 공고"
    assert f["apply_end"] == date(2026, 10, 20)
    assert "5,000만원" in f["budget_text"]
    assert "충남 소재" in f["eligibility_text"]


def test_annual_candidates():
    text = "에너지효율화 기술개발사업 (신규) 중소기업 대상 5월 공고 예정\n관광진흥 사업 2월 공고\n탄소중립 실증사업 계속 1월"
    rows = annual_candidates(text, ["중소기업", "에너지"], 3)
    assert len(rows) == 1 and "에너지효율화" in rows[0]["근거문장"]

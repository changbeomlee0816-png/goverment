from app.writer.template_parser import link_eval_items, parse_eval_text, parse_template_text

TEMPLATE = """
사업계획서 표지
목 차
1. 기술개발 개요 및 필요성
※ 개발기술의 개요와 필요성을 사회적 비용 통계와 함께 작성
1-1. 기술개발 목표
※ 최종 목표를 정량적 성능지표로 제시 (2페이지 이내)
(예시) 에너지 절감률 15%
2. 기술개발 방법
가. 추진 체계
- 참여기관별 역할을 기재
3. 사업화 계획
□ 목표 시장
※ 시장규모는 출처를 명시하여 작성
개인정보 수집·이용 동의서
"""

EVAL = """
평가항목 | 배점
기술개발 목표의 명확성 | 30
기술개발 방법의 적정성 | 30
사업화 계획의 타당성 | 40
합계 | 100
"""


def test_sections_and_instructions():
    sections = parse_template_text(TEMPLATE)
    titles = [s["title"] for s in sections]
    assert titles[:3] == ["1. 기술개발 개요 및 필요성", "1-1. 기술개발 목표", "2. 기술개발 방법"]
    assert "가. 추진 체계" in titles and "□ 목표 시장" in titles
    assert not any("동의서" in t for t in titles)
    goal = sections[1]
    assert any("정량적 성능지표" in i for i in goal["instructions"])
    assert goal["page_limit"] == "2페이지 이내"
    assert "(예시) 에너지 절감률 15%" in goal["sample"]
    assert [s["key"] for s in sections] == [f"s{i}" for i in range(1, len(sections) + 1)]


def test_eval_items_parsing():
    items = parse_eval_text(EVAL)
    assert [(i["name"], i["max_score"]) for i in items] == [
        ("기술개발 목표의 명확성", 30), ("기술개발 방법의 적정성", 30), ("사업화 계획의 타당성", 40),
    ]


def test_eval_inline_format():
    items = parse_eval_text("○ 기술성(40점): 기술의 독창성\n○ 사업성(60점): 시장성")
    assert [(i["name"], i["max_score"]) for i in items] == [("기술성", 40), ("사업성", 60)]


def test_link_eval_items():
    sections = link_eval_items(parse_template_text(TEMPLATE), parse_eval_text(EVAL))
    by_title = {s["title"]: s for s in sections}
    assert by_title["1-1. 기술개발 목표"]["eval_item"] == "e1"
    assert by_title["3. 사업화 계획"]["eval_item"] == "e3"
    assert by_title["3. 사업화 계획"]["max_score"] == 40

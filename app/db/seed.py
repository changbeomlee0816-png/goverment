"""샘플 데이터: 에너지 관리 솔루션 기업 + 아이템 + 성능지표 + 선행연구 + 샘플 공고 3건.

    python -m app.db.seed
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select

from app.collectors.base import AnnouncementData, upsert_announcements
from app.db.models import Announcement, Company, Document, EligibilityRule, Item, PerformanceIndicator, PriorResearch
from app.db.session import session_scope


def seed(session) -> Company:
    existing = session.scalar(select(Company).where(Company.name == "(주)그린에너지솔루션"))
    if existing:
        return existing
    c = Company(
        name="(주)그린에너지솔루션",
        biz_no="123-45-67890",
        founded_date=date(2020, 3, 15),
        region_sido="충남",
        region_sigungu="천안시",
        industry_code="J58222",
        industry_name="응용 소프트웨어 개발 및 공급업",
        revenue_last_year=4_200_000_000,
        employees=28,
        rnd_staff=9,
        rnd_ratio=12.5,
        has_rnd_lab=True,
        certifications=["벤처", "이노비즈"],
        ceo_attributes=[],
        export_amount=150_000_000,
        patents=4,
    )
    item = Item(
        name="AI 기반 공장 에너지 관리 시스템(FEMS) 고도화",
        summary="설비별 전력 데이터를 수집해 AI로 피크 부하를 예측·제어하는 중소 제조공장용 FEMS",
        issue="중소 제조공장은 전력 피크 관리 수단이 없어 기본요금과 탄소배출 부담이 큼",
        keywords=["에너지", "FEMS", "탄소중립", "스마트공장", "AI", "전력"],
        portfolio_type="Project",
        trl_current=4,
        trl_target=7,
        dev_period_months=24,
        budget_krw=600_000_000,
        staff_count=6,
        scope="데이터 수집 게이트웨이, 피크 예측 모델, 자동 부하 제어 모듈, 대시보드",
        priority=1,
        preferred_type="R&D",
    )
    item.indicators = [
        PerformanceIndicator(name="피크 전력 예측 정확도", unit="% (MAPE 기준 정확도)", measure_method="실증 공장 3개월 데이터 대비 MAPE", test_org="한국산업기술시험원(KTL)", baseline="85", target="95"),
        PerformanceIndicator(name="에너지 절감률", unit="%", measure_method="도입 전후 동일 생산량 기준 전력사용량 비교", test_org="한국에너지기술연구원 [확인 필요]", baseline="0", target="15"),
        PerformanceIndicator(name="제어 응답시간", unit="초", measure_method="제어명령~설비반영 시간 측정", test_org="KTL", baseline="10", target="2"),
    ]
    c.items = [item]
    c.prior_research = [
        PriorResearch(title="중소기업 에너지 모니터링 플랫폼 개발", type="국가R&D", period="2021.05~2022.12", result="TRL 4 달성, 실증 2개 공장", ip="특허 등록 2건", relevance="데이터 수집 모듈 재활용"),
        PriorResearch(title="설비 이상탐지 알고리즘 자체 개발", type="자체", period="2023.01~2023.12", result="이상탐지 정확도 92%", ip="특허 출원 1건", relevance="예측 모델 기반 기술"),
    ]
    today = date.today()
    c.documents = [
        Document(doc_type="사업자등록증", issued_date=date(2020, 3, 15)),
        Document(doc_type="기업부설연구소 인정서", issued_date=date(2020, 7, 1)),
        Document(doc_type="벤처기업확인서", issued_date=today - timedelta(days=700), expires_date=today + timedelta(days=20)),
        Document(doc_type="중소기업확인서", issued_date=today - timedelta(days=200), expires_date=today + timedelta(days=160)),
    ]
    session.add(c)
    session.flush()

    anns = [
        AnnouncementData(
            source="manual", source_id="sample-1",
            title="[샘플] 2026년 중소기업 탄소중립 에너지효율화 기술개발사업(R&D) 공고",
            agency="중소벤처기업부", exec_agency="중소기업기술정보진흥원",
            apply_start=today - timedelta(days=5), apply_end=today + timedelta(days=12),
            budget_text="과제당 최대 3억원 이내(최대 2년)",
            eligibility_text="중소기업기본법 제2조에 따른 중소기업, 기업부설연구소 또는 연구개발전담부서 보유 기업",
            summary="중소 제조기업의 에너지 효율화 및 탄소중립 기술개발 지원. FEMS, 에너지 관리, AI 기반 설비 최적화 등",
            region="전국", url="https://www.smtech.go.kr (샘플)",
        ),
        AnnouncementData(
            source="manual", source_id="sample-2",
            title="[샘플] 2026년 충청남도 스마트공장 솔루션 시제품 제작 지원사업",
            agency="충청남도", exec_agency="충남테크노파크",
            apply_start=today - timedelta(days=2), apply_end=today + timedelta(days=25),
            budget_text="기업당 최대 5,000만원",
            eligibility_text="공고일 기준 충청남도에 본사 또는 사업장을 둔 업력 7년 이내 중소기업",
            summary="스마트공장·에너지 솔루션 시제품 제작 및 실증 지원",
            region="충남", url="https://www.ctp.or.kr (샘플)",
        ),
        AnnouncementData(
            source="manual", source_id="sample-3",
            title="[샘플] 2026년 서울시 여성기업 판로개척 지원",
            agency="서울특별시", exec_agency="서울경제진흥원",
            apply_start=today - timedelta(days=10), apply_end=today + timedelta(days=5),
            budget_text="기업당 최대 2,000만원",
            eligibility_text="서울 소재 여성기업확인서 보유 기업",
            summary="국내외 전시회 참가 및 마케팅 지원",
            region="서울", url="https://www.sba.seoul.kr (샘플)",
        ),
    ]
    upsert_announcements(session, anns)
    by_title = {a.title: a for a in session.scalars(select(Announcement).where(Announcement.source_id.like("sample-%")))}
    rules = {
        anns[0].title: [("has_rnd_lab", "==", True, "기업부설연구소 또는 연구개발전담부서 보유 기업")],
        anns[1].title: [
            ("region_sido", "in", ["충남"], "공고일 기준 충청남도에 본사 또는 사업장을 둔"),
            ("years_in_business", "<=", 7, "업력 7년 이내 중소기업"),
        ],
        anns[2].title: [
            ("region_sido", "in", ["서울"], "서울 소재"),
            ("certification", "has_any", ["여성기업"], "여성기업확인서 보유 기업"),
        ],
    }
    for title, rs in rules.items():
        ann = by_title[title]
        for f, op, v, ev in rs:
            session.add(EligibilityRule(announcement_id=ann.id, field=f, operator=op, value=json.dumps(v, ensure_ascii=False), evidence_text=ev, verified=True))
    by_title[anns[0].title].raw_json = {"_llm_meta": {"dev_period_months": 24, "purpose_keywords": ["탄소중립", "에너지 효율", "FEMS"], "required_documents": ["사업자등록증", "기업부설연구소 인정서", "국세납세증명서", "중소기업확인서"]}}
    session.flush()
    return c


if __name__ == "__main__":
    with session_scope() as s:
        company = seed(s)
        print(f"샘플 기업 등록: {company.name} (id={company.id})")

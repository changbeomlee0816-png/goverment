# 작업: 공고 원문 → 자격요건 JSON 추출

<참고자료>의 공고 원문에서 신청 자격요건과 사업 개요를 추출한다. 원문에 없는 항목은 null로 둔다.

field 허용값과 operator:
- years_in_business (업력, 년): "<=", ">=", "between"(value=[min,max])
- region_sido (소재지 시·도): "in"(value=["서울","경기",...])
- revenue_krw (전년도 매출, 원): "<=", ">=", "between"
- employees (상시근로자 수): "<=", ">=", "between"
- industry (업종 키워드): "in" / "not_in"(value=["제조업",...])
- certification (필수 인증): "has_any" / "has_all"(value=["벤처","이노비즈",...])
- has_rnd_lab (기업부설연구소 보유): "==", value=true/false
- ceo_attribute (대표자 요건): "has_any"(value=["여성","청년"])
- trl (요구 TRL): "between"(value=[min,max])
- other: 규칙화할 수 없는 요건. operator "note"

출력 형식(JSON만):
```json
{
  "rules": [
    {"field": "years_in_business", "operator": "<=", "value": 7, "evidence_text": "공고일 기준 업력 7년 이내인 중소기업"}
  ],
  "category": "R&D|시제품|인증|판로|시험분석|멘토링|자금|교육|기타",
  "is_rnd": true,
  "support_amount_krw": 200000000,
  "dev_period_months": 24,
  "purpose_keywords": ["탄소중립", "에너지 효율"],
  "required_documents": ["사업자등록증", "재무제표"],
  "evidence": {"support_amount_krw": "과제당 최대 2억원 이내", "dev_period_months": "..."}
}
```
evidence_text는 반드시 원문 문장을 그대로 복사한다. 금액은 원 단위 정수.

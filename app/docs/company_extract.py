"""사업자등록증·재무제표 텍스트에서 기업정보 후보값 추출(사용자 확인 후 저장)."""
from __future__ import annotations

import re
from datetime import date

from app.collectors.base import normalize_region, parse_date


def extract_company_fields(text: str) -> dict:
    out: dict = {}
    m = re.search(r"(\d{3})\s*-\s*(\d{2})\s*-\s*(\d{5})", text)
    if m:
        out["biz_no"] = "-".join(m.groups())
    m = re.search(r"(법인명|상\s*호)\s*(\(단체명\))?\s*[:：]?\s*([^\n]+)", text)
    if m:
        out["name"] = m.group(3).strip()[:100]
    m = re.search(r"개\s*업\s*연\s*월\s*일\s*[:：]?\s*(\d{4})\s*[년.\-]\s*(\d{1,2})\s*[월.\-]\s*(\d{1,2})", text)
    if m:
        out["founded_date"] = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(사업장\s*소재지|본\s*점\s*소재지)\s*[:：]?\s*([^\n]+)", text)
    if m:
        region = normalize_region(m.group(2))
        if region:
            out["region_sido"] = region.split(",")[0]
        sgg = re.search(r"([가-힣]+[시군구])", m.group(2).split(" ", 1)[-1])
        if sgg:
            out["region_sigungu"] = sgg.group(1)
    m = re.search(r"종\s*목\s*[:：]?\s*([^\n]+)", text)
    if m:
        out["industry_name"] = m.group(1).strip()[:100]
    m = re.search(r"매\s*출\s*액\s*[:：]?\s*([\d,]+)", text)
    if m:
        try:
            out["revenue_last_year"] = int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return out


__all__ = ["extract_company_fields", "parse_date"]

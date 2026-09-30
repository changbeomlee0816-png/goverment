"""기업마당 지원사업정보 API 수집기.

GET https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do
파라미터: crtfcKey(인증키), dataType(json/rss), searchCnt, searchLclasId(분야), hashtags, pageUnit

※ 응답 필드명은 첫 실제 호출 스냅샷(data/snapshots/YYYYMMDD/bizinfo_*.json)으로 반드시 검증할 것.
  pick()에 후보 필드명을 여러 개 두어 필드명이 일부 바뀌어도 동작하게 했다.
"""
from __future__ import annotations

import logging

import requests

from app.collectors.base import AnnouncementData, parse_period, pick, save_snapshot, strip_html
from app.config import env

log = logging.getLogger(__name__)

API_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
BASE_URL = "https://www.bizinfo.go.kr"


class CollectorError(RuntimeError):
    pass


def fetch(search_cnt: int = 100, hashtags: str = "", lclas_id: str = "", timeout: int = 30) -> dict:
    key = env("BIZINFO_API_KEY")
    if not key:
        raise CollectorError("BIZINFO_API_KEY가 설정되지 않았습니다 (.env)")
    params = {"crtfcKey": key, "dataType": "json", "searchCnt": search_cnt}
    if hashtags:
        params["hashtags"] = hashtags
    if lclas_id:
        params["searchLclasId"] = lclas_id
    resp = requests.get(API_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and payload.get("reqErr"):
        raise CollectorError(f"기업마당 API 오류: {payload['reqErr']}")
    return payload


def records(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    for key in ("jsonArray", "items", "item", "data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            inner = records(value)
            if inner:
                return inner
    return []


def parse(payload) -> list[AnnouncementData]:
    out = []
    for r in records(payload):
        title = pick(r, "pblancNm", "title", "sj")
        if not title:
            continue
        start, end = parse_period(pick(r, "reqstBeginEndDe", "reqstDt", "applyPeriod"))
        url = pick(r, "pblancUrl", "link", "url")
        if url and url.startswith("/"):
            url = BASE_URL + url
        out.append(
            AnnouncementData(
                source="bizinfo",
                source_id=pick(r, "pblancId", "seq", "id"),
                title=strip_html(title),
                agency=pick(r, "jrsdInsttNm", "author", "insttNm"),
                exec_agency=pick(r, "excInsttNm", "excInsttNm"),
                apply_start=start,
                apply_end=end,
                summary=strip_html(pick(r, "bsnsSumryCn", "description", "sumry")),
                eligibility_text=strip_html(pick(r, "trgetNm", "target")),
                budget_text=strip_html(pick(r, "sportCn", "suportCn")),
                hashtags=pick(r, "hashTags", "hashtags"),
                region=pick(r, "areaNm", "region"),
                url=url,
                category_hint=pick(r, "pldirSportRealmLclasCodeNm", "lcategory", "category"),
                raw=r,
            )
        )
    return out


def collect(search_cnt: int = 100, hashtags: str = "") -> tuple[list[AnnouncementData], str]:
    payload = fetch(search_cnt=search_cnt, hashtags=hashtags)
    path = save_snapshot("bizinfo", payload)
    return parse(payload), str(path)

"""NTIS Open API — 국가R&D 과제 검색 (벤치마킹 참고용).

NTIS 로그인 → 회원정보에 소속기관 등록 → Open API 활용신청 후 발급받은 키를 NTIS_API_KEY에 넣는다.
결과는 '참고용'으로만 표시하고 아이템 정보에 자동 입력하지 않는다(REQUIREMENTS 4.2).

※ 엔드포인트·필드는 발급 후 1건 호출해 스냅샷으로 확인한 뒤 parse()를 맞출 것.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from app.collectors.base import save_snapshot
from app.collectors.bizinfo import CollectorError
from app.config import env

API_URL = "https://www.ntis.go.kr/rndopen/openApi/public_project"


def search_projects(query: str, count: int = 10, timeout: int = 30) -> list[dict]:
    key = env("NTIS_API_KEY")
    if not key:
        raise CollectorError("NTIS_API_KEY가 설정되지 않았습니다 (.env)")
    params = {"apprvKey": key, "collection": "project", "query": query, "displayCnt": count}
    resp = requests.get(API_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    save_snapshot("ntis_project", {"query": query, "raw": resp.text[:200000]})
    return parse(resp.text)


def parse(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise CollectorError("NTIS 응답을 해석하지 못했습니다") from exc
    out = []
    for hit in root.iter("HIT"):
        def text(tag):
            node = hit.find(tag)
            if node is None:
                return None
            return "".join(node.itertext()).strip() or None

        out.append(
            {
                "과제명": text("ProjectTitle/Korean") or text("ProjectTitle"),
                "연구기관": text("LeadAgency") or text("ResearchAgency/Name"),
                "연구기간": text("ProjectPeriod/TotalStart") or text("ProjectPeriod"),
                "연구목표": text("Goal/Full") or text("Goal"),
                "기대효과": text("Effect/Full") or text("Effect"),
                "키워드": text("Keyword/Korean") or text("Keyword"),
            }
        )
    return out

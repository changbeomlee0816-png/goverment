"""K-Startup 조회서비스 (공공데이터포털 15125364) 수집기.

사업공고: https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01
파라미터: serviceKey, page, perPage, returnType=json

※ 응답 필드명은 첫 실제 호출 스냅샷으로 검증할 것(pick()에 후보 키를 둠).
"""
from __future__ import annotations

import requests

from app.collectors.base import AnnouncementData, parse_date, pick, save_snapshot, strip_html
from app.collectors.bizinfo import CollectorError
from app.config import env

API_URL = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"


def fetch(page: int = 1, per_page: int = 100, timeout: int = 30) -> dict:
    key = env("DATA_GO_KR_KEY")
    if not key:
        raise CollectorError("DATA_GO_KR_KEY가 설정되지 않았습니다 (.env)")
    params = {"serviceKey": key, "page": page, "perPage": per_page, "returnType": "json"}
    resp = requests.get(API_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    try:
        payload = resp.json()
    except ValueError as exc:
        raise CollectorError("K-Startup 응답이 JSON이 아닙니다 (서비스키/승인 상태 확인)") from exc
    header = payload.get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader") if isinstance(payload, dict) else None
    if header:
        raise CollectorError(f"K-Startup API 오류: {header.get('errMsg')} / {header.get('returnAuthMsg')}")
    return payload


def records(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    for key in ("data", "items", "item", "body", "response"):
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
        title = pick(r, "biz_pbanc_nm", "intg_pbanc_biz_nm", "pbanc_nm", "title")
        if not title:
            continue
        recruiting = pick(r, "rcrt_prgs_yn")
        out.append(
            AnnouncementData(
                source="kstartup",
                source_id=str(pick(r, "pbanc_sn", "id", default="")) or None,
                title=strip_html(title),
                agency=pick(r, "sprv_inst", "pbanc_ntrp_nm"),
                exec_agency=pick(r, "pbanc_ntrp_nm", "biz_prch_dprt_nm"),
                apply_start=parse_date(pick(r, "pbanc_rcpt_bgng_dt", "rcpt_bgng_dt")),
                apply_end=parse_date(pick(r, "pbanc_rcpt_end_dt", "rcpt_end_dt")),
                summary=strip_html(pick(r, "pbanc_ctnt", "biz_pbanc_ctnt")),
                eligibility_text=strip_html(
                    " / ".join(
                        filter(None, [pick(r, "aply_trgt_ctnt"), pick(r, "aply_trgt"), pick(r, "biz_enyy"), pick(r, "biz_trgt_age")])
                    )
                ),
                region=pick(r, "supt_regin"),
                url=pick(r, "detl_pg_url", "biz_aply_url", "url"),
                category_hint=pick(r, "supt_biz_clsfc"),
                raw={**r, "_recruiting": recruiting},
            )
        )
    return out


def collect(per_page: int = 100, pages: int = 2) -> tuple[list[AnnouncementData], list[str]]:
    items, paths = [], []
    for page in range(1, pages + 1):
        payload = fetch(page=page, per_page=per_page)
        paths.append(str(save_snapshot(f"kstartup_p{page}", payload)))
        parsed = parse(payload)
        items.extend(parsed)
        if len(parsed) < per_page:
            break
    return items, paths

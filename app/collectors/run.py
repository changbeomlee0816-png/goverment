"""공고 수집 배치 (CLI).

    python -m app.collectors.run              # 1회 수집
    python -m app.collectors.run --schedule   # 설정된 주기(collect.interval_hours)마다 반복 수집
    python -m app.collectors.run --extract    # 수집 후 신규 공고 자격요건 추출까지

cron 예시(매일 06:10): 10 6 * * * cd /path/to/goverment && python -m app.collectors.run --extract
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime

from sqlalchemy import select

from app.collectors import bizinfo, kstartup
from app.collectors.bizinfo import CollectorError
from app.collectors.base import upsert_announcements
from app.collectors.eligibility import extract_for_announcement
from app.config import load_settings
from app.db.models import Announcement
from app.db.session import session_scope

log = logging.getLogger("collector")


def collect_once(extract: bool = False) -> list[dict]:
    """각 소스를 수집해 DB에 반영. 소스별 결과 요약 리스트를 반환(오류는 결과에 기록하고 계속)."""
    settings = load_settings()["collect"]
    results = []
    started = datetime.now()
    for source in settings.get("sources", []):
        try:
            if source == "bizinfo":
                cfg = settings.get("bizinfo", {})
                items, snap = bizinfo.collect(cfg.get("searchCnt", 100), cfg.get("hashtags", ""))
                snaps = [snap]
            elif source == "kstartup":
                cfg = settings.get("kstartup", {})
                items, snaps = kstartup.collect(cfg.get("perPage", 100), cfg.get("pages", 2))
            else:
                results.append({"source": source, "ok": False, "error": "알 수 없는 소스"})
                continue
            with session_scope() as session:
                created, updated = upsert_announcements(session, items)
            results.append({"source": source, "ok": True, "fetched": len(items), "created": created, "updated": updated, "snapshots": snaps})
        except (CollectorError, OSError, ValueError) as exc:
            # requests 예외도 OSError 계열. 키 값이 섞일 수 있는 URL은 기록하지 않는다.
            results.append({"source": source, "ok": False, "error": str(exc).split("?")[0]})
    if extract:
        with session_scope() as session:
            fresh = session.scalars(
                select(Announcement).where(Announcement.collected_at >= started)
            ).all()
            for ann in fresh:
                if not ann.rules:
                    try:
                        extract_for_announcement(session, ann)
                    except Exception as exc:  # noqa: BLE001 - 한 건 실패로 배치 중단하지 않음
                        log.warning("자격요건 추출 실패 id=%s: %s", ann.id, exc)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="정부지원사업 공고 수집")
    parser.add_argument("--schedule", action="store_true", help="주기적으로 반복 수집")
    parser.add_argument("--extract", action="store_true", help="신규 공고 자격요건 추출")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    while True:
        for r in collect_once(extract=args.extract):
            log.info("%s", r)
        if not args.schedule:
            break
        hours = float(load_settings()["collect"].get("interval_hours", 24))
        log.info("다음 수집까지 %.1f시간 대기", hours)
        time.sleep(hours * 3600)


if __name__ == "__main__":
    main()

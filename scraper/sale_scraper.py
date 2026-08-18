"""買屋（中古屋）抓取：逐區查詢 sale.591，取 __NUXT__ JSON，程式端過濾。

重用租屋的 HTTP/SSL/merge 邏輯（list_scraper），只是換 URL 組法與解析器。
買屋單區 firstRow=0 一次通常已涵蓋（篩選後多在 30 筆內）。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

import config
import filters
from scraper.list_scraper import _build_ssl_context, fetch_list_html, merge_listings
from scraper.sale_parser import parse_sale_html
from scraper.sale_url_builder import build_sale_url

log = logging.getLogger(__name__)


def scrape_sale_subscription(
    sub: dict,
    fetched_at: datetime | None = None,
    client: httpx.Client | None = None,
) -> tuple[list[dict], set | None]:
    """抓一筆買屋訂閱，回傳 (物件清單, 已涵蓋行政區集合或 None)。"""
    fetched_at = fetched_at or datetime.now(timezone.utc)
    region_name = config.REGION_NAMES.get(str(sub["region"]))
    section_map = config.SECTION_NAMES.get(str(sub["region"]), {})
    sections = sub.get("sections") or [None]
    region_wide = not sub.get("sections")

    own = client is None
    if own:
        client = httpx.Client(
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"},
            follow_redirects=True, verify=_build_ssl_context(),
        )

    covered: set = set()
    batches: list[list[dict]] = []
    first = True
    try:
        for section in sections:
            if not first:
                time.sleep(config.REQUEST_INTERVAL_SEC)
            first = False
            url = build_sale_url(sub, section=section, first_row=0)
            html = fetch_list_html(url, client)
            if not html:
                continue  # 被擋：此區未涵蓋
            if section is not None:
                covered.add(str(section))
            parsed = parse_sale_html(html, fetched_at=fetched_at)
            rows = [r for r in parsed if filters.matches_sale(r, sub)]
            batches.append(rows)
            running = merge_listings(sub, batches, region_name)
            log.info("[%s] sec=%s → 符合 %d/%d 筆（聯集累計 %d）",
                     sub["id"], section, len(rows), len(parsed), len(running))
    finally:
        if own:
            client.close()

    merged = merge_listings(sub, batches, region_name)
    covered_districts = None if region_wide else {section_map[s] for s in covered if s in section_map}
    log.info("[%s] 完成，聯集共 %d 筆（涵蓋區：%s）",
             sub["id"], len(merged), "全區" if covered_districts is None else "、".join(sorted(covered_districts)) or "無")
    return merged, covered_districts

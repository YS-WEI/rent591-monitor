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
from scraper.nuxt import extract_page
from scraper.sale_parser import listings_from_sale_json
from scraper.sale_url_builder import build_sale_url

log = logging.getLogger(__name__)

PAGE_SIZE = 30       # 591 每頁筆數（firstRow 以此遞增）
MAX_PAGES = 10       # 每區最多翻幾頁（封頂避免請求爆量）


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
            seen: set = set()          # 該區已見過的 houseid（判斷是否還有新頁）
            total = None
            matched = 0
            for page in range(MAX_PAGES):
                # 不翻過首頁回報的 total：591 對超過筆數的 firstRow 會回「另一組」資料
                if page > 0 and total is not None and page * PAGE_SIZE >= total:
                    break
                if not first:
                    time.sleep(config.REQUEST_INTERVAL_SEC)
                first = False
                url = build_sale_url(sub, section=section, first_row=page * PAGE_SIZE)
                html = fetch_list_html(url, client)
                if not html:
                    break  # 被擋/失敗
                if section is not None:
                    covered.add(str(section))
                pg = extract_page(html)
                items = pg["items"]
                if total is None:
                    total = pg["total"]
                if not items:
                    break
                new_ids = {str(it.get("houseid")) for it in items} - seen
                if not new_ids:
                    break  # 這頁沒有新物件（591 已重複），停止翻頁
                seen |= new_ids
                rows = [r for r in listings_from_sale_json(items, fetched_at)
                        if filters.matches_sale(r, sub)]
                batches.append(rows)
                matched += len(rows)
                if total is not None and len(seen) >= total:
                    break  # 已涵蓋官方總數
            running = merge_listings(sub, batches, region_name)
            note = "（591 分頁重排，未完全涵蓋）" if total and len(seen) < total else ""
            log.info("[%s] sec=%s → 抓過 %d/%s、符合累計 %d%s",
                     sub["id"], section, len(seen), total, len(running), note)
    finally:
        if own:
            client.close()

    merged = merge_listings(sub, batches, region_name)
    covered_districts = None if region_wide else {section_map[s] for s in covered if s in section_map}
    log.info("[%s] 完成，聯集共 %d 筆（涵蓋區：%s）",
             sub["id"], len(merged), "全區" if covered_districts is None else "、".join(sorted(covered_districts)) or "無")
    return merged, covered_districts

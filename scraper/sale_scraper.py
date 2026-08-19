"""買屋（中古屋）抓取：直接打 591 買屋 BFF JSON API，逐區 + firstRow 分頁。

重用租屋的 HTTP/SSL/merge 邏輯（list_scraper）；資料源改為 bff-house 的 JSON
（data.house_list / data.total），比抓 HTML+eval 乾淨，且 total 準確。
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import httpx

import config
import filters
from scraper.list_scraper import _build_ssl_context, fetch_list_html, merge_listings
from scraper.sale_parser import dedupe_sale_units, listings_from_sale_json
from scraper.sale_url_builder import build_sale_url

log = logging.getLogger(__name__)

PAGE_SIZE = 30       # 591 每頁筆數（firstRow 以此遞增）
MAX_PAGES = 10       # 每區最多翻幾頁（封頂避免請求爆量）
# BFF 對機房 IP 冷啟動會連續 403，需靠退避熬過冷卻窗口。實測第 5 次（累計 ~60s）
# 才放行，故多留幾次（退避 …64→128，累計 ~4 分）確保突破；一旦有一枪 200，
# 同一 session 後續分頁即全部放行，不再付這個成本。
COLD_START_RETRIES = 6
WARMUP_URL = "https://sale.591.com.tw/"  # 先載主站（未被 IP 擋）取得 cookie，再打 BFF


def _fetch_page(url: str, client: httpx.Client, max_retries: int | None = None) -> tuple[list, int | None]:
    """打 BFF API 回傳 (house_list, total)；失敗回 ([], None)。"""
    text = fetch_list_html(url, client, max_retries=max_retries)  # 沿用其重試/退避；回傳字串
    if not text:
        return [], None
    try:
        data = json.loads(text).get("data") or {}
    except Exception:  # noqa: BLE001
        return [], None
    total = data.get("total")
    total = int(total) if str(total).isdigit() else None
    return (data.get("house_list") or []), total


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
            headers={"User-Agent": config.USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9",
                     "Accept": "application/json", "Referer": "https://sale.591.com.tw/"},
            follow_redirects=True, verify=_build_ssl_context(),
        )
        # 暖機：先載主站取得 cookie（webp/urlJumpIp/T591_TOKEN），模仿瀏覽器「先載頁再打 API」，
        # 降低 BFF 冷啟動 403 機率。主站本身也會對機房 IP 冷啟動 403，故走 fetch_list_html
        # 的指數退避重試（會 raise_for_status，403 才算失敗）；重試後仍失敗就略過，續靠 BFF 自身重試。
        if fetch_list_html(WARMUP_URL, client, max_retries=COLD_START_RETRIES) is None:
            log.warning("暖機請求重試後仍失敗（略過，續打 BFF）：%s", WARMUP_URL)

    covered: set = set()
    batches: list[list[dict]] = []
    first = True
    try:
        for section in sections:
            seen: set = set()          # 該區已見過的 houseid（去重＝實際量，不信 591 的 total）
            total = None               # 只用來擋「翻過頭」：firstRow 超過 total 會回一組雜資料
            ts = int(time.time() * 1000)  # 同一區各分頁共用 timestamp（定格、頁間重疊少）
            for page in range(MAX_PAGES):
                if page > 0 and total is not None and page * PAGE_SIZE >= total:
                    break
                if not first:
                    time.sleep(config.REQUEST_INTERVAL_SEC)
                first = False
                url = build_sale_url(sub, section=section, first_row=page * PAGE_SIZE, timestamp=ts)
                # 每區第一枪多給幾次重試熬過冷啟動 403；破關後同 session 後續分頁走預設即可
                retries = COLD_START_RETRIES if page == 0 else None
                items, page_total = _fetch_page(url, client, max_retries=retries)
                if total is None:
                    total = page_total
                if not items:
                    break  # 被擋/失敗/翻到底
                if section is not None:
                    covered.add(str(section))
                new_ids = {str(it.get("houseid")) for it in items} - seen
                if not new_ids:
                    break  # 這頁全是看過的（591 重排重複）→ 停止翻頁
                seen |= new_ids
                rows = [r for r in listings_from_sale_json(items, fetched_at)
                        if filters.matches_sale(r, sub)]
                batches.append(rows)
            running = merge_listings(sub, batches, region_name)
            log.info("[%s] sec=%s → 抓過 %d 筆（591 report total=%s，不採信）、符合累計 %d",
                     sub["id"], section, len(seen), total, len(running))
    finally:
        if own:
            client.close()

    merged = merge_listings(sub, batches, region_name)
    deduped = dedupe_sale_units(merged)
    if len(deduped) != len(merged):
        log.info("[%s] 同案去重 + 濾死連結：%d → %d 筆", sub["id"], len(merged), len(deduped))
    covered_districts = None if region_wide else {section_map[s] for s in covered if s in section_map}
    log.info("[%s] 完成，共 %d 筆（涵蓋區：%s）",
             sub["id"], len(deduped), "全區" if covered_districts is None else "、".join(sorted(covered_districts)) or "無")
    return deduped, covered_districts

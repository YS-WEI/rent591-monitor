"""列表頁抓取：逐區 + firstRow 分頁。

列表資料取自 __NUXT__ 的結構化 JSON（見 scraper/nuxt.py）。每個 section 用 firstRow
分頁抓到官方總數（total）或無新頁為止，以 listing_id 去重。

反爬：請求間隔 ≥ 4 秒、帶正常 UA、失敗重試後跳過（不中斷整輪）。
"""
from __future__ import annotations

import logging
import ssl
import time
from datetime import datetime

import certifi
import httpx

import config
import filters
from scraper.list_parser import listings_from_json
from scraper.nuxt import extract_page
from scraper.url_builder import build_list_url

log = logging.getLogger(__name__)

PAGE_SIZE = 30       # 591 每頁筆數（firstRow 遞增量）
MAX_PAGES = 10       # 每區最多翻幾頁（封頂避免請求爆量）


def _build_ssl_context() -> ssl.SSLContext:
    """完整驗證憑證鏈與主機名，但關閉 OpenSSL 3.6+ 預設的 X509_STRICT。

    591 的憑證鏈缺 Subject Key Identifier 擴充，會被嚴格模式拒絕；
    此處僅放寬該 RFC 5280 擴充檢查，不影響鏈結與主機名驗證。
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def fetch_list_html(url: str, client: httpx.Client) -> str | None:
    """抓單一列表頁 HTML；失敗重試 config.MAX_RETRIES 次後回 None（不拋出）。"""
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = client.get(url, timeout=config.REQUEST_TIMEOUT_SEC)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001 — 任何失敗都應可跳過重試
            if attempt < config.MAX_RETRIES:
                backoff = config.REQUEST_INTERVAL_SEC * (2 ** attempt)  # 指數退避 4→8→16→32
                log.warning("抓取失敗（第 %d 次重試，等 %ds）：%s", attempt + 1, backoff, exc)
                time.sleep(backoff)
                continue
            log.error("抓取放棄：%s（%s）", url, exc)
            return None


def merge_listings(sub: dict, batches: list[list[dict]], region_name: str | None) -> list[dict]:
    """把多次抓取的結果以 listing_id 取聯集去重，並補上訂閱/城市資訊。

    純函式，方便測試。先出現者為準（保留較早排序批次的欄位）。
    """
    merged: dict[str, dict] = {}
    for rows in batches:
        for row in rows:
            lid = row["listing_id"]
            if lid in merged:
                continue
            row = {**row, "subscription_id": sub["id"], "region": region_name}
            merged[lid] = row
    return list(merged.values())


def scrape_subscription(
    sub: dict,
    sorts: list[str] | None = None,
    fetched_at: datetime | None = None,
    client: httpx.Client | None = None,
) -> list[dict]:
    """抓取單一訂閱（逐區 + 多排序聯集），回傳 (物件清單, 已涵蓋的行政區集合)。

    「已涵蓋」= 該區這輪成功抓到（HTTP 有回應）。被擋（403 重試後仍失敗）的區
    不列入，供上層判斷「這區沒抓到就別動它的資料」。
    無 sections 的（全區）訂閱回傳 covered=None，代表視為全部涵蓋。

    每次請求之間間隔 config.REQUEST_INTERVAL_SEC 秒。
    可注入 httpx.Client（測試用）；未提供則自建。
    """
    sorts = sorts or config.SECTION_SORTS
    fetched_at = fetched_at or datetime.now()
    region_name = config.REGION_NAMES.get(str(sub["region"]))

    own_client = client is None
    if own_client:
        client = httpx.Client(
            headers={
                "User-Agent": config.USER_AGENT,
                "Accept-Language": "zh-TW,zh;q=0.9",
            },
            follow_redirects=True,
            verify=_build_ssl_context(),
        )

    # 逐區查詢：每個 section 各自查（避免多區共用 SSR 的 ~30 筆名額而漏抓）
    section_map = config.SECTION_NAMES.get(str(sub["region"]), {})
    sections = sub.get("sections") or [None]
    region_wide = not sub.get("sections")
    covered_sections: set = set()
    batches: list[list[dict]] = []
    first = True
    sort = (sorts[0] if sorts else None) or sub.get("sort") or "posttime_desc"
    try:
        for section in sections:
            sub_one = sub if section is None else {**sub, "sections": [section]}
            seen: set = set()
            total = None
            for page in range(MAX_PAGES):
                # 不翻過首頁回報的 total：591 對超過筆數的 firstRow 會回「另一組」資料
                if page > 0 and total is not None and page * PAGE_SIZE >= total:
                    break
                if not first:
                    time.sleep(config.REQUEST_INTERVAL_SEC)
                first = False
                url = build_list_url(sub_one, sort=sort, first_row=page * PAGE_SIZE)
                html = fetch_list_html(url, client)
                if not html:
                    break  # 被擋/失敗：此 section 未涵蓋，不加入 covered
                if section is not None:
                    covered_sections.add(str(section))
                pg = extract_page(html)
                items = pg["items"]
                if total is None:
                    total = pg["total"]
                if not items:
                    if page == 0 and total == 0:
                        log.info("[%s] sec=%s → 此區無符合條件（total=0）", sub["id"], section)
                    elif page == 0:
                        import re as _re
                        m = _re.search(r"<title>([^<]*)</title>", html)
                        log.warning("[%s] sec=%s → 0 筆（HTML %d bytes，title=%r）疑似反爬",
                                    sub["id"], section, len(html), (m.group(1) if m else "?"))
                    break
                new_ids = {str(it.get("id")) for it in items} - seen
                if not new_ids:
                    break  # 這頁沒有新物件（591 已重複），停止翻頁
                seen |= new_ids
                # 591 SSR 未套用房數/坪數等篩選，於程式端過濾
                rows = [r for r in listings_from_json(items, fetched_at) if filters.matches(r, sub)]
                batches.append(rows)
                if total is not None and len(seen) >= total:
                    break
            running = merge_listings(sub, batches, region_name)
            note = "（591 分頁重排，未完全涵蓋）" if total and len(seen) < total else ""
            log.info("[%s] sec=%s → 抓過 %d/%s、符合累計 %d%s",
                     sub["id"], section, len(seen), total, len(running), note)
    finally:
        if own_client:
            client.close()

    merged = merge_listings(sub, batches, region_name)
    if region_wide:
        covered = None  # 全區訂閱無法逐區判斷，視為全部涵蓋
    else:
        covered = {section_map[s] for s in covered_sections if s in section_map}
    log.info("[%s] 完成，聯集共 %d 筆（涵蓋區：%s）",
             sub["id"], len(merged), "全區" if covered is None else "、".join(sorted(covered)) or "無")
    return merged, covered

"""住商不動產租屋：沿用同一份租屋訂閱，抓取並轉成與 591 相同的物件 schema。

實測（2026-11）：
- https://www.hbhousing.com.tw/renthouse/<路徑> 為 Nuxt 3 SSR，物件放在頁面的
  <script id="__NUXT_DATA__">（devalue 格式：扁平陣列，物件的值是指向陣列的索引）。
- 篩選寫在路徑片段、伺服器端套用（順序比照住商前端）：城市/郵遞區號/型態(style)/
  租金(price，單位「萬」)/類型(type)/坪數(area)/房數(pattern)；路徑尾加 `N-page` 翻頁，每頁 10 筆。
- 範圍格式：`a-b`、`a-up`、`b-down`；房數片段把 `-` 換成 `_`（`4_up_room-pattern`）。
- 抓回後一律再用 filters.matches 依訂閱精篩。卡片無管理費 → total_monthly 暫等於租金。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from urllib.parse import quote

import httpx

import config
import filters
from scraper.list_scraper import _build_ssl_context, fetch_list_html
from scraper.sinyi_scraper import _split_address

log = logging.getLogger(__name__)

SOURCE = "hb"
ID_PREFIX = "hb-"  # 住商 sn 有 ZR/OR/gOT/C… 等開頭，加前綴避免與信義 C 開頭 ID 撞號
_WRAPPERS = ("Reactive", "ShallowReactive", "Ref", "ShallowRef")


def _num(v: float) -> str:
    """數字轉路徑字串：5.0 → '5'、1.5 → '1.5'。"""
    return f"{v:g}"


def _range(lo, hi) -> str:
    """住商前端的 rt()：兩端皆空回空字串；單邊用 -up / -down；相等只寫一個值。"""
    if lo is None and hi is None:
        return ""
    if lo is None:
        return f"{_num(hi)}-down"
    if hi is None:
        return f"{_num(lo)}-up"
    return _num(lo) if lo == hi else f"{_num(lo)}-{_num(hi)}"


def build_hb_path(sub: dict, page: int = 1) -> str | None:
    """訂閱 → 住商搜尋路徑（未 URL encode）。城市不支援時回 None。純函式。"""
    region = str(sub["region"])
    city = config.HB_CITY.get(region)
    if not city:
        return None
    segs = [city]

    zips = [config.SECTION_ZIP.get(region, {}).get(str(s)) for s in (sub.get("sections") or [])]
    zips = [z for z in zips if z]
    if zips:
        segs.append("-".join(zips))

    styles = {k for s in (sub.get("shape") or []) for k in config.HB_STYLE.get(str(s), [])}
    if styles:
        segs.append("-".join(k for k in config.HB_STYLE_ORDER if k in styles) + "-style")

    lo, hi = sub.get("price_min"), sub.get("price_max")
    price = _range(None if lo is None else lo / 10000, None if hi is None else hi / 10000)
    if price:
        segs.append(f"{price}-price")

    hb_type = config.HB_TYPE.get(str(sub.get("kind") or ""))
    if hb_type:
        segs.append(f"{hb_type}-type")

    area = _range(sub.get("acreage_min"), sub.get("acreage_max"))
    if area:
        segs.append(f"area-{area}-area")

    layout = [int(x) for x in (sub.get("layout") or [])]
    if layout:
        # 591 的 4 代表「4 房以上」；其餘精確值交給 filters 精篩
        room = _range(min(layout), None if max(layout) >= 4 else max(layout))
        segs.append(f"{room}-room".replace("-", "_") + "-pattern")

    if page > 1:
        segs.append(f"{page}-page")
    return "/".join(segs)


def extract_items(html: str) -> list[dict]:
    """從 HTML 的 __NUXT_DATA__ 取出物件 dict 清單（純函式）。找不到資料回空清單。"""
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    arr = json.loads(m.group(1))

    def res(v, depth=0):
        if isinstance(v, int) and not isinstance(v, bool):
            v = arr[v]
        if depth > 6:
            return None
        if isinstance(v, dict):
            return {k: res(x, depth + 1) for k, x in v.items()}
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in _WRAPPERS:
                return res(v[1], depth + 1)
            return [res(x, depth + 1) for x in v]
        return v

    return [res(x) for x in arr if isinstance(x, dict) and "sn" in x and "objName" in x]


def listing_from_item(o: dict, sub: dict, fetched_at: datetime) -> dict:
    """住商的一筆 → 與 591 相同的物件 dict（純對應）。"""
    sn = str(o["sn"])
    fetched_iso = fetched_at.date().isoformat()
    district, street = _split_address(o.get("doorplate") or "")
    rent = o.get("rentPrice")
    price = round(float(rent) * 10000) if rent not in (None, "") else None  # 單位：萬 → 元
    area = o.get("area")
    mod = o.get("modifiedDate")
    return {
        "listing_id": ID_PREFIX + sn,
        "source": SOURCE,
        "title": o.get("objName"),
        "url": config.HB_DETAIL_URL + sn,
        "image": o.get("photo1") or None,
        "region": config.REGION_NAMES.get(str(sub["region"])),
        "district": district,
        "street": street,
        "community": None,
        # 類型已由伺服器端 type 篩過；訂閱沒指定類型時無從得知，留 None
        "kind_name": config.KIND_NAMES.get(str(sub.get("kind") or "")),
        "rooms": o.get("room"), "halls": o.get("hall"), "baths": o.get("bath"),
        "size_ping": float(area) if area not in (None, "") else None,
        "floor": o.get("floor") or None, "total_floor": o.get("floorTotal") or None,
        "price": price,
        "extra_fee": 0,
        "fee_included": [],
        "total_monthly": price,
        "tags": [t for t in [o.get("mrt"), o.get("style")] if t],
        "poster_type": "住商不動產", "poster_name": None,
        "updated_rel": None,
        "posted_at": (str(mod)[:10].replace("/", "-") if mod else None),
        "first_seen": fetched_iso, "last_seen": fetched_iso,
        "status": "active",
        "subscription_id": sub["id"],
    }


def scrape_hb_subscription(sub: dict, fetched_at: datetime | None = None,
                           client: httpx.Client | None = None) -> tuple[list[dict], set]:
    """抓單一訂閱的住商物件，回傳 (物件清單, 已涵蓋行政區集合)。

    涵蓋全有或全無（所有區在同一查詢）：任一頁抓取失敗 → 空集合，上層不判住商物件下架。
    翻頁停止條件：該頁不足 10 筆、或沒有新物件（防止超出頁數時回到重複資料）。
    """
    fetched_at = fetched_at or datetime.now()
    if not build_hb_path(sub):
        return [], set()

    own = client is None
    if own:
        client = httpx.Client(headers={"User-Agent": config.USER_AGENT,
                                       "Accept-Language": "zh-TW,zh;q=0.9"},
                              follow_redirects=True, verify=_build_ssl_context())
    rows: dict[str, dict] = {}
    seen: set = set()
    covered: set = set()
    try:
        for page in range(1, config.HB_MAX_PAGES + 1):
            if page > 1:
                time.sleep(config.REQUEST_INTERVAL_SEC)
            html = fetch_list_html(config.HB_LIST_URL + quote(build_hb_path(sub, page)), client)
            if html is None:
                covered = set()  # 有頁沒抓到：那頁物件會「看似消失」，整輪視為未涵蓋
                break
            if page == 1:
                names = config.SECTION_NAMES.get(str(sub["region"]), {})
                secs = sub.get("sections") or list(names)
                covered = {names[str(s)] for s in secs if str(s) in names}
            items = extract_items(html)
            new = [o for o in items if str(o["sn"]) not in seen]
            seen |= {str(o["sn"]) for o in items}
            for o in new:
                row = listing_from_item(o, sub, fetched_at)
                if filters.matches(row, sub):
                    rows[row["listing_id"]] = row
            if len(items) < config.HB_PAGE_SIZE or not new:
                break
    finally:
        if own:
            client.close()
    log.info("[住商][%s] 伺服器 %d 筆，符合訂閱 %d 筆（%s）", sub["id"], len(seen), len(rows), build_hb_path(sub))
    return list(rows.values()), covered

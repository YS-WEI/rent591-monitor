"""信義房屋租屋：沿用同一份租屋訂閱，抓取並轉成與 591 相同的物件 schema。

實測（2026-11）：
- 列表頁 https://www.sinyi.com.tw/rent/list/<路徑>/index.html 只有 SSR 第一頁，
  網址加 `N-page` 不會翻頁；資料其實由前端 POST `ajaxSearchHouse.php`
  （params=路徑, page, limit）取得 JSON，含 total/totalPage，翻頁正常。
- 篩選寫在路徑片段，伺服器端會套用：郵遞區號(zip)、用途(use)、租金(price)、
  N 房以上(room)、N 坪以上(area)、型態(type)。
- 信義的篩選較粗（房數只有「N 房以上」、坪數只有下限），抓回後一律再用
  filters.matches 依訂閱條件精篩（房數精確值、租金與坪數上下限、類型）。
- 卡片沒有管理費資訊，total_monthly 暫以租金計（extra_fee=0）。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime

import httpx

import config
import filters
from scraper.list_parser import _parse_floor, _parse_money
from scraper.list_scraper import _build_ssl_context

log = logging.getLogger(__name__)

SOURCE = "sinyi"
# 與信義前端相同的回傳欄位清單
RETURN_PARAMS = ("NO,name,description,address,areaLand,areaBuilding,areaBuildingMain,areaBalcony,"
                 "price,priceFirst,discount,type,use,room,hall,bathroom,openroom,roomplus,hallplus,"
                 "bathroomplus,openroomplus,age,floor,inc,imgCount,imgDefault,bigImg,staffpick,decoar,"
                 "pingratesup,community,lift,parking,customize,keyword,zipcode,tags,tagsSpecial,source")
# 友善標記 → 標籤文字
FLAG_TAGS = {"rentAid": "可租補", "houseReg": "可設籍", "student": "歡迎學生",
             "youth": "歡迎青年", "seniors": "歡迎長者"}


def build_sinyi_path(sub: dict) -> str | None:
    """訂閱 → 信義搜尋路徑。城市不支援時回 None（略過此訂閱）。

    純函式。信義只有「N 房以上 / N 坪以上」，故房數取訂閱最小值、坪數只送下限，
    其餘精確條件交給 filters.matches 在程式端處理。
    """
    region = str(sub["region"])
    city = config.SINYI_CITY.get(region)
    if not city:
        return None
    segs = [city]

    zips = [config.SECTION_ZIP.get(region, {}).get(str(s)) for s in (sub.get("sections") or [])]
    zips = [z for z in zips if z]
    if zips:
        segs.append("-".join(zips) + "-zip")

    use = config.SINYI_USE.get(str(sub.get("kind") or ""))
    if use:
        segs.append(f"{use}-use")

    lo, hi = sub.get("price_min"), sub.get("price_max")
    if hi is not None:
        segs.append(f"{int(lo or 0)}-{int(hi)}-price")
    elif lo is not None:
        segs.append(f"{int(lo)}-up-price")

    layout = [int(x) for x in (sub.get("layout") or [])]
    if layout:
        segs.append(f"{min(layout)}-up-room")

    if sub.get("acreage_min") is not None:
        segs.append(f"{int(sub['acreage_min'])}-up-area")

    types = sorted({config.SINYI_TYPE[str(s)] for s in (sub.get("shape") or [])
                    if str(s) in config.SINYI_TYPE})
    if types:
        segs.append("-".join(types) + "-type")

    return "/".join(segs)


def _split_address(addr: str) -> tuple[str | None, str | None]:
    """'新北市蘆洲區九芎街' → ('蘆洲區', '九芎街')。"""
    m = re.match(r"^(?:..[市縣])?(\S{1,3}?區)(.*)$", addr or "")
    if not m:
        return None, (addr or None)
    return m.group(1), (m.group(2).strip() or None)


def listing_from_api(r: dict, sub: dict, fetched_at: datetime) -> dict:
    """信義 API 的一筆 → 與 591 相同的物件 dict（純對應）。"""
    lid = str(r["NO"])
    fetched_iso = fetched_at.date().isoformat()
    # address 可能帶社區名（'成功座標   /   新北市土城區金安街'）；addressrwd 為純地址
    addr = r.get("addressrwd") or (r.get("address") or "").split("/")[-1].strip()
    district, street = _split_address(addr)
    price = _parse_money(r.get("price"))
    floor, total_floor = _parse_floor(r.get("floor") or "")
    try:
        size = float(r.get("ping")) if r.get("ping") not in (None, "") else None
    except ValueError:
        size = None
    upd = (r.get("updatedate") or "")[:10].replace("/", "-") or None
    return {
        "listing_id": lid,
        "source": SOURCE,
        "title": r.get("name"),
        "url": config.SINYI_HOUSE_URL + lid,
        "image": r.get("img") or None,
        "region": config.REGION_NAMES.get(str(sub["region"])),
        "district": district,
        "street": street,
        "community": r.get("community") or None,
        # 用途已由伺服器端 use 篩過；訂閱沒指定類型時無從得知，留 None
        "kind_name": config.KIND_NAMES.get(str(sub.get("kind") or "")),
        "rooms": r.get("room"), "halls": r.get("hall"), "baths": r.get("bathroom"),
        "size_ping": size,
        "floor": floor, "total_floor": total_floor,
        "price": price,
        "extra_fee": 0,
        "fee_included": [],
        "total_monthly": price,
        "tags": [t for k, t in FLAG_TAGS.items() if r.get(k) == "Y"],
        "poster_type": "信義房屋", "poster_name": None,
        "updated_rel": r.get("updatedate"),
        "posted_at": upd,  # 信義給的是絕對更新時間，比 591 的相對時間準
        "first_seen": fetched_iso, "last_seen": fetched_iso,
        "status": "active",
        "subscription_id": sub["id"],
    }


def _post_page(client: httpx.Client, path: str, page: int) -> dict | None:
    """抓一頁；失敗重試後回 None（不拋出）。"""
    data = {"params": path, "page": str(page), "limit": str(config.SINYI_PAGE_SIZE),
            "returnParams": RETURN_PARAMS}
    referer = f"{config.SINYI_LIST_URL}{path}/index.html"
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = client.post(config.SINYI_API_URL, data=data, timeout=config.REQUEST_TIMEOUT_SEC,
                               headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest"})
            resp.raise_for_status()
            opt = resp.json().get("OPT") or {}
            if opt.get("status") != "OK":
                raise ValueError(f"status={opt.get('status')!r}")
            return opt
        except Exception as exc:  # noqa: BLE001 — 任何失敗都可重試/跳過
            if attempt < config.MAX_RETRIES:
                backoff = config.REQUEST_INTERVAL_SEC * (2 ** attempt)
                log.warning("[信義] 抓取失敗（第 %d 次重試，等 %ds）：%s", attempt + 1, backoff, exc)
                time.sleep(backoff)
                continue
            log.error("[信義] 抓取放棄：%s page=%d（%s）", path, page, exc)
            return None


def scrape_sinyi_subscription(sub: dict, fetched_at: datetime | None = None,
                              client: httpx.Client | None = None) -> tuple[list[dict], set]:
    """抓單一訂閱的信義物件，回傳 (物件清單, 已涵蓋行政區集合)。

    所有區在同一個查詢內，故涵蓋是全有或全無：第一頁成功 → 訂閱的所有區都算涵蓋
    （全區訂閱則為該城市所有區）；第一頁失敗 → 空集合，上層不會把信義物件誤判下架。
    """
    fetched_at = fetched_at or datetime.now()
    path = build_sinyi_path(sub)
    if not path:
        return [], set()

    own = client is None
    if own:
        client = httpx.Client(headers={"User-Agent": config.USER_AGENT,
                                       "Accept-Language": "zh-TW,zh;q=0.9"},
                              follow_redirects=True, verify=_build_ssl_context())
    rows: dict[str, dict] = {}
    covered: set = set()
    total = None
    try:
        for page in range(1, config.SINYI_MAX_PAGES + 1):
            if page > 1:
                time.sleep(config.REQUEST_INTERVAL_SEC)
            opt = _post_page(client, path, page)
            if opt is None:
                # 中途某頁失敗：沒抓到的頁上的物件會「看似消失」，整輪視為未涵蓋，不判下架
                covered = set()
                break
            if page == 1:
                names = config.SECTION_NAMES.get(str(sub["region"]), {})
                secs = sub.get("sections") or list(names)
                covered = {names[str(s)] for s in secs if str(s) in names}
                total = int(opt.get("total") or 0)
            for r in opt.get("List") or []:
                if not r.get("NO"):
                    continue
                row = listing_from_api(r, sub, fetched_at)
                if filters.matches(row, sub):
                    rows.setdefault(row["listing_id"], row)
            if page >= int(opt.get("totalPage") or 0):
                break
    finally:
        if own:
            client.close()
    log.info("[信義][%s] 伺服器 %s 筆，符合訂閱 %d 筆（%s）", sub["id"], total, len(rows), path)
    return list(rows.values()), covered

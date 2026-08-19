"""把買屋（中古屋）列表 __NUXT__ 的 JSON 物件對應成我們的 schema。

比價基準為「總價（萬）」= total_price，供 diff 使用（main 以 price_key='total_price' 呼叫）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from scraper.nuxt import extract_listings


def _layout(text: str):
    def grab(u):
        m = re.search(rf"(\d+)\s*{u}", text or "")
        return int(m.group(1)) if m else None
    return grab("房"), grab("廳"), grab("衛")


def _floor(text: str):
    if not text or "/" not in text:
        return (text or None), None
    f, _, t = text.rpartition("/")
    return f or None, t or None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _posted_date(posttime, fetched_at) -> str | None:
    try:
        return datetime.fromtimestamp(int(posttime), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return fetched_at.date().isoformat()


def _map(r: dict, fetched_iso: str, fetched_at: datetime) -> dict:
    lid = str(r.get("houseid"))
    rooms, halls, baths = _layout(r.get("room", ""))
    floor, total_floor = _floor(r.get("floor", ""))
    return {
        "listing_id": lid,
        "title": r.get("title"),
        "url": f"https://sale.591.com.tw/home/house/detail/2/{lid}.html",
        "image": r.get("photo_url"),
        "region": r.get("region_name"),
        "district": r.get("section_name"),
        "community": r.get("community_name") or None,
        "address": r.get("address"),
        "kind_name": r.get("kind_name"),
        "shape_name": r.get("shape_name"),
        "rooms": rooms, "halls": halls, "baths": baths,
        "size_ping": _num(r.get("area")),          # 權狀坪數
        "main_area": _num(r.get("mainarea")),       # 主建物
        "floor": floor, "total_floor": total_floor,
        "total_price": _num(r.get("price")),        # 總價（萬）— 比價基準
        "unit_price": _num(r.get("unitprice")),     # 單價（萬/坪）
        "unit_price_text": r.get("unit_price"),
        "houseage": (int(r["houseage"]) if str(r.get("houseage")).lstrip("-").isdigit() else None),
        "has_carport": bool(r.get("has_carport")),
        "cart_model": r.get("cartmodel") or None,
        "poster_name": r.get("nick_name") or r.get("linkman"),
        "posted_at": _posted_date(r.get("posttime"), fetched_at),
        "updated_rel": r.get("refreshtime"),
        "is_down_price": bool(r.get("is_down_price")),
        "first_seen": fetched_iso, "last_seen": fetched_iso,
        "status": "active",
    }


def listings_from_sale_json(raw: list[dict], fetched_at: datetime | None = None) -> list[dict]:
    fetched_at = fetched_at or datetime.now(timezone.utc)
    fetched_iso = fetched_at.date().isoformat()
    return [_map(r, fetched_iso, fetched_at) for r in raw if r.get("houseid")]


# 實測（2026-08-19）：591 買屋 BFF 會把同一物件由多個仲介以不同 houseid 重複刊登
# （單一物件可達 11 筆）。其中 id 落在「24 號段」（≥ 24,000,000）者為代銷/同步餵入的
# 重複來源，sale.591 沒有對應詳情頁，/detail/2/{id}.html 一律 404；正常中古屋在
# 20–21 號段、連結皆正常。此門檻是目前觀測到的乾淨分界，若 591 改變 id 配置需重新檢視。
LIVE_ID_MAX = 24_000_000


def _link_live(listing_id) -> bool:
    """該 listing 的詳情頁是否可連（id 未落在 24 號段）。非數字 id 保守視為可用。"""
    try:
        return int(listing_id) < LIVE_ID_MAX
    except (TypeError, ValueError):
        return True


def _unit_key(r: dict):
    """同一物件的模糊鍵（社區/坪數/樓層/房數/總價）。無社區資訊者回 None（不併）。"""
    community = (r.get("community") or "").strip()
    if not community:
        return None
    return (community, r.get("size_ping"), r.get("floor"), r.get("rooms"), r.get("total_price"))


def dedupe_sale_units(listings: list[dict]) -> list[dict]:
    """收斂買屋重複刊登：

    1. 丟棄 24 號段（詳情頁 404）的死連結物件。
    2. 同一物件（模糊鍵相同）只留一筆，代表取「最小 houseid」——跨輪最穩定，
       可降低因代表輪替造成的假新增/假下架。
    無社區資訊者無法安全歸併，原樣保留（仍需通過死連結過濾）。
    """
    def _id_int(r):
        try:
            return int(r.get("listing_id"))
        except (TypeError, ValueError):
            return float("inf")

    chosen: dict = {}       # unit_key -> 代表 row
    passthrough: list = []  # 無社區、無法歸併者
    for r in listings:
        if not _link_live(r.get("listing_id")):
            continue
        key = _unit_key(r)
        if key is None:
            passthrough.append(r)
            continue
        cur = chosen.get(key)
        if cur is None or _id_int(r) < _id_int(cur):
            chosen[key] = r
    return passthrough + list(chosen.values())


def parse_sale_html(html: str, fetched_at: datetime | None = None) -> list[dict]:
    return listings_from_sale_json(extract_listings(html), fetched_at=fetched_at)

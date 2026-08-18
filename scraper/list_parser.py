"""把 591 列表頁的資料轉成物件 dict 清單。

資料來源改為列表頁 window.__NUXT__ 內的結構化 JSON（見 scraper/nuxt.py），
比解析 HTML 更準、更穩。`listings_from_json` 為純對應函式（無 I/O、可單元測試）；
`parse_list_html` 則負責從 HTML 取出 __NUXT__（需 node）再對應。
輸出 schema 與先前一致，供 diff / notify / 網頁沿用。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from scraper.nuxt import extract_listings

POSTER_TYPES = ("屋主", "代理人", "仲介", "房東", "委託", "建商", "代管")


def _parse_money(text) -> int | None:
    digits = re.sub(r"[^\d]", "", str(text or ""))
    return int(digits) if digits else None


def _fee_included(text: str) -> list[str]:
    """'(租金含管理費/車位)' -> ['管理費','車位']；無則空。"""
    if not text or "含" not in text:
        return []
    after = text.split("含", 1)[1].strip("()（） ")
    return [x.strip() for x in re.split(r"[/、,]", after) if x.strip()]


def _parse_layout(text: str) -> tuple[int | None, int | None, int | None]:
    """'4房2廳' / '4房2廳2衛' -> (rooms, halls, baths)。缺項 None。"""
    def grab(unit: str):
        m = re.search(rf"(\d+)\s*{unit}", text or "")
        return int(m.group(1)) if m else None
    return grab("房"), grab("廳"), grab("衛")


def _parse_floor(text: str) -> tuple[str | None, str | None]:
    if not text or "/" not in text:
        return (text or None), None
    floor, _, total = text.rpartition("/")
    return floor or None, total or None


def _parse_poster(text: str) -> tuple[str | None, str | None]:
    for p in POSTER_TYPES:
        if text and text.startswith(p):
            return p, (text[len(p):].strip() or None)
    return None, (text or None)


def _rel_to_date(rel: str, fetched_at: datetime) -> str | None:
    if not rel:
        return None
    if "剛剛" in rel or "分鐘" in rel or "小時" in rel:
        return fetched_at.date().isoformat()
    m = re.search(r"(\d+)\s*天", rel)
    if m:
        return (fetched_at - timedelta(days=int(m.group(1)))).date().isoformat()
    return fetched_at.date().isoformat()


def _map(r: dict, fetched_iso: str, fetched_at: datetime) -> dict:
    lid = str(r.get("id"))
    rooms, halls, baths = _parse_layout(r.get("layoutStr", ""))
    floor, total_floor = _parse_floor(r.get("floor_name", ""))
    district, _, street = (r.get("address") or "").partition("-")
    price = _parse_money(r.get("price"))
    extra_fee = int(r.get("extra_fee") or 0)
    total_monthly = (price + extra_fee) if price is not None else None
    updated_rel = r.get("refresh_time")
    poster_type, poster_name = _parse_poster(r.get("role_name") or "")
    photos = r.get("photoList") or []
    image = (photos[0] if photos else None) or r.get("cover")
    return {
        "listing_id": lid,
        "title": r.get("title"),
        "url": r.get("url") or f"https://rent.591.com.tw/{lid}",
        "image": image,
        "district": district.strip() or None,
        "street": street.strip() or None,
        "community": r.get("community_name") or None,
        "kind_name": r.get("kind_name") or None,
        "rooms": rooms, "halls": halls, "baths": baths,
        "size_ping": (float(r["area"]) if r.get("area") not in (None, "", 0) else None),
        "floor": floor, "total_floor": total_floor,
        "price": price,
        "extra_fee": extra_fee,
        "fee_included": _fee_included(r.get("price_contain_text") or ""),
        "total_monthly": total_monthly,
        "tags": r.get("tags") or [],
        "poster_type": poster_type, "poster_name": poster_name,
        "updated_rel": updated_rel,
        "posted_at": _rel_to_date(updated_rel or "", fetched_at),
        "first_seen": fetched_iso, "last_seen": fetched_iso,
        "status": "active",
        # 591 自算的降價資訊（保留備用）
        "down_price": int(r.get("diff_price") or 0),
    }


def listings_from_json(raw: list[dict], fetched_at: datetime | None = None) -> list[dict]:
    """__NUXT__ 物件清單 -> 我們的物件 dict 清單（純對應，無 I/O）。"""
    fetched_at = fetched_at or datetime.now()
    fetched_iso = fetched_at.date().isoformat()
    return [_map(r, fetched_iso, fetched_at) for r in raw if r.get("id")]


def parse_list_html(html: str, fetched_at: datetime | None = None) -> list[dict]:
    """列表頁 HTML -> 物件 dict 清單（從 __NUXT__ 取 JSON，需 node）。"""
    return listings_from_json(extract_listings(html), fetched_at=fetched_at)

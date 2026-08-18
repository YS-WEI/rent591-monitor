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
        "houseage": (int(r["houseage"]) if str(r.get("houseage") or "").isdigit() else None),
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


def parse_sale_html(html: str, fetched_at: datetime | None = None) -> list[dict]:
    return listings_from_sale_json(extract_listings(html), fetched_at=fetched_at)

"""把一筆買屋（中古屋）訂閱條件組成 sale.591 列表頁網址。

實測參數（2026-08）：
  https://sale.591.com.tw/?shType=list&regionid=1&section=8&kind=9&price=2000_3000&shape=2&firstRow=0
- regionid：縣市（沿用縣市代碼）
- section：區域（沿用區代碼，逗號複選）
- kind：類型（9=住宅，其餘見 config.SALE_KIND_NAMES）
- shape：型態（沿用租屋代碼，逗號複選）
- price：總價範圍（萬），格式 `min_max`；開放端留空（如 `2000_`、`_3000`）
- firstRow：分頁起始列（0/30/60…）
屋齡、坪數、房數等在程式端過濾（JSON 已有 houseage/area/room），不放 URL。
"""
from __future__ import annotations


def _price_wan(low, high) -> str | None:
    if low is None and high is None:
        return None
    return f"{'' if low is None else low}_{'' if high is None else high}"


def build_sale_url(sub: dict, section: str | None = None, first_row: int = 0) -> str:
    params: list[tuple[str, str]] = [("shType", "list"), ("regionid", str(sub["region"]))]

    secs = [section] if section is not None else (sub.get("sections") or [])
    if secs:
        params.append(("section", ",".join(str(s) for s in secs)))

    params.append(("kind", str(sub.get("kind") or "9")))  # 預設住宅

    shape = sub.get("shape") or []
    if shape:
        params.append(("shape", ",".join(str(s) for s in shape)))

    price = _price_wan(sub.get("price_min"), sub.get("price_max"))
    if price is not None:
        params.append(("price", price))

    params.append(("firstRow", str(first_row)))

    query = "&".join(f"{k}={v}" for k, v in params)
    return f"https://sale.591.com.tw/?{query}"

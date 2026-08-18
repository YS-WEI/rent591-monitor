"""把一筆買屋（中古屋）訂閱條件組成 591 買屋 BFF API 網址。

直接打 JSON API（無需 cookie），比抓 HTML+eval 乾淨：
  https://bff-house.591.com.tw/v1/web/sale/list?type=2&category=1&regionid=3&section=43&kind=9&price=$0_$2500&shape=2&pattern=4,5&firstRow=0&shType=list
回傳 data.house_list（物件）與 data.total（總筆數）。
- regionid/section：縣市/區（沿用代碼，section 逗號複選）
- kind：9=住宅（見 config.SALE_KIND_NAMES）；shape：型態（逗號複選）
- pattern：房數（4=4房以上→展開 4,5）
- price：總價（萬），格式 `$min_$max`，開放上限 `$min_$`
- firstRow：分頁起始列（0/30/60…）；每頁約 30
坪數/屋齡等仍在程式端過濾。
"""
from __future__ import annotations


def _price_wan(low, high) -> str | None:
    """總價（萬）→ 591 格式 `$min_$max`；開放上限為 `$min_$`。"""
    if low is None and high is None:
        return None
    low_part = f"${0 if low is None else low}"
    high_part = f"${high}" if high is not None else "$"
    return f"{low_part}_{high_part}"


def _pattern(layout) -> str | None:
    """房數 → 591 買屋的 pattern 參數。'4'（4房以上）展開為 4,5（591 5=5房以上）。"""
    if not layout:
        return None
    nums: list[str] = []
    for l in layout:
        if str(l) == "4":
            nums += ["4", "5"]
        else:
            nums.append(str(l))
    seen = list(dict.fromkeys(nums))  # 去重保序
    return ",".join(seen)


def build_sale_url(sub: dict, section: str | None = None, first_row: int = 0) -> str:
    params: list[tuple[str, str]] = [
        ("type", "2"), ("category", "1"), ("shType", "list"),
        ("regionid", str(sub["region"])),
    ]

    secs = [section] if section is not None else (sub.get("sections") or [])
    if secs:
        params.append(("section", ",".join(str(s) for s in secs)))

    params.append(("kind", str(sub.get("kind") or "9")))  # 預設住宅

    shape = sub.get("shape") or []
    if shape:
        params.append(("shape", ",".join(str(s) for s in shape)))

    pattern = _pattern(sub.get("layout"))
    if pattern is not None:
        params.append(("pattern", pattern))  # 房數（伺服器端篩選）

    price = _price_wan(sub.get("price_min"), sub.get("price_max"))
    if price is not None:
        params.append(("price", price))

    params.append(("firstRow", str(first_row)))

    query = "&".join(f"{k}={v}" for k, v in params)
    return f"https://bff-house.591.com.tw/v1/web/sale/list?{query}"

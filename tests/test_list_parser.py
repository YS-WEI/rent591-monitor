"""驗證列表資料對應（改用 __NUXT__ 的結構化 JSON）。

為何重要：這些欄位是 diff（以 total_monthly 比價）與通知的來源，對應錯位會誤報。
主體測試用固定 JSON fixture 走純對應函式（不需 node、可重現）；
另有一個整合測試確認能從 HTML 取出 __NUXT__（需 node，沒裝就跳過）。
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.list_parser import listings_from_json, parse_list_html  # noqa: E402

FIX_DIR = Path(__file__).resolve().parent / "fixtures"
JSON_FIXTURE = FIX_DIR / "rent_list.json"
HTML_FIXTURE = FIX_DIR / "list_sample.html"
FETCHED_AT = datetime(2026, 8, 12, 14, 0, 0)


def _rows():
    raw = json.loads(JSON_FIXTURE.read_text(encoding="utf-8"))
    return listings_from_json(raw, fetched_at=FETCHED_AT)


def _by_id(rows, lid):
    return next(r for r in rows if r["listing_id"] == lid)


def test_maps_all_items():
    rows = _rows()
    assert len(rows) == 30
    assert all(r["listing_id"] for r in rows)


def test_owner_listing_fields():
    r = _by_id(_rows(), "21813196")
    assert r["district"] == "板橋區"
    assert r["street"] == "金門街369巷36號"
    assert r["community"] == "金龍名邸"
    assert r["kind_name"] == "整層住家"
    assert (r["rooms"], r["halls"]) == (4, 2)
    assert r["size_ping"] == 40.0
    assert (r["floor"], r["total_floor"]) == ("4F", "7F")
    assert r["price"] == 33000
    assert r["extra_fee"] == 0
    assert r["total_monthly"] == 33000
    assert r["poster_type"] == "屋主"
    assert r["poster_name"] == "廖小姐"
    assert "屋主直租" in r["tags"]
    assert r["image"].startswith("https://") and "591.com.tw" in r["image"]


def test_extra_fee_added_to_total_monthly():
    # 額外費用要計入 total_monthly，否則比價會失真（JSON 的 extra_fee 為結構化欄位，較準）
    r = _by_id(_rows(), "21814834")
    assert r["extra_fee"] == 1580
    assert r["price"] == 35000
    assert r["total_monthly"] == 36580


def test_fee_included_parsed():
    r = _by_id(_rows(), "21817212")
    assert r["extra_fee"] == 0
    assert r["fee_included"] == ["管理費"]


def test_relative_days_converted_to_absolute_date():
    # '5天前' 相對 2026-08-12 -> 2026-08-07
    assert _by_id(_rows(), "21793269")["posted_at"] == "2026-08-07"


def test_within_a_day_uses_fetch_date():
    assert _by_id(_rows(), "21817212")["posted_at"] == "2026-08-12"


@pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 才能 eval __NUXT__")
def test_parse_from_html_via_node():
    rows = parse_list_html(HTML_FIXTURE.read_text(encoding="utf-8"), fetched_at=FETCHED_AT)
    assert len(rows) == 30
    assert _by_id(rows, "21813196")["community"] == "金龍名邸"

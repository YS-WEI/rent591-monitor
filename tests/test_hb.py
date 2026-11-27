"""住商不動產來源：組路徑、解 __NUXT_DATA__、欄位對應（租金單位萬→元）、依訂閱精篩、翻頁與失敗。

為何重要：
- 住商租金單位是「萬」：沒換算成元，比價/通知/降價判斷都會差一萬倍。
- 路徑格式錯了伺服器只會回空結果（不會報錯），必須鎖住實測可用的格式。
- 與 591、信義並存：住商被擋時不能把住商物件誤判下架。
"""
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from diff import diff_snapshots  # noqa: E402
from notify import format_report  # noqa: E402
from scraper import hb_scraper, list_scraper  # noqa: E402
from scraper.hb_scraper import build_hb_path, extract_items, listing_from_item  # noqa: E402

HTML = (Path(__file__).parent / "fixtures" / "hb_list.html").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 27, 10, 0)
SUB_4R = {"id": "sub-4r", "region": "3", "sections": ["43", "47", "44", "26", "27"], "kind": "1",
          "layout": ["4"], "shape": ["2"], "price_min": 0, "price_max": 50000,
          "acreage_min": 30, "acreage_max": None}


def test_path_matches_live_verified_format():
    # 2026-11 實測此路徑伺服器端套用全部條件（只回 1 筆：新莊 大樓 4 房 50.84 坪 3.2 萬）
    assert build_hb_path(SUB_4R) == ("新北市/241-247-242-220-221/elevator-mansion-style/0-5-price/"
                                     "apartment-type/area-30-up-area/4_up_room-pattern")


def test_path_price_in_wan_and_ranges():
    sub = {"region": "1", "sections": ["4"], "kind": "2", "layout": ["1"],
           "price_min": None, "price_max": 15000, "acreage_min": 8, "acreage_max": 20}
    assert build_hb_path(sub) == "台北市/105/1.5-down-price/cottage-type/area-8-20-area/1_room-pattern"


def test_path_room_range_and_page():
    sub = {"region": "3", "sections": [], "layout": ["2", "3"]}
    assert build_hb_path(sub, page=3) == "新北市/2_3_room-pattern/3-page"
    assert "2_up_room" in build_hb_path({"region": "3", "layout": ["2", "4"]})


def test_unsupported_city_is_skipped():
    assert build_hb_path({"region": "99"}) is None


def test_extract_items_from_nuxt_payload():
    items = extract_items(HTML)
    assert len(items) == 10
    assert items[0]["sn"] == "ZR200422" and items[0]["room"] == 5
    assert extract_items("<html>沒有資料</html>") == []


def test_mapping_converts_wan_to_yuan():
    o = next(x for x in extract_items(HTML) if x["sn"] == "OR236957")  # 3.3 萬
    r = listing_from_item(o, SUB_4R, NOW)
    assert r["listing_id"] == "hb-OR236957" and r["source"] == "hb"
    assert r["url"] == "https://www.hbhousing.com.tw/detail?sn=OR236957"
    assert (r["price"], r["total_monthly"]) == (33000, 33000)
    assert (r["district"], r["street"]) == ("板橋區", "忠孝路")
    assert (r["rooms"], r["size_ping"], r["floor"], r["total_floor"]) == (4, 36.21, "3", "4")


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(hb_scraper.time, "sleep", lambda s: None)
    monkeypatch.setattr(list_scraper.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "MAX_RETRIES", 0)


def _scrape(handler, sub=SUB_4R):
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        return hb_scraper.scrape_hb_subscription(sub, fetched_at=NOW, client=c)


def test_filters_by_subscription_content():
    # 伺服器回的物件仍要依訂閱精篩：超過 5 萬（11、18、7、8.8、5.3 萬）或不到 30 坪的都要濾掉
    rows, covered = _scrape(lambda req: httpx.Response(200, text=HTML))
    assert {r["listing_id"] for r in rows} == {"hb-OR233151", "hb-OR236957", "hb-gOT23135", "hb-gOT22977"}
    assert covered == {"板橋區", "三重區", "蘆洲區", "新莊區", "汐止區"}


def test_stops_when_page_repeats():
    # 第 2 頁回同一批（超出頁數時常見）→ 沒有新物件就停，不無限翻頁
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, text=HTML)
    _scrape(handler)
    assert len(calls) == 2 and "2-page" in calls[1]


def test_page_failure_marks_nothing_covered():
    def handler(req):
        return httpx.Response(403) if "2-page" in str(req.url) else httpx.Response(200, text=HTML)
    rows, covered = _scrape(handler)
    assert rows and covered == set()


def test_hb_blocked_does_not_remove_hb_listings():
    rec = {"listing_id": "hb-X", "district": "板橋區", "source": "hb", "total_monthly": 30000,
           "status": "active", "missing_count": 0, "price_history": []}
    state, _ = diff_snapshots({"listings": {"hb-X": rec}}, [], today="2026-11-27",
                              covered_districts={"板橋區", "sinyi:板橋區"})
    assert state["listings"]["hb-X"]["missing_count"] == 0


def test_notification_marks_hb_source():
    report = {"new": [{"title": "住商好房", "district": "板橋區", "source": "hb", "total_monthly": 33000}],
              "price_drop": [], "removed": []}
    assert "· ［住商］住商好房" in format_report(report)

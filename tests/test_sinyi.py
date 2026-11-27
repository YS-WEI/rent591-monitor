"""信義房屋來源：組路徑、欄位對應、依訂閱精篩、分頁/失敗處理、與 591 並存的下架判斷。

為何重要：
- 信義伺服器端篩選較粗（只有「N 房以上」「N 坪以上」），不精篩就會把不符訂閱的物件
  灌進通知（例如訂 1 房卻收到 3 房）。
- 信義和 591 是兩個獨立來源，各自可能被擋；一邊失敗時絕不能把那一邊的物件誤判下架。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from diff import diff_snapshots  # noqa: E402
from notify import format_report  # noqa: E402
from scraper import sinyi_scraper  # noqa: E402
from scraper.sinyi_scraper import build_sinyi_path, listing_from_api  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sinyi_list.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 27, 10, 0)

# 使用者實際的訂閱「新北 板橋・三重・蘆洲・新莊 4房」（含汐止）
SUB_4R = {"id": "sub-4r", "region": "3", "sections": ["43", "47", "44", "26", "27"], "kind": "1",
          "layout": ["4"], "shape": ["2"], "price_min": 0, "price_max": 50000,
          "acreage_min": 30, "acreage_max": None}


def test_path_matches_live_verified_format():
    # 2026-11 實測此格式伺服器端確實套用區域/用途/租金/房數/坪數/型態
    assert build_sinyi_path(SUB_4R) == \
        "NewTaipei-city/241-247-242-220-221-zip/house-use/0-50000-price/4-up-room/30-up-area/t2-type"


def test_path_open_ranges_and_suite():
    sub = {"region": "1", "sections": ["4", "7"], "kind": "2", "layout": [],
           "price_min": None, "price_max": 10000, "acreage_min": 8}
    assert build_sinyi_path(sub) == "Taipei-city/105-110-zip/rent1-use/0-10000-price/8-up-area"
    sub2 = {"region": "1", "sections": [], "kind": "1", "price_min": 20000, "price_max": None}
    assert build_sinyi_path(sub2) == "Taipei-city/house-use/20000-up-price"


def test_path_uses_min_room_since_sinyi_only_has_n_up():
    # 訂 2 房與 4 房以上 → 送 2-up-room，精確值交給 filters
    sub = {"region": "3", "sections": [], "layout": ["4", "2"]}
    assert "2-up-room" in build_sinyi_path(sub)


def test_unsupported_city_is_skipped():
    assert build_sinyi_path({"region": "99", "sections": []}) is None


def test_mapping_fields():
    rows = {r["NO"]: listing_from_api(r, SUB_4R, NOW) for r in FIXTURE["OPT"]["List"]}
    r = rows["C366627"]
    assert r["source"] == "sinyi"
    assert r["url"] == "https://www.sinyi.com.tw/rent/houseno/C366627"
    # address 帶社區名時仍要解析出正確行政區（下架判斷依賴 district）
    assert (r["district"], r["street"], r["community"]) == ("土城區", "金安街", "成功座標")
    assert (r["price"], r["total_monthly"], r["rooms"]) == (33000, 33000, 4)
    assert (r["floor"], r["total_floor"], r["size_ping"]) == ("3", "13", 41.44)
    assert r["posted_at"] == "2026-11-25"  # 信義給絕對時間，不需相對換算
    assert r["kind_name"] == "整層住家"


class _Api:
    """假的 ajaxSearchHouse.php：依 page 回應，可指定某頁失敗。"""

    def __init__(self, pages: list, fail_pages=()):
        self.pages, self.fail_pages, self.calls = pages, set(fail_pages), []

    def __call__(self, request: httpx.Request):
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        page = int(form["page"])
        self.calls.append(page)
        if page in self.fail_pages:
            return httpx.Response(403)
        opt = {"status": "OK", "totalPage": len(self.pages), "total": 99, "List": self.pages[page - 1]}
        return httpx.Response(200, json={"OPT": opt})


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(sinyi_scraper.time, "sleep", lambda s: None)
    monkeypatch.setattr(config, "MAX_RETRIES", 0)


def _scrape(api, sub=SUB_4R):
    with httpx.Client(transport=httpx.MockTransport(api)) as c:
        return sinyi_scraper.scrape_sinyi_subscription(sub, fetched_at=NOW, client=c)


def test_filters_by_subscription_content():
    # 伺服器回的 2、3 房（信義只篩 N 房以上，實務上也會混入）必須被訂閱條件濾掉
    L = FIXTURE["OPT"]["List"]
    rows, covered = _scrape(_Api([L]))
    assert {r["listing_id"] for r in rows} == {"C366627", "C365988"}
    assert covered == {"板橋區", "三重區", "蘆洲區", "新莊區", "汐止區"}


def test_paginates_until_total_page():
    L = FIXTURE["OPT"]["List"]
    api = _Api([L[:3], L[3:]])
    rows, _ = _scrape(api, {**SUB_4R, "layout": [], "acreage_min": None})
    assert api.calls == [1, 2]
    assert len(rows) == 6


def test_mid_pagination_failure_marks_nothing_covered():
    # 第 2 頁失敗：那頁的物件會「看似消失」，必須整輪視為未涵蓋，否則會誤判下架
    L = FIXTURE["OPT"]["List"]
    rows, covered = _scrape(_Api([L[:3], L[3:]], fail_pages=[2]),
                            {**SUB_4R, "layout": [], "acreage_min": None})
    assert len(rows) == 3 and covered == set()


def test_first_page_failure_returns_empty():
    rows, covered = _scrape(_Api([[]], fail_pages=[1]))
    assert rows == [] and covered == set()


def _rec(lid, district, source=None):
    r = {"listing_id": lid, "district": district, "total_monthly": 30000, "status": "active",
         "missing_count": 0, "price_history": [{"date": "2026-11-26", "price": 30000}]}
    if source:
        r["source"] = source
    return r


def test_sinyi_blocked_does_not_remove_sinyi_listings():
    # 591 板橋成功、信義被擋 → 591 消失物件照常累計 missing，信義物件原狀保留
    prev = {"listings": {"591A": _rec("591A", "板橋區"), "C1": _rec("C1", "板橋區", "sinyi")}}
    state, _ = diff_snapshots(prev, [], today="2026-11-27", covered_districts={"板橋區"})
    assert state["listings"]["591A"]["missing_count"] == 1
    assert state["listings"]["C1"]["missing_count"] == 0


def test_sinyi_covered_counts_missing():
    prev = {"listings": {"C1": _rec("C1", "板橋區", "sinyi")}}
    state, _ = diff_snapshots(prev, [], today="2026-11-27", covered_districts={"sinyi:板橋區"})
    assert state["listings"]["C1"]["missing_count"] == 1


def test_notification_marks_every_source():
    # 兩個來源混在同一則通知裡，每筆都要看得出來自哪個網站
    report = {"new": [{**_rec("C1", "板橋區", "sinyi"), "title": "好房"},
                      {**_rec("1", "板橋區"), "title": "591房"}],
              "price_drop": [], "removed": []}
    text = format_report(report)
    assert "· ［信義］好房" in text
    assert "· ［591］591房" in text  # 591 物件沒有 source 欄位，也要標成 591

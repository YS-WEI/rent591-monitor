"""驗證程式端過濾（因 591 SSR 未套用房數/坪數等篩選）。

為何重要：若不自行過濾，查「台北中正 4 房」時 SSR 會回一堆 2 房/13 坪，
導致案件數灌水、通知誤報。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters import matches, matches_sale, _layout_ok  # noqa: E402

SALE_SUB = {"layout": ["3", "4"], "price_min": 2000, "price_max": 3500,
            "acreage_min": None, "acreage_max": None, "houseage_max": 30, "shape": ["2"]}


def _sale(**kw):
    d = {"rooms": 3, "total_price": 2800, "size_ping": 35.0, "houseage": 16, "shape_name": "電梯大樓"}
    d.update(kw)
    return d


def test_sale_rejects_over_total_price():
    assert not matches_sale(_sale(total_price=4000), SALE_SUB)
    assert matches_sale(_sale(total_price=3000), SALE_SUB)


def test_sale_rejects_too_old():
    assert not matches_sale(_sale(houseage=45), SALE_SUB)


def test_sale_rejects_wrong_shape():
    assert not matches_sale(_sale(shape_name="公寓"), SALE_SUB)


def test_sale_rejects_wrong_room():
    assert not matches_sale(_sale(rooms=1), SALE_SUB)

SUB = {"kind": "1", "layout": ["4"], "price_min": 0, "price_max": 50000,
       "acreage_min": 30, "acreage_max": None}


def _lst(**kw):
    d = {"rooms": 4, "price": 40000, "size_ping": 35.0, "kind_name": "整層住家"}
    d.update(kw)
    return d


def test_layout_4_means_four_or_more():
    assert _layout_ok(4, ["4"]) and _layout_ok(5, ["4"])
    assert not _layout_ok(3, ["4"])
    assert not _layout_ok(None, ["4"])  # 開放式無房數 → 不符


def test_exact_room_match():
    assert _layout_ok(2, ["2"]) and not _layout_ok(3, ["2"])


def test_rejects_wrong_room_count():
    # SSR 常混入的 2 房要被擋掉
    assert not matches(_lst(rooms=2), SUB)


def test_rejects_too_small():
    assert not matches(_lst(size_ping=13.0), SUB)


def test_rejects_over_price():
    assert not matches(_lst(price=55000), SUB)


def test_rejects_wrong_kind():
    assert not matches(_lst(kind_name="獨立套房"), SUB)


def test_accepts_matching():
    assert matches(_lst(rooms=4, size_ping=40.0, price=48000), SUB)
    assert matches(_lst(rooms=5, size_ping=50.0, price=30000), SUB)


def test_empty_criteria_pass():
    assert matches(_lst(rooms=1, size_ping=5.0, price=99999), {})

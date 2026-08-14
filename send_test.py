"""送一則測試通知到已設定的管道（Telegram / Discord）。

由 .github/workflows/test-notify.yml 手動觸發，用來驗證通知有沒有接通。
可用 workflow 輸入或環境變數 TEST_GROUP 指定要測哪位歸屬人（填「全部」送所有人）。
會拿目前快照的一筆真實物件當範例（讓 Discord embed 也能顯示封面圖）。
"""
import json
import os

import config
import notify


def _sample_listing() -> dict:
    """從 latest.json 取一筆在架物件當範例；沒有就用假資料。"""
    if config.LATEST_PATH.exists():
        data = json.loads(config.LATEST_PATH.read_text(encoding="utf-8"))
        for rec in data.get("listings", {}).values():
            if rec.get("status") == "active":
                return rec
    return {
        "title": "測試物件（範例）", "district": "板橋區", "total_monthly": 35000,
        "rooms": 4, "size_ping": 40.0, "floor": "5F",
        "url": "https://rent.591.com.tw/", "image": None,
    }


def _all_groups() -> list[str]:
    """從 subscriptions.json 取所有歸屬人（保序去重）。"""
    data = json.loads(config.SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
    return list(dict.fromkeys((s.get("group") or "我") for s in data.get("subscriptions", []))) or ["我"]


if __name__ == "__main__":
    want = (os.environ.get("TEST_GROUP") or "我").strip()
    targets = _all_groups() if want in ("全部", "all", "ALL") else [want]

    report = {"new": [], "price_drop": [], "removed": []}
    for g in targets:
        s = dict(_sample_listing())
        s["title"] = f"[測試] {s.get('title', '')}"
        s["groups"] = [g]
        report["new"].append(s)

    notify.notify(report, [{"group": g} for g in targets])
    print(f"已對歸屬人 {targets} 送測試通知，請查看對應的 Telegram / Discord。")

"""送一則測試通知到已設定的管道（Telegram / Discord）。

由 .github/workflows/test-notify.yml 手動觸發，用來驗證通知有沒有接通。
會拿目前快照的一筆真實物件當範例（讓 Discord embed 也能顯示封面圖）。
"""
import json

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


if __name__ == "__main__":
    sample = _sample_listing()
    sample["groups"] = ["🧪測試"]
    report = {"new": [sample], "price_drop": [], "removed": []}
    # 用一個測試用歸屬人；未設路由會退回預設管道
    notify.notify(report, [{"group": "🧪測試"}])
    print("已呼叫 notify()，請查看 Telegram / Discord。")

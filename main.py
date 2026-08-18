"""主流程：讀訂閱 → 逐訂閱抓取 → 比對 → 通知 → 存快照。

依類型分派：
  python main.py              # 租屋（預設）
  python main.py --type sale  # 買屋（中古屋）
租屋與買屋各自讀/寫不同的資料檔、用不同的通知頻道。
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

import config
import notify
from diff import diff_snapshots
from scraper.list_scraper import scrape_subscription
from scraper.sale_scraper import scrape_sale_subscription
from storage import load_latest, load_watchlist, save_snapshot

log = logging.getLogger("main")

# 各類型的差異集中在這裡
KINDS = {
    "rent": {
        "scrape": scrape_subscription, "price_key": "total_monthly",
        "latest": config.LATEST_PATH, "snapshots": config.SNAPSHOT_DIR,
    },
    "sale": {
        "scrape": scrape_sale_subscription, "price_key": "total_price",
        "latest": config.SALE_LATEST_PATH, "snapshots": config.SALE_SNAPSHOT_DIR,
    },
}


def load_subscriptions(kind: str) -> tuple[list[dict], dict]:
    data = json.loads(config.SUBSCRIPTIONS_PATH.read_text(encoding="utf-8"))
    subs = [s for s in data.get("subscriptions", [])
            if s.get("enabled", True) and (s.get("type") or "rent") == kind]
    return subs, data.get("settings", {})


def collect_current(subs, fetched_at, scrape_fn):
    """逐訂閱抓取，跨訂閱以 listing_id 去重、併入歸屬人。"""
    merged: dict[str, dict] = {}
    stats, all_covered, cover_all = [], set(), False
    for sub in subs:
        group = sub.get("group") or "我"
        rows, covered = scrape_fn(sub, fetched_at=fetched_at)
        if covered is None:
            cover_all = True
        else:
            all_covered |= covered
        added = 0
        for r in rows:
            lid = r["listing_id"]
            if lid in merged:
                if group not in merged[lid]["groups"]:
                    merged[lid]["groups"].append(group)
            else:
                r["groups"] = [group]
                merged[lid] = r
                added += 1
        stats.append({"id": sub["id"], "name": sub.get("name", sub["id"]),
                      "group": group, "fetched": len(rows), "unique_added": added})
        log.info("訂閱 %s（%s）：抓到 %d 筆，新增去重 %d 筆", sub["id"], group, len(rows), added)
    return list(merged.values()), stats, (None if cover_all else all_covered)


def run(kind: str = "rent") -> dict:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfgk = KINDS[kind]
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    timestamp = now.strftime("%Y%m%d-%H%M%S")

    subs, settings = load_subscriptions(kind)
    if not subs:
        log.warning("沒有啟用中的%s訂閱，結束。", kind)
        return {}

    threshold = settings.get("missing_rounds_before_removed", 2)
    watchlist = load_watchlist()

    current, stats, covered = collect_current(subs, now, cfgk["scrape"])
    previous = load_latest(cfgk["latest"])
    if covered is not None and not covered:
        log.warning("本輪所有區皆未抓到（疑似被擋），維持既有狀態。")

    new_state, report = diff_snapshots(previous, current, today=today,
                                       missing_rounds_before_removed=threshold,
                                       covered_districts=covered,
                                       price_key=cfgk["price_key"])

    for lid, rec in new_state["listings"].items():
        rec["watched"] = lid in watchlist
        if lid in watchlist and isinstance(watchlist[lid], dict):
            rec["note"] = watchlist[lid].get("note", rec.get("note", ""))

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "kind": kind,
        "subscriptions": stats,
        "report": report,
        "listings": new_state["listings"],
    }
    save_snapshot(payload, timestamp, cfgk["latest"], cfgk["snapshots"])
    notify.notify(report, subs, kind=kind)

    log.info("[%s] 完成：🆕%d 💰%d ❌%d（狀態共 %d 筆）", kind,
             len(report["new"]), len(report["price_drop"]), len(report["removed"]),
             len(new_state["listings"]))
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=list(KINDS), default="rent")
    run(ap.parse_args().type)

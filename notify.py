"""通知：同時支援 Telegram Bot 與 Discord Webhook。

哪個 Secret 有設定就發哪個，兩個都設就都發：
- Telegram：TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
- Discord：DISCORD_WEBHOOK_URL

格式化為純函式，方便測試。實際發送從 GitHub Actions 那輪呼叫。
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict

import httpx

log = logging.getLogger(__name__)

TG_API = "https://api.telegram.org/bot{token}/sendMessage"
TG_MAX_CHARS = 3800  # Telegram 上限 4096，留餘裕
DISCORD_MAX_EMBEDS = 10  # Discord 單則訊息最多 10 個 embed
MAX_ITEMS = 24  # 單輪最多列幾筆物件（避免大量變動時洗版）

COLOR_NEW = 0x2E8B57
COLOR_DROP = 0xC8641E
COLOR_OFF = 0xA33A2E


# ---------- 共用 ----------

def _spec(r: dict) -> str:
    parts = []
    if r.get("rooms"):
        parts.append(f"{r['rooms']}房")
    if r.get("size_ping"):
        parts.append(f"{r['size_ping']}坪")
    if r.get("floor"):
        parts.append(str(r["floor"]))
    return "／".join(parts)


def _group_by_district(rows: list[dict]) -> dict[str, list[dict]]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[r.get("district") or "其他"].append(r)
    return g


def has_changes(report: dict) -> bool:
    return bool(report["new"] or report["price_drop"] or report["removed"])


# ---------- Telegram（純文字）----------

def format_report(report: dict, header: str = "591 租屋監控") -> str | None:
    """把 diff 報告排成 Telegram 通知文字；無變動回 None。"""
    new, drop, removed = report["new"], report["price_drop"], report["removed"]
    if not (new or drop or removed):
        return None

    lines = [f"🔔 {header}", f"🆕 新增 {len(new)}｜💰 降價 {len(drop)}｜❌ 下架 {len(removed)}"]

    if new:
        lines.append("\n🆕 新增")
        for district, rows in _group_by_district(new).items():
            lines.append(f"📍{district}")
            for r in rows:
                lines.append(f"· {r.get('title','')} ${r.get('total_monthly')}／月（{_spec(r)}）\n  {r.get('url','')}")

    if drop:
        lines.append("\n💰 降價")
        for district, rows in _group_by_district(drop).items():
            lines.append(f"📍{district}")
            for r in rows:
                lines.append(
                    f"· {r.get('title','')} ${r['old_price']}→${r['new_price']}"
                    f"（↓{r['drop_pct']}%）\n  {r.get('url','')}"
                )

    if removed:
        lines.append("\n❌ 下架")
        for district, rows in _group_by_district(removed).items():
            lines.append(f"📍{district}")
            lines.extend(f"· {r.get('title','')}" for r in rows)

    return "\n".join(lines)


def _chunk(text: str, limit: int = TG_MAX_CHARS) -> list[str]:
    chunks, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit and buf:
            chunks.append(buf)
            buf = ""
        buf += line + "\n"
    if buf.strip():
        chunks.append(buf)
    return chunks


def send_telegram(text: str, token: str, chat_id: str) -> bool:
    ok = True
    with httpx.Client(timeout=20) as client:
        for chunk in _chunk(text):
            try:
                resp = client.post(
                    TG_API.format(token=token),
                    json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                )
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.error("Telegram 推播失敗：%s", exc)
                ok = False
    return ok


# ---------- Discord（embed，帶封面圖）----------

def _discord_embed(r: dict, kind: str) -> dict:
    emoji = {"new": "🆕", "drop": "💰", "off": "❌"}[kind]
    color = {"new": COLOR_NEW, "drop": COLOR_DROP, "off": COLOR_OFF}[kind]
    desc = []
    if kind == "drop":
        desc.append(f"💰 ${r['old_price']:,}→${r['new_price']:,}（↓{r['drop_pct']}%）")
    elif r.get("total_monthly") is not None:
        desc.append(f"${r['total_monthly']:,}／月")
    if _spec(r):
        desc.append(_spec(r))
    if r.get("district"):
        desc.append(r["district"])
    embed = {
        "title": f"{emoji} {r.get('title','')}"[:250],
        "url": r.get("url"),
        "color": color,
        "description": " · ".join(desc),
    }
    if r.get("image"):
        embed["thumbnail"] = {"url": r["image"]}
    return embed


def format_discord(report: dict, header: str = "591 租屋監控") -> list[dict]:
    """把報告排成 Discord webhook payload 清單（每則最多 10 embed）；無變動回空。"""
    new, drop, removed = report["new"], report["price_drop"], report["removed"]
    if not (new or drop or removed):
        return []

    embeds = (
        [_discord_embed(r, "new") for r in new]
        + [_discord_embed(r, "drop") for r in drop]
        + [_discord_embed(r, "off") for r in removed]
    )
    overflow = max(0, len(embeds) - MAX_ITEMS)
    embeds = embeds[:MAX_ITEMS]

    content = f"🔔 **{header}**\n🆕 新增 {len(new)}｜💰 降價 {len(drop)}｜❌ 下架 {len(removed)}"
    if overflow:
        content += f"\n（另有 {overflow} 筆未列出，詳見網頁）"

    payloads = []
    for i in range(0, len(embeds), DISCORD_MAX_EMBEDS):
        payload = {"embeds": embeds[i:i + DISCORD_MAX_EMBEDS]}
        if i == 0:
            payload["content"] = content
        payloads.append(payload)
    return payloads


def send_discord(payloads: list[dict], webhook_url: str) -> bool:
    ok = True
    with httpx.Client(timeout=20) as client:
        for payload in payloads:
            try:
                resp = client.post(webhook_url, json=payload)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.error("Discord 推播失敗：%s", exc)
                ok = False
    return ok


# ---------- 依歸屬人分流 ----------

def _filter_by_group(report: dict, group: str) -> dict:
    """取出屬於某位歸屬人（group）的變動子集。"""
    def keep(rows):
        return [r for r in rows if group in (r.get("groups") or [])]
    return {"new": keep(report["new"]), "price_drop": keep(report["price_drop"]),
            "removed": keep(report["removed"])}


def _routes() -> dict:
    """讀取 NOTIFY_ROUTES（JSON）：{ "<歸屬人>": {"discord": url, "telegram_chat": id}, ... }。"""
    import json
    try:
        return json.loads(os.environ.get("NOTIFY_ROUTES") or "{}")
    except Exception:  # noqa: BLE001
        log.warning("NOTIFY_ROUTES 不是合法 JSON，忽略。")
        return {}


def _send_one(report: dict, header: str, discord_url: str | None,
              tg_token: str | None, tg_chat: str | None) -> bool:
    sent = False
    if tg_token and tg_chat:
        send_telegram(format_report(report, header), tg_token, tg_chat)
        sent = True
    if discord_url:
        send_discord(format_discord(report, header), discord_url)
        sent = True
    return sent


def notify(report: dict, subs: list[dict]) -> None:
    """依歸屬人把變動分流到各自的管道。

    路由來源 NOTIFY_ROUTES（Secret，JSON）；某人沒設定就退回預設管道
    （DISCORD_WEBHOOK_URL / TELEGRAM_BOT_TOKEN+TELEGRAM_CHAT_ID）。
    """
    if not has_changes(report):
        log.info("本輪無變動，不發送通知。")
        return

    groups = list(dict.fromkeys((s.get("group") or "我") for s in subs))  # 保序去重
    routes = _routes()
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    default_dc = os.environ.get("DISCORD_WEBHOOK_URL")
    default_tg_chat = os.environ.get("TELEGRAM_CHAT_ID")

    for group in groups:
        sub_report = _filter_by_group(report, group)
        if not has_changes(sub_report):
            continue
        route = routes.get(group, {})
        discord_url = route.get("discord") or default_dc
        tg_chat = route.get("telegram_chat") or default_tg_chat
        header = f"{group}的租屋監控" if group else "591 租屋監控"
        if not _send_one(sub_report, header, discord_url, tg_token, tg_chat):
            log.warning("「%s」無可用通知管道，內容預覽：\n%s",
                        group, format_report(sub_report, header))

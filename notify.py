"""通知：Telegram + Discord，依類型（租/買）分流到不同頻道。

各類型讀不同 Secret（租屋無前綴、買屋前綴 SALE_）：
- 預設頻道：{P}DISCORD_WEBHOOK_URL / {P}TELEGRAM_CHAT_ID（收該類型所有人，訊息標明是誰的）
- 分人路由：{P}NOTIFY_ROUTES（有設某人就額外送其專屬頻道）
Telegram Bot 共用 TELEGRAM_BOT_TOKEN。格式化為純函式，方便測試。
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict

import httpx

log = logging.getLogger(__name__)

TG_API = "https://api.telegram.org/bot{token}/sendMessage"
TG_MAX_CHARS = 3800
DISCORD_MAX_EMBEDS = 10
MAX_ITEMS = 24
COLOR_NEW, COLOR_DROP, COLOR_OFF = 0x2E8B57, 0xC8641E, 0xA33A2E


def has_changes(report: dict) -> bool:
    return bool(report["new"] or report["price_drop"] or report["removed"])


def _group_by_district(rows):
    g = defaultdict(list)
    for r in rows:
        g[r.get("district") or "其他"].append(r)
    return g


def _off_label(kind: str) -> str:
    return "下架/成交" if kind == "sale" else "下架"


# 租屋：維持原格式（有測試對應）
def _spec_rent(r):
    parts = []
    if r.get("rooms"):
        parts.append(f"{r['rooms']}房")
    if r.get("size_ping"):
        parts.append(f"{r['size_ping']}坪")
    if r.get("floor"):
        parts.append(str(r["floor"]))
    return "／".join(parts)


def _spec_sale(r):
    parts = []
    rm = "".join(f"{r[k]}{u}" for k, u in [("rooms", "房"), ("halls", "廳"), ("baths", "衛")] if r.get(k))
    if rm:
        parts.append(rm)
    if r.get("size_ping"):
        parts.append(f"{r['size_ping']}坪")
    if r.get("houseage") is not None:
        parts.append(f"{r['houseage']}年")
    if r.get("unit_price"):
        parts.append(f"{r['unit_price']:g}萬/坪")
    if r.get("has_carport"):
        parts.append(r.get("cart_model") or "有車位")
    return "／".join(parts)


def _new_line(r, kind):
    if kind == "sale":
        tp = r.get("total_price")
        return f"· {r.get('title','')} {tp:g}萬（{_spec_sale(r)}）\n  {r.get('url','')}"
    return f"· {r.get('title','')} ${r.get('total_monthly')}／月（{_spec_rent(r)}）\n  {r.get('url','')}"


def _drop_line(r, kind):
    if kind == "sale":
        return (f"· {r.get('title','')} {r['old_price']:g}→{r['new_price']:g}萬"
                f"（↓{r['drop_pct']}%）\n  {r.get('url','')}")
    return (f"· {r.get('title','')} ${r['old_price']}→${r['new_price']}"
            f"（↓{r['drop_pct']}%）\n  {r.get('url','')}")


# ---------- Telegram ----------

def format_report(report: dict, header: str = "591 租屋監控", kind: str = "rent") -> str | None:
    new, drop, removed = report["new"], report["price_drop"], report["removed"]
    if not (new or drop or removed):
        return None
    lines = [f"🔔 {header}",
             f"🆕 新增 {len(new)}｜💰 降價 {len(drop)}｜❌ {_off_label(kind)} {len(removed)}"]
    if new:
        lines.append("\n🆕 新增")
        for d, rows in _group_by_district(new).items():
            lines.append(f"📍{d}")
            lines.extend(_new_line(r, kind) for r in rows)
    if drop:
        lines.append("\n💰 降價")
        for d, rows in _group_by_district(drop).items():
            lines.append(f"📍{d}")
            lines.extend(_drop_line(r, kind) for r in rows)
    if removed:
        lines.append(f"\n❌ {_off_label(kind)}")
        for d, rows in _group_by_district(removed).items():
            lines.append(f"📍{d}")
            lines.extend(f"· {r.get('title','')}" for r in rows)
    return "\n".join(lines)


def _chunk(text, limit=TG_MAX_CHARS):
    chunks, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit and buf:
            chunks.append(buf)
            buf = ""
        buf += line + "\n"
    if buf.strip():
        chunks.append(buf)
    return chunks


def send_telegram(text, token, chat_id) -> bool:
    ok = True
    with httpx.Client(timeout=20) as client:
        for chunk in _chunk(text):
            try:
                client.post(TG_API.format(token=token),
                            json={"chat_id": chat_id, "text": chunk,
                                  "disable_web_page_preview": True}).raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.error("Telegram 推播失敗：%s", exc)
                ok = False
    return ok


# ---------- Discord ----------

def _discord_embed(r, flag, kind):
    emoji = {"new": "🆕", "drop": "💰", "off": "❌"}[flag]
    color = {"new": COLOR_NEW, "drop": COLOR_DROP, "off": COLOR_OFF}[flag]
    desc = []
    if flag == "drop":
        if kind == "sale":
            desc.append(f"💰 {r['old_price']:g}→{r['new_price']:g}萬（↓{r['drop_pct']}%）")
        else:
            desc.append(f"💰 ${r['old_price']:,}→${r['new_price']:,}（↓{r['drop_pct']}%）")
    elif kind == "sale" and r.get("total_price") is not None:
        desc.append(f"{r['total_price']:g}萬")
    elif r.get("total_monthly") is not None:
        desc.append(f"${r['total_monthly']:,}／月")
    spec = _spec_sale(r) if kind == "sale" else _spec_rent(r)
    if spec:
        desc.append(spec)
    if r.get("district"):
        desc.append(r["district"])
    embed = {"title": f"{emoji} {r.get('title','')}"[:250], "url": r.get("url"),
             "color": color, "description": " · ".join(desc)}
    if r.get("image"):
        embed["thumbnail"] = {"url": r["image"]}
    return embed


def format_discord(report: dict, header: str = "591 租屋監控", kind: str = "rent") -> list[dict]:
    new, drop, removed = report["new"], report["price_drop"], report["removed"]
    if not (new or drop or removed):
        return []
    embeds = ([_discord_embed(r, "new", kind) for r in new]
              + [_discord_embed(r, "drop", kind) for r in drop]
              + [_discord_embed(r, "off", kind) for r in removed])
    overflow = max(0, len(embeds) - MAX_ITEMS)
    embeds = embeds[:MAX_ITEMS]
    content = (f"🔔 **{header}**\n"
               f"🆕 新增 {len(new)}｜💰 降價 {len(drop)}｜❌ {_off_label(kind)} {len(removed)}")
    if overflow:
        content += f"\n（另有 {overflow} 筆未列出，詳見網頁）"
    payloads = []
    for i in range(0, len(embeds), DISCORD_MAX_EMBEDS):
        p = {"embeds": embeds[i:i + DISCORD_MAX_EMBEDS]}
        if i == 0:
            p["content"] = content
        payloads.append(p)
    return payloads


def send_discord(payloads, webhook_url) -> bool:
    ok = True
    with httpx.Client(timeout=20) as client:
        for payload in payloads:
            try:
                client.post(webhook_url, json=payload).raise_for_status()
            except Exception as exc:  # noqa: BLE001
                log.error("Discord 推播失敗：%s", exc)
                ok = False
    return ok


# ---------- 依歸屬人分流 ----------

def _filter_by_group(report: dict, group: str) -> dict:
    def keep(rows):
        return [r for r in rows if group in (r.get("groups") or [])]
    return {"new": keep(report["new"]), "price_drop": keep(report["price_drop"]),
            "removed": keep(report["removed"])}


def _routes(env_name: str) -> dict:
    try:
        return json.loads(os.environ.get(env_name) or "{}")
    except Exception:  # noqa: BLE001
        log.warning("%s 不是合法 JSON，忽略。", env_name)
        return {}


def notify(report: dict, subs: list[dict], kind: str = "rent") -> None:
    """依歸屬人把變動送到該類型（租/買）的通知管道。"""
    if not has_changes(report):
        log.info("本輪無變動，不發送通知。")
        return
    pfx = "" if kind == "rent" else "SALE_"
    label = "買屋" if kind == "sale" else "租屋"
    groups = list(dict.fromkeys((s.get("group") or "我") for s in subs))
    routes = _routes(f"{pfx}NOTIFY_ROUTES")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    default_dc = os.environ.get(f"{pfx}DISCORD_WEBHOOK_URL")
    default_tg_chat = os.environ.get(f"{pfx}TELEGRAM_CHAT_ID")

    for group in groups:
        sub_report = _filter_by_group(report, group)
        if not has_changes(sub_report):
            continue
        route = routes.get(group, {})
        header = f"{group}的{label}監控"
        discord_targets = {u for u in (default_dc, route.get("discord")) if u}
        tg_targets = {c for c in (default_tg_chat, route.get("telegram_chat")) if c}
        if not discord_targets and not tg_targets:
            log.warning("「%s」無可用通知管道，內容預覽：\n%s",
                        group, format_report(sub_report, header, kind))
            continue
        for url in discord_targets:
            send_discord(format_discord(sub_report, header, kind), url)
        if tg_targets and not tg_token:
            log.warning("有 Telegram chat 但未設 TELEGRAM_BOT_TOKEN，略過 Telegram。")
        elif tg_token:
            for chat in tg_targets:
                send_telegram(format_report(sub_report, header, kind), tg_token, chat)

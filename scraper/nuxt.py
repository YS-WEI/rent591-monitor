"""從 591 列表頁 HTML 取出 window.__NUXT__ 的物件清單（結構化 JSON）。

591 列表結果放在 Nuxt 的狀態物件（函式包裹的 IIFE），非乾淨 JSON 也非 HTML 卡片，
故用 node（vm 沙箱 + timeout）eval 後輸出 JSON 陣列，再由 Python 讀取。
node 在 GitHub Actions ubuntu runner 內建；本機亦需安裝 node。
"""
from __future__ import annotations

import json
import subprocess

import config

_JS = config.ROOT / "scraper" / "nuxt_extract.js"


def extract_listings(html: str) -> list[dict]:
    """回傳列表頁 __NUXT__ 內的物件清單（list of dict）；失敗回空清單或拋錯。"""
    if not html:
        return []
    try:
        proc = subprocess.run(
            ["node", str(_JS)],
            input=html, capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError as exc:  # 沒有 node
        raise RuntimeError("找不到 node，無法解析 591 列表 JSON") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"node 解析失敗：{proc.stderr[:200]}")
    return json.loads(proc.stdout or "[]")

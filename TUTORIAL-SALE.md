# 買屋（中古屋）監控 — 設定教學

本文專講**買屋（中古屋）**的設定，與租屋分開。租屋設定請看 [`TUTORIAL.md`](TUTORIAL.md)。
買屋與租屋**共用同一個 repo、同一套系統**，只是資料、排程、通知頻道各自獨立。

## 買屋監控做什麼

抓 591 中古屋（`sale.591`），比對出 🆕 新增、💰 **降價（總價下修）**、❌ 下架/成交，
依區分組通知。卡片資料：**總價（萬）、單價/坪、屋齡、格局（含衛）、坪數、樓層、型態、
平面/機械車位、社區、真實刊登日**。

- 資料檔：`data/sale.json`（與租屋 `data/latest.json` 分開）
- 排程：`.github/workflows/monitor-sale.yml`，**每 6 小時**（中古屋變動慢）
- 比價基準：**總價**（不是月租）

---

## 1. 新增買屋訂閱

> 目前買屋訂閱先用**編輯 `subscriptions.json`** 新增（網頁的「買屋」分頁開發中）。
> 可在 GitHub 網頁編輯器直接改，或用租屋網頁的「⚙️ 設定」token 之後由介面編輯。

在 `subscriptions.json` 的 `subscriptions` 陣列加一筆，**`type` 設 `"sale"`**：

```json
{
  "id": "sale-001",
  "type": "sale",
  "name": "台北士林/中山 3-4房 3500萬內",
  "group": "外婆家",
  "enabled": true,
  "region": "1",
  "sections": ["8", "3"],
  "kind": "9",
  "shape": ["2", "5"],
  "layout": ["3", "4"],
  "price_min": 0,
  "price_max": 3500,
  "acreage_min": null,
  "acreage_max": null,
  "houseage_max": 40
}
```

欄位說明：

| 欄位 | 意義 |
|---|---|
| `type` | 固定 `"sale"`（買屋） |
| `region` / `sections` | 縣市 / 區域（代碼沿用租屋，見 `CLAUDE.md`） |
| `kind` | `9`=住宅（其餘：5店面 6辦公 12住辦 11土地 7廠房 8車位） |
| `shape` | 型態：1公寓 2電梯大樓 3透天 4別墅 5華廈（可複選） |
| `layout` | 房數：`"4"`=4房以上，其餘為精確房數（可複選） |
| `price_min` / `price_max` | **總價範圍（萬）** |
| `acreage_min` / `acreage_max` | 坪數範圍（可留 `null`） |
| `houseage_max` | 屋齡上限（年，可省略） |
| `group` | 歸屬人（分人通知用） |

> 房數/坪數/屋齡/型態都會在程式端過濾，確保結果符合條件。

---

## 2. 設定買屋通知頻道（與租屋分開）

買屋通知走**獨立頻道**，Secret 名稱都加 `SALE_` 前綴
（repo → Settings → Secrets and variables → Actions）：

- `SALE_DISCORD_WEBHOOK_URL` — 買屋預設 Discord 頻道（收所有買屋變動）
- `SALE_TELEGRAM_CHAT_ID` — 買屋預設 Telegram（Bot 共用 `TELEGRAM_BOT_TOKEN`）
- `SALE_NOTIFY_ROUTES` — 買屋分人路由（JSON，格式同租屋的 `NOTIFY_ROUTES`）

分人邏輯與租屋一致：預設頻道收全部（標明是誰的），`SALE_NOTIFY_ROUTES` 有設的人再額外送其專屬頻道。

範例 `SALE_NOTIFY_ROUTES`：
```json
{ "外婆家": { "discord": "https://discord.com/api/webhooks/…" } }
```

---

## 3. 讓它跑

- **自動**：`monitor-sale.yml` 每 6 小時自動跑（台灣約 每 6 小時的第 47 分前後）。
- **手動**：Actions → **591 買屋監控排程** → Run workflow。

跑完會 commit `data/sale.json`；有新增/降價/下架時推播到你的買屋頻道。

> 租屋與買屋兩個排程**共用 concurrency group**、不會同時跑；push 前會 rebase，
> 不會互相撞版（兩者寫不同檔）。

---

## 4. 常見問題

| 症狀 | 說明 |
|---|---|
| 買屋沒通知 | 確認有**買屋訂閱（type:sale）**、且設了 `SALE_DISCORD_WEBHOOK_URL` 或 `SALE_TELEGRAM_CHAT_ID` |
| 抓到的房數/總價不符 | 程式端會過濾；若仍有偏差回報條件，多半是 `layout`/`price_max` 設定 |
| 想改頻率 | 改 `monitor-sale.yml` 的 cron（`47 */6 * * *`） |
| 排程延遲/偶爾跳過 | GitHub 排程特性，屬正常；資料每輪獨立比對不會漏 |

> 已知限制：純 HTTP 每區抓「最新那批」（~30 筆/區），量大的區可能不完整；
> 中古屋單價/屋齡/含衛格局等資料來自列表 JSON，通常完整。

---

## 待辦（開發中）

- 網頁「租屋 / 買屋」頂部分頁與買屋卡片（目前買屋以通知為主，網頁瀏覽稍後補）。

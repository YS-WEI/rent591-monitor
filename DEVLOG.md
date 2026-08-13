# 開發紀錄 DEVLOG

本檔為**開發者技術筆記**（非使用者文件；使用者請看 `TUTORIAL.md`）。
記錄開發過程的關鍵實測發現、技術決策與已知限制，方便日後接手或除錯。

---

## 一、591 實測行為（重要）

1. **列表頁是 JS 動態渲染**：純 HTTP GET 只拿得到 SSR 首頁約 30 筆，`page` 參數無效。
2. **SSR 只按 region/section 回傳，不套用 layout（房數）/acreage（坪數）等篩選**
   —— 那些是前端 JS 做的。實測查「台北中正 4 房」，SSR 回一堆 2 房/13 坪。
   → **必須在程式端自行過濾**（`filters.py`），否則案件數會灌水、通知誤報。
3. **`window.__NUXT__` 是函式包裹的壓縮 JS**（非純 JSON），脆弱難解。
   → 改走 **DOM 解析**（selectolax；主列表卡片 `div.item[data-id]`）。
4. **時間只有相對值**（「N 天前更新」「12 分鐘前」）→ 抓取當下即時換算絕對日期
   （`posted_at ≈ fetch_time − 相對時間`，誤差約一天內）。
5. **反爬**：對機房 IP（GitHub Actions＝Azure，非台灣）**偶發 403**，但重試通常能過。
   高頻請求更容易被擋。
6. **同物件多仲介重複刊登**（不同 id、同社區/坪數/樓層）——尚未去重（後續）。

## 二、技術決策

- **部署**：全靜態 = GitHub Actions（cron 爬蟲，commit 快照回 repo）+ GitHub Pages（網頁）。
  免費、免維運。放棄 FastAPI 後端（免費方案私有 repo 不能開 Pages，且無需保活伺服器）。
- **前端讀寫**：讀取走同源公開檔（免 token，任何瀏覽器零設定可看）；
  寫入（編輯訂閱/關注/立即更新）走 GitHub Contents API，需 fine-grained token（存瀏覽器）。
  owner/repo 由 Pages 網址自動判斷。
- **TLS**：本機 OpenSSL 3.6 預設開 `VERIFY_X509_STRICT`，591 憑證鏈缺 SKI 擴充會被拒。
  → 只關閉該嚴格擴充檢查，保留鏈結與主機名驗證（`list_scraper._build_ssl_context`）。
- **抓取策略**：逐區查詢（每個 section 各自查，避免多區共用 SSR 30 筆名額而稀釋），
  每區 **1 種排序**（posttime_desc）即可涵蓋（單區通常 <30），以減少請求數、降低被擋率。
- **比價**：一律用 `total_monthly = price + extra_fee`（有物件租金低但額外費用高，實際更貴）。
- **下架判定**：連續 `missing_rounds_before_removed`（預設 2）輪消失才判下架，避免暫時被擋誤判。

## 三、抗反爬 / 資料穩定機制（易踩雷，重點記錄）

- **重試 + 指數退避**：`fetch_list_html` 對失敗重試 `MAX_RETRIES`（4）次，
  等待 `REQUEST_INTERVAL_SEC * 2**attempt`＝ 4→8→16→32 秒（被擋時「多等一下」）。
- **逐區涵蓋追蹤（關鍵）**：`scrape_subscription` 回傳 `(listings, covered_districts)`；
  被擋（403 重試仍失敗）的 section 不列入 covered。
- **被擋的區資料原狀保留**：`diff_snapshots(..., covered_districts=...)`——
  消失的物件若其 district **不在** covered_districts，就**原狀保留、不算 missing、不判下架**。
  只有「該區有抓到、但物件確實不見」才累積 missing。
  → 局部被擋不影響整體、不誤刪、不整輪作廢；全被擋則等於本輪不動任何資料。
- 歷史備註：曾用「整輪筆數驟降 <70% 就中止」的粗略保險絲，後由上述**逐區保留**取代（更精準）。

## 四、已知限制

- 純 HTTP 只抓得到每區「最新那批」（SSR 視窗 ~30）；某區真正符合者若遠多於此會抓不全，
  需改用 **Playwright** 翻頁（重解法，未實作）。實測目前各區數字貼近 591。
- 衛數、平面車位費用、押金、最短租期等**只在物件內頁**，列表頁沒有；目前未抓內頁。
  車位僅以列表的「有車位/含車位」呈現。
- 相對時間換算誤差約一天內。

## 五、運維備註

- GitHub Actions 排程 bot **每輪都會 commit `data/`**，本機 push 常撞版；
  慣用解法：`git pull --rebase` 後解 `data/latest.json` 衝突（產生檔，取需要的一版）再 push。
- 「立即更新」用 `workflow_dispatch` API，token 需額外 **Actions: Read and write**。
- 改 workflow 檔（cron 頻率）若要從網頁做，token 需 **Workflows** 權限；目前走手動編輯 `monitor.yml`。

## 六、關鍵參數

| 參數 | 位置 | 值 |
|---|---|---|
| 請求間隔 | `config.REQUEST_INTERVAL_SEC` | 4 秒 |
| 重試次數 | `config.MAX_RETRIES` | 4（指數退避） |
| 每區排序 | `config.SECTION_SORTS` | `["posttime_desc"]` |
| 下架門檻 | `subscriptions.json` settings | 2 輪 |
| 排程頻率 | `.github/workflows/monitor.yml` | 每 3 小時（UTC cron） |

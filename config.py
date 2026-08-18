"""共用常數與路徑設定。"""
from pathlib import Path

# 591 端點
BASE_URL = "https://rent.591.com.tw"
LIST_URL = f"{BASE_URL}/list"

# 多排序聯集法用的排序清單（同一條件用多種 sort 各抓一次取聯集）
SORTS = ["posttime_desc", "money_asc", "money_desc", "area_asc", "area_desc"]

# 逐區查詢時每個區用的排序。單區通常 <30 筆，posttime 一次即可涵蓋；
# 只用一種排序可大幅減少請求數（降低 591 擋機房 IP 的機率、讓筆數更穩定）。
SECTION_SORTS = ["posttime_desc"]

# 城市代碼 → 名稱
REGION_NAMES = {"1": "台北市", "3": "新北市"}

# 類型代碼 → 名稱（591 列表頁的 kind_name 文字）
KIND_NAMES = {"1": "整層住家", "2": "獨立套房", "3": "分租套房", "4": "雅房"}

# 買屋（中古屋）類型代碼 → 名稱。9=住宅為主；其餘為店面/辦公等。
SALE_KIND_NAMES = {"9": "住宅", "5": "店面", "6": "辦公", "12": "住辦",
                   "11": "土地", "7": "廠房", "8": "車位"}
# 型態代碼沿用租屋 shape：1=公寓 2=電梯大樓 3=透天厝 4=別墅（買屋另有 5=華廈）
SHAPE_NAMES = {"1": "公寓", "2": "電梯大樓", "3": "透天厝", "4": "別墅", "5": "華廈"}

# 區域 section 代碼 → 行政區名稱（含「區」，對齊列表解析出的 district）
# 用於判斷「哪些區這輪真的有抓到」，被擋的區其資料不動、不誤判下架
SECTION_NAMES = {
    "3": {"26": "板橋區", "27": "汐止區", "28": "深坑區", "34": "新店區", "37": "永和區",
          "38": "中和區", "39": "土城區", "40": "三峽區", "41": "樹林區", "42": "鶯歌區",
          "43": "三重區", "44": "新莊區", "45": "泰山區", "46": "林口區", "47": "蘆洲區",
          "48": "五股區", "49": "八里區", "50": "淡水區"},
    "1": {"1": "中正區", "2": "大同區", "3": "中山區", "4": "松山區", "5": "大安區",
          "6": "萬華區", "7": "信義區", "8": "士林區", "9": "北投區", "10": "內湖區",
          "11": "南港區", "12": "文山區"},
}

# 反爬：請求間隔與重試
REQUEST_INTERVAL_SEC = 4  # 請求間隔；拉長較不易被 591 擋
REQUEST_TIMEOUT_SEC = 20
MAX_RETRIES = 4  # 591 對機房 IP 偶發 403；重試搭配指數退避（4→8→16→32 秒）多等一下
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# 路徑
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
LATEST_PATH = DATA_DIR / "latest.json"
SUBSCRIPTIONS_PATH = ROOT / "subscriptions.json"
WATCHLIST_PATH = ROOT / "watchlist.json"

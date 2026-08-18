// 從 591 列表頁 HTML 取出 window.__NUXT__ 裡的物件清單，輸出 JSON 陣列。
// 讀 stdin(HTML)、寫 stdout(JSON)。用 vm 沙箱 + timeout 執行那段 Nuxt IIFE。
const vm = require("vm");

let html = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (html += d));
process.stdin.on("end", () => {
  const m = html.match(/window\.__NUXT__=(\(function[\s\S]*?\}\([^;]*?\)\));?<\/script>/);
  if (!m) { process.stdout.write("[]"); return; }
  let nuxt;
  try {
    nuxt = vm.runInNewContext("(" + m[1] + ")", { window: {} }, { timeout: 5000 });
  } catch (e) {
    process.stderr.write("nuxt eval error: " + e);
    process.exit(2);
  }
  const isListing = (x) => x && typeof x === "object" && (("id" in x) || ("houseid" in x)) && ("price" in x);
  const longestListArray = (obj) => {
    let best = null;
    for (const k in obj) {
      const v = obj[k];
      if (Array.isArray(v) && v.length && isListing(v[0]) && (!best || v.length > best.length)) best = v;
    }
    return best;
  };

  let items = null, total = null;

  // 首選：pinia 的結果 store（rent-list / sale-list），鎖定真正的結果清單與其 total，
  // 避免抓到「猜你喜歡」推薦清單（結果少時 591 會用推薦填版面）。
  const pinia = nuxt && nuxt.pinia;
  if (pinia) {
    const storeKey = Object.keys(pinia).find((k) => /-list$/.test(k));
    const store = storeKey && pinia[storeKey];
    if (store) {
      items = store.wareList || store.dataList || longestListArray(store);
      for (const tk of ["total", "wareTotal", "records", "totalRows"]) {
        if (typeof store[tk] === "number") { total = store[tk]; break; }
      }
    }
  }

  // 後備：全域找最長的物件陣列（舊行為）
  if (!items) {
    (function walk(o, d) {
      if (!o || d > 10 || typeof o !== "object") return;
      if (Array.isArray(o) && o.length && isListing(o[0]) && (!items || o.length > items.length)) items = o;
      for (const k in o) { try { walk(o[k], d + 1); } catch (e) {} }
    })(nuxt, 0);
  }

  process.stdout.write(JSON.stringify({ items: items || [], total: total }));
});

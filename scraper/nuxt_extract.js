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
  // 找出「物件清單陣列」：元素是物件、且含 id 與 price 欄位，取最長的一個
  let best = null;
  (function walk(o, d) {
    if (!o || d > 9 || typeof o !== "object") return;
    if (Array.isArray(o) && o.length && o[0] && typeof o[0] === "object") {
      const ks = Object.keys(o[0]);
      // 租屋物件有 id、買屋物件有 houseid，皆含 price
      if ((ks.includes("id") || ks.includes("houseid")) && ks.includes("price") && (!best || o.length > best.length)) best = o;
    }
    for (const k in o) { try { walk(o[k], d + 1); } catch (e) {} }
  })(nuxt, 0);
  process.stdout.write(JSON.stringify(best || []));
});

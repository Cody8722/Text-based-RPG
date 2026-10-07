// 瀏覽器端到端：真的點介面玩一段。由 tests/test_ui_e2e.py 啟動伺服器後呼叫。
// 用法：node tests/ui_e2e.js http://127.0.0.1:PORT/ expectNarration(0|1)
const { chromium } = require("playwright");

(async () => {
  const base = process.argv[2];
  const expectNarration = process.argv[3] === "1";
  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/fonts\.g/.test(m.text())) errors.push(m.text()); });
  const fail = async (msg) => { console.log(JSON.stringify({ ok: false, msg, errors })); await browser.close(); process.exit(1); };

  await page.goto(base);
  await page.click("#btn-new");
  await page.waitForSelector(".bg-card");
  if ((await page.locator(".bg-card").count()) !== 3) await fail("expected 3 backgrounds");
  await page.locator(".bg-card").first().click();
  await page.waitForSelector("#game:not([hidden])");
  const turns0 = await page.locator(".turn").count();

  const click = async (selector) => {
    const btn = page.locator(selector).first();
    if (!(await btn.count())) return false;
    await btn.click();
    await page.waitForFunction(() => !document.querySelector("#actions button[disabled]:not(.closed)") || true);
    await page.waitForTimeout(250);
    return true;
  };
  // 移動、交談、寒暄、打聽
  await click('#actions button:has-text("長街")');
  for (let i = 0; i < 6; i++) {
    if (await click("#actions .person-btn")) {
      await click('#actions button:has-text("寒暄")');
      await click('#actions button:has-text("最近鎮上")');
      await click('#actions button:has-text("結束談話")');
    }
    const moves = page.locator('.group:has(.group-title:text("前往")) button:not(.closed)');
    const n = await moves.count();
    if (n) { await moves.nth(i % n).click(); await page.waitForTimeout(250); }
  }
  // 鍵盤快捷鍵
  await page.keyboard.press("1");
  await page.waitForTimeout(300);
  const turns = await page.locator(".turn").count();
  if (turns <= turns0 + 5) await fail(`story did not grow (${turns0} -> ${turns})`);
  if (expectNarration) {
    await page.waitForSelector(".k-narration", { timeout: 15000 }).catch(() => null);
    if (!(await page.locator(".k-narration").count())) await fail("LLM narration never appeared");
    await page.waitForFunction(() => !document.querySelector(".thinking"), null, { timeout: 15000 }).catch(() => null);
    if (await page.locator(".thinking").count()) await fail("a narration placeholder never resolved");
  }
  for (const tab of ["journal", "people", "deeds", "pack", "here"]) {
    await page.click(`#tabs button[data-tab=${tab}]`);
    if (await page.locator(`#tab-${tab}`).isHidden()) await fail(`tab ${tab} did not open`);
  }
  const journal = await page.locator("#tab-journal .jentry").count();
  // 介面上不能出現數字化的好感度或內部欄位
  const html = await page.content();
  for (const bad of ["opinion", "traits", "truth", "undefined", "NaN", "[object Object]"]) {
    if (html.includes(bad)) await fail(`page shows internal token: ${bad}`);
  }
  if (errors.length) await fail("page errors");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click("#drawer-btn");
  await page.waitForTimeout(300);
  const drawer = await page.locator("#side.open").count();
  console.log(JSON.stringify({ ok: true, turns, journal, drawer }));
  await browser.close();
})().catch((e) => { console.log(JSON.stringify({ ok: false, msg: String(e) })); process.exit(1); });

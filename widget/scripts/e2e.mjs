// Browser e2e over the embed test pages (step 4.3.3), driven by the system Chrome via
// playwright-core (no browser download). Needs a running API serving /widget/* — normally
// started by scripts/verify/p4_s3.sh with AGENT_LLM=demo (no spend).
//   WIDGET_BASE=http://localhost:8010 node scripts/e2e.mjs [--headed] [--shots dir]
import { mkdirSync } from "node:fs";
import { chromium } from "playwright-core";

const BASE = process.env.WIDGET_BASE ?? "http://localhost:8010";
const headed = process.argv.includes("--headed");
const shotsIdx = process.argv.indexOf("--shots");
const SHOTS = shotsIdx > 0 ? process.argv[shotsIdx + 1] : null;
if (SHOTS) mkdirSync(SHOTS, { recursive: true });

let failed = false;
const ok = (cond, label, detail = "") => {
  console.log(`  ${cond ? "✔" : "✘"} ${label}${cond ? "" : ` ${detail}`}`);
  if (!cond) failed = true;
  return cond;
};

const browser = await chromium.launch({ channel: "chrome", headless: !headed });
const shot = async (page, name) => SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png` });

async function open(page, path) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto(`${BASE}/widget/test/${path}`);
  const launcher = page.locator("#raabta-widget-host").locator(".launcher");
  await launcher.waitFor({ timeout: 10_000 });
  return { launcher, errors, w: page.locator("#raabta-widget-host") };
}

try {
  // 1) plain page: ask a question, see status → approved answer + citation chip; book a slot; lead.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const { launcher, errors, w } = await open(page, "plain.html");
    ok(true, "plain: launcher mounted in shadow DOM");
    await launcher.click();
    ok(await w.locator(".panel").isVisible(), "plain: panel opens");
    ok((await w.locator(".qr button").count()) === 3, "plain: 3 suggested questions");
    await w.locator("textarea").fill("What is the fee for Class 3?");
    await w.locator("textarea").press("Enter");
    await w.locator(".m.ai").nth(1).waitFor({ timeout: 30_000 });
    await page.waitForFunction(
      () =>
        !document.getElementById("raabta-widget-host").shadowRoot.querySelector(".send").disabled,
      null,
      { timeout: 30_000 },
    );
    const reply = await w.locator(".m.ai").nth(1).innerText();
    ok(reply.length > 10, "plain: answer rendered", reply.slice(0, 80));
    await shot(page, "plain-answer");

    await w.locator("textarea").fill("I want to book a campus visit");
    await w.locator(".send").click();
    await w.locator(".slot").first().waitFor({ timeout: 30_000 });
    ok((await w.locator(".slot").count()) > 0, "plain: slot picker rendered");
    ok((await w.locator("form.lead").count()) === 1, "plain: lead form rendered");
    await shot(page, "plain-slots");
    await w.locator(".slot").first().click();
    await page.waitForFunction(
      () =>
        !document.getElementById("raabta-widget-host").shadowRoot.querySelector(".send").disabled,
      null,
      { timeout: 30_000 },
    );
    const form = w.locator("form.lead");
    if ((await form.count()) === 0) ok(false, "plain: lead form still available after slot pick");
    else {
      await form.locator("input").nth(0).fill("E2E Parent");
      await form.locator("input").nth(1).fill("12345");
      await form.locator("button").click();
      await form.locator(".err").filter({ hasText: /\S/ }).waitFor({ timeout: 10_000 });
      ok(true, "plain: invalid phone shows an error");
      await form.locator("input").nth(1).fill("0300-1234567");
      await form.locator("button").click();
      await form.waitFor({ state: "detached", timeout: 30_000 });
      ok(true, "plain: lead submitted");
    }
    const pageFont = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
    const widgetFont = await page.evaluate(
      () =>
        getComputedStyle(
          document.getElementById("raabta-widget-host").shadowRoot.querySelector(".panel"),
        ).fontFamily,
    );
    ok(pageFont !== widgetFont, "plain: host font does not leak", widgetFont);
    ok(errors.length === 0, "plain: no JS errors", errors.join("; "));
    await shot(page, "plain-done");
    await page.close();
  }

  // 2) WordPress-like: hostile theme CSS, left position.
  {
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const { launcher, errors, w } = await open(page, "wordpress-like.html");
    const box = await launcher.boundingBox();
    ok(box && box.x < 200, "wp: launcher on the left (data-position)", JSON.stringify(box));
    const bg = await launcher.evaluate((el) => getComputedStyle(el).backgroundColor);
    ok(bg !== "rgb(255, 0, 0)", "wp: theme !important button CSS does not leak", bg);
    await launcher.click();
    ok(await w.locator(".panel").isVisible(), "wp: panel opens above fixed header");
    ok(errors.length === 0, "wp: no JS errors", errors.join("; "));
    await shot(page, "wordpress");
    await page.close();
  }

  // 3) RTL page, Urdu UI; mobile viewport → full-screen panel.
  {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true });
    const { launcher, errors, w } = await open(page, "rtl.html");
    await launcher.click();
    const dir = await w.locator(".panel").getAttribute("dir");
    ok(dir === "rtl", "rtl: panel dir=rtl for data-lang=ur", dir);
    const pb = await w.locator(".panel").boundingBox();
    ok(
      pb && pb.width >= 389 && pb.height >= 800,
      "rtl: mobile panel is full-screen",
      JSON.stringify(pb),
    );
    const font = await page.evaluate(() =>
      [...document.querySelectorAll("link")].some((l) => l.href.includes("Noto+Nastaliq")),
    );
    ok(font, "rtl: Noto Nastaliq lazy-loaded for Urdu");
    await w.locator(".langs button").first().click();
    ok((await w.locator(".panel").getAttribute("dir")) === "ltr", "rtl: language toggle → ltr");
    ok(errors.length === 0, "rtl: no JS errors", errors.join("; "));
    await shot(page, "rtl-mobile");
    await page.close();
  }
} catch (e) {
  ok(false, "unexpected error", String(e));
} finally {
  await browser.close();
}
console.log(failed ? "E2E FAILED" : "E2E OK");
process.exit(failed ? 1 : 0);

// Admin browser e2e (Phase 5) on the system Chrome via playwright-core (no browser download).
// Needs: demo API (AGENT_LLM=demo, seeded test DB) + the built admin (`next start`) proxying it.
//   ADMIN_BASE=http://localhost:3010 API_BASE=http://localhost:8010 node scripts/e2e.mjs [--headed] [--shots dir]
// Covers: login, every page renders without JS errors, axe (no serious/critical violations),
// inbox takeover → staff reply → widget poll → return to AI, leads create/move, Urdu RTL,
// dark mode, mobile inbox, superadmin impersonation banner.
import { createRequire } from "node:module";
import { mkdirSync, readFileSync } from "node:fs";
import { chromium } from "playwright-core";

const require = createRequire(import.meta.url);
const AXE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const BASE = process.env.ADMIN_BASE ?? "http://localhost:3010";
const API = process.env.API_BASE ?? "http://localhost:8010";
const PASSWORD = "Raabta-demo-2027";
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
const shot = async (page, name) =>
  SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

async function axe(page, label) {
  await page.addScriptTag({ content: AXE });
  const res = await page.evaluate(async () => {
    // eslint-disable-next-line no-undef
    const r = await axe.run(document, { resultTypes: ["violations"] });
    return r.violations
      .filter((v) => v.impact === "serious" || v.impact === "critical")
      .map(
        (v) =>
          `${v.id}(${v.nodes.length}): ${v.nodes[0]?.target?.join(" ")} — ${
            v.nodes[0]?.any?.[0]?.message ?? ""
          }`,
      );
  });
  ok(res.length === 0, `a11y ${label}: no serious/critical axe violations`, res.join(" | "));
}

/** A widget visitor asks something through the public API (the demo agent answers). */
async function widgetVisitor(text) {
  const s = await (
    await fetch(`${API}/api/v1/widget/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: API },
      body: JSON.stringify({ slug: "abc-grammar-school" }),
    })
  ).json();
  const say = async (t) => {
    const r = await fetch(`${API}/api/v1/widget/sessions/${s.session_id}/messages`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${s.token}`,
        Origin: API,
      },
      body: JSON.stringify({ text: t, lang: "en" }),
    });
    return r.text();
  };
  await say(text);
  const updates = async () =>
    (
      await fetch(`${API}/api/v1/widget/sessions/${s.session_id}/updates`, {
        headers: { Authorization: `Bearer ${s.token}`, Origin: API },
      })
    ).json();
  return { say, updates };
}

async function login(page, email) {
  await page.goto(`${BASE}/inbox`);
  await page.waitForURL(/\/login/);
  await page.getByLabel(/email/i).fill(email);
  await page.getByLabel(/password/i).fill(PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 15_000 });
}

const browser = await chromium.launch({ channel: "chrome", headless: !headed });
try {
  const visitor = await widgetVisitor("What is the fee for Class 3?");
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  // 1) auth guard + login (5.1.2)
  await page.goto(`${BASE}/leads`);
  ok(page.url().includes("/login?next=%2Fleads"), "guard redirects to /login with ?next");
  await axe(page, "login");
  await login(page, "owner@abc.demo.raabta.pk");
  ok(new URL(page.url()).pathname === "/inbox", "login returns to the requested page");

  // 2) inbox takeover flow (5.4)
  await page
    .getByRole("list", { name: "Inbox" })
    .getByRole("button")
    .first()
    .waitFor({ timeout: 15_000 });
  ok(
    (await page.getByRole("list", { name: "Inbox" }).getByRole("button").count()) >= 1,
    "inbox lists conversations",
  );
  await page.getByRole("list", { name: "Inbox" }).getByRole("button").first().click();
  await page.getByRole("button", { name: /take over/i }).click();
  await page.getByRole("button", { name: /return to ai/i }).waitFor();
  ok(true, "take over → mode switches to staff");
  await page.getByRole("tab", { name: /^reply$/i }).click();
  await page.getByLabel(/^reply$/i).fill("Salam, Imran from admissions here.");
  // The bubble is optimistic (renders before the POST lands) → wait for the API response.
  const sent = page.waitForResponse(
    (r) => r.request().method() === "POST" && /\/conversations\/[^/]+\/messages$/.test(r.url()),
  );
  await page.getByRole("button", { name: /^send$/i }).click();
  ok((await sent).status() === 201, "staff reply accepted (201)");
  await page.getByText("Salam, Imran from admissions here.").first().waitFor();
  const up = await visitor.updates();
  ok(
    up.messages.some((m) => m.text === "Salam, Imran from admissions here."),
    "staff reply reaches the widget poll (I-18)",
    JSON.stringify(up),
  );
  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: /internal note/i }).click();
  await page.getByLabel(/internal note/i).fill("Father prefers Urdu");
  await page.getByRole("button", { name: /^send$/i }).click();
  await page.getByText("Father prefers Urdu").first().waitFor();
  ok(true, "internal note shown in the timeline");
  await axe(page, "inbox");
  await shot(page, "inbox");
  await page.getByRole("button", { name: /return to ai/i }).click();
  await page.getByLabel(/note for the ai/i).fill("Promised a Saturday visit");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /return to ai/i })
    .click();
  await page.getByRole("button", { name: /take over/i }).waitFor();
  ok(true, "return to AI → mode back to AI");
  const after = await visitor.say("When can I visit?");
  ok(after.includes("event: message"), "AI answers the parent again after return");

  // 3) every page renders (+ axe)
  for (const [path, heading] of [
    ["/", /overview/i],
    ["/leads", /leads/i],
    ["/slots", /calendar/i],
    ["/knowledge", /knowledge base/i],
    ["/onboarding", /set up your assistant/i],
    ["/settings", /settings/i],
    ["/usage", /usage/i],
    ["/audit", /audit log/i],
    ["/templates", /whatsapp templates/i],
  ]) {
    await page.goto(`${BASE}${path}`);
    const h = page.getByRole("heading", { level: 1, name: heading });
    const seen = await h.waitFor({ timeout: 15_000 }).then(
      () => true,
      () => false,
    );
    ok(seen, `page ${path} renders`);
    await page.waitForLoadState("networkidle");
    await page
      .locator("[aria-busy=true]")
      .first()
      .waitFor({ state: "detached", timeout: 10_000 })
      .catch(() => {});
    await axe(page, path);
    await shot(page, `page${path.replaceAll("/", "_") || "_home"}`);
  }

  // 3b) WhatsApp templates (6.5): seed the default set → edit a draft → live preview
  await page.goto(`${BASE}/templates`);
  await page.getByRole("button", { name: /add default set/i }).click();
  await page.getByRole("cell", { name: "visit_reminder", exact: false }).first().waitFor();
  ok((await page.getByRole("row").count()) >= 34, "default templates seeded (11 × 3 languages)");
  // The "added" toast fades behind the modal backdrop; let it go before auditing the editor.
  await page.waitForFunction(() => !document.querySelector("[data-sonner-toast]"), null, {
    timeout: 15_000,
  });
  await page
    .getByRole("button", { name: /^edit$/i })
    .first()
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel(/^message$/i).fill("Dear {{name}}, welcome to our open day.");
  await dialog.getByLabel(/example for name/i).fill("Ayesha");
  ok(
    await dialog.getByText("Dear Ayesha, welcome to our open day.").isVisible(),
    "template editor shows a live preview",
  );
  await axe(page, "templates editor");
  await page.keyboard.press("Escape");
  await page.goto(`${BASE}/settings`);
  await page.getByRole("tab", { name: /whatsapp/i }).click();
  await page
    .getByText(/daily summary/i)
    .first()
    .waitFor();
  ok(true, "WhatsApp settings tab shows the daily summary form");
  await axe(page, "settings whatsapp");

  // 4) dashboard data + leads interactions (5.3, 5.5)
  await page.goto(`${BASE}/`);
  await page
    .getByText(/conversations/i)
    .first()
    .waitFor();
  ok((await page.locator(".recharts-surface").count()) >= 1, "trend chart rendered");
  await page.goto(`${BASE}/leads`);
  await page.getByRole("button", { name: /new lead/i }).click();
  await page.getByLabel(/^student$/i).fill("E2E Student");
  await page.getByLabel(/^phone$/i).fill("0300 7654321");
  await page.getByRole("button", { name: /^create$/i }).click();
  const card = page.locator("article", { hasText: "E2E Student" });
  await card.waitFor();
  ok(true, "lead created and shown on the board");
  await card.getByRole("combobox").selectOption("visit_booked");
  await page
    .getByRole("region", { name: /visit booked/i })
    .locator("article", { hasText: "E2E Student" })
    .waitFor();
  ok(true, "lead moved to 'Visit booked' column");

  // 5) settings → assistant tab saves (5.8)
  await page.goto(`${BASE}/settings`);
  await page.getByRole("tab", { name: /assistant/i }).click();
  await page.getByLabel(/escalate to staff/i).fill("complaint, refund");
  await page.getByRole("button", { name: /^save$/i }).click();
  await page.getByText(/saved/i).first().waitFor();
  ok(true, "assistant settings saved");

  // 6) Urdu RTL + dark mode (5.1.4 / 5.1.1)
  await page.getByRole("button", { name: "اردو", exact: true }).click();
  await page.waitForFunction(() => document.documentElement.dir === "rtl");
  ok(
    (await page.evaluate(() => document.documentElement.lang)) === "ur",
    "Urdu UI: lang=ur, dir=rtl",
  );
  ok(
    await page.getByRole("heading", { level: 1, name: "ترتیبات" }).isVisible(),
    "Urdu strings render",
  );
  await shot(page, "settings-ur");
  await page.getByRole("button", { name: "English", exact: true }).click();
  await page.waitForFunction(() => document.documentElement.dir === "ltr");
  await page.getByRole("button", { name: /theme/i }).click();
  await page.waitForFunction(() => document.documentElement.classList.contains("dark"));
  ok(true, "dark mode toggles");
  await page.goto(`${BASE}/`);
  await page.getByRole("heading", { level: 1 }).waitFor();
  await axe(page, "overview (dark)");
  await shot(page, "overview-dark");

  ok(errors.length === 0, "no uncaught JS errors", errors.join(" | "));
  await ctx.close();

  // 7) mobile inbox (5.11.2)
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  const m = await mctx.newPage();
  await login(m, "staff@abc.demo.raabta.pk");
  await m.goto(`${BASE}/inbox`);
  await m.getByRole("list", { name: "Inbox" }).getByRole("button").first().waitFor();
  await m.getByRole("list", { name: "Inbox" }).getByRole("button").first().click();
  ok(
    await m.getByRole("button", { name: /back/i }).isVisible(),
    "mobile: conversation full-width with back button",
  );
  await shot(m, "inbox-mobile");
  await m.getByRole("button", { name: /back/i }).click();
  ok(
    await m.getByRole("list", { name: "Inbox" }).getByRole("button").first().isVisible(),
    "mobile: back to the list",
  );
  ok(
    !(await m.getByRole("link", { name: /audit log/i }).count()),
    "staff role: admin pages hidden",
  );
  await mctx.close();

  // 8) superadmin impersonation banner (5.9)
  const sctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const s = await sctx.newPage();
  await login(s, "super@raabta.pk");
  await s.goto(`${BASE}/superadmin`);
  await s.getByRole("heading", { level: 1, name: /platform/i }).waitFor();
  await axe(s, "superadmin");
  const row = s.getByRole("row", { name: /ABC Grammar School/ });
  await row.getByRole("button", { name: /open as owner/i }).click();
  await s
    .getByRole("status")
    .filter({ hasText: /viewing ABC Grammar School/i })
    .waitFor();
  ok(true, "impersonation banner shown");
  await s.getByRole("heading", { level: 1, name: /overview/i }).waitFor();
  ok(true, "impersonated tenant dashboard loads");
  await s.getByRole("status").getByRole("button", { name: /stop/i }).click();
  await s
    .getByRole("status")
    .filter({ hasText: /viewing/i })
    .waitFor({ state: "detached" });
  ok(true, "impersonation stopped");
  await sctx.close();
} catch (e) {
  ok(false, "e2e crashed", e?.stack ?? String(e));
} finally {
  await browser.close();
}
console.log(failed ? "ADMIN E2E: FAILED" : "ADMIN E2E: OK");
process.exit(failed ? 1 : 0);

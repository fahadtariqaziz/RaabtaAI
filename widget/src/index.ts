/**
 * RaabtaAI embeddable widget (PLAN §15.1).
 * <script src="https://…/widget/v1/widget.js" data-institution="slug" async></script>
 * Optional: data-lang (en|ur|roman_ur), data-position (left|right), data-primary (#rrggbb),
 * data-api (API origin; defaults to the script's origin), data-open (auto-open the panel).
 */
import { WidgetApi } from "./api";
import { Widget } from "./ui";

const HOST_ID = "raabta-widget-host";
// Must be read synchronously at load time — currentScript is null inside later callbacks.
const SCRIPT = document.currentScript as HTMLScriptElement | null;

async function mount(): Promise<void> {
  if (document.getElementById(HOST_ID)) return; // idempotent: never mount twice
  const ds = SCRIPT?.dataset ?? {};
  const slug = ds.institution ?? "";
  if (!slug) return;
  const base = (ds.api ?? (SCRIPT?.src ? new URL(SCRIPT.src).origin : location.origin)).replace(
    /\/$/,
    "",
  );
  const api = new WidgetApi(base, slug);
  let cfg;
  try {
    cfg = await api.config();
  } catch {
    return; // unknown/suspended institution or API down — render nothing
  }
  if (ds.primary && /^#[0-9a-f]{6}$/i.test(ds.primary)) cfg.theme.primary = ds.primary;
  if (ds.position === "left" || ds.position === "right") cfg.theme.position = ds.position;

  const host = document.createElement("div");
  host.id = HOST_ID;
  host.dataset.institution = slug;
  // Shadow DOM isolates our styles from the host site's CSS (and vice versa).
  const shadow = host.attachShadow({ mode: "open" });
  document.body.appendChild(host);
  const widget = new Widget(shadow, cfg, api, ds.lang);
  widget.mount();
  if (ds.open !== undefined) widget.toggle(true);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => void mount(), { once: true });
} else {
  void mount();
}

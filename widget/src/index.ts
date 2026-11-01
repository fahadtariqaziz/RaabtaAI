/**
 * RaabtaAI embeddable widget (placeholder — real UI lands in HANDOFF step 4.2).
 * Usage: <script src=".../widget.js" data-institution="slug" async></script>
 */
const HOST_ID = "raabta-widget-host";
// Must be read synchronously at load time — currentScript is null inside later callbacks.
const SCRIPT = document.currentScript as HTMLScriptElement | null;

function mount(): void {
  if (document.getElementById(HOST_ID)) return; // idempotent: never mount twice
  const institution = SCRIPT?.dataset.institution ?? "";

  const host = document.createElement("div");
  host.id = HOST_ID;
  host.dataset.institution = institution;
  // Shadow DOM isolates our styles from the host site's CSS (and vice versa).
  host.attachShadow({ mode: "open" });
  document.body.appendChild(host);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mount, { once: true });
} else {
  mount();
}

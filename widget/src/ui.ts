import { HttpError, type ServerEvent, type Slot, type WidgetApi, type WidgetConfig } from "./api";
import { LANG_LABEL, type Lang, isRtl, loadUrduFont, t } from "./i18n";
import { renderMarkdown, reveal } from "./render";
import { CSS } from "./styles";

interface Line {
  role: "me" | "ai";
  text: string;
}

const CHAT_ICON =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>';

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls = "",
  text = "",
): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

export class Widget {
  private lang: Lang;
  private busy = false;
  private lines: Line[] = [];
  private leadDone = false;
  private pendingSlot: string | null = null;
  private store: string;
  private root = el("div", "root");
  private panel = el("div", "panel hidden");
  private launcher = el("button", "launcher");
  private title = el("div", "n");
  private sub = el("div", "s");
  private langs = el("div", "langs");
  private log = el("div", "log");
  private input = el("textarea");
  private sendBtn = el("button", "send");
  private waBtn = el("button", "wa");
  private powered = el("div", "pw");
  private closeBtn = el("button", "x", "×");
  private statusEl: HTMLElement | null = null;

  constructor(
    private shadow: ShadowRoot,
    private cfg: WidgetConfig,
    private api: WidgetApi,
    lang: string | undefined,
  ) {
    this.store = `raabta-chat:${cfg.slug}`;
    this.lang = cfg.languages.includes(lang as Lang) ? (lang as Lang) : cfg.default_language;
    try {
      const saved = JSON.parse(sessionStorage.getItem(this.store) ?? "null") as {
        lines: Line[];
        leadDone: boolean;
      } | null;
      if (saved) ({ lines: this.lines, leadDone: this.leadDone } = saved);
    } catch {
      /* ignore */
    }
  }

  mount(): void {
    const style = el("style");
    style.textContent = CSS;
    this.root.style.setProperty("--p", this.cfg.theme.primary);
    if (this.cfg.theme.position === "left") this.root.classList.add("left");

    this.launcher.innerHTML = CHAT_ICON; // static markup, no external data
    this.launcher.addEventListener("click", () => this.toggle());

    const head = el("div", "head");
    const tbox = el("div", "t");
    tbox.append(this.title, this.sub);
    this.closeBtn.addEventListener("click", () => this.toggle(false));
    head.append(tbox, this.langs, this.closeBtn);

    this.log.setAttribute("aria-live", "polite");
    this.panel.setAttribute("role", "dialog");
    this.panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") this.toggle(false);
    });

    const foot = el("div", "foot");
    this.input.rows = 1;
    this.input.maxLength = 1000;
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.submit();
      }
    });
    this.sendBtn.addEventListener("click", () => this.submit());
    foot.append(this.input, this.sendBtn);
    this.waBtn.classList.toggle("hidden", !this.cfg.whatsapp);
    this.waBtn.addEventListener("click", () => void this.openWhatsApp());

    this.panel.append(head, this.log, foot, this.waBtn, this.powered);
    this.root.append(this.panel, this.launcher);
    this.shadow.append(style, this.root);
    this.applyLang();
    this.renderLog();
  }

  private persist(): void {
    try {
      sessionStorage.setItem(
        this.store,
        JSON.stringify({ lines: this.lines.slice(-40), leadDone: this.leadDone }),
      );
    } catch {
      /* ignore */
    }
  }

  toggle(open = this.panel.classList.contains("hidden")): void {
    this.panel.classList.toggle("hidden", !open);
    this.launcher.setAttribute("aria-expanded", String(open));
    if (open) this.input.focus();
    else this.launcher.focus();
  }

  private applyLang(): void {
    const l = this.lang;
    if (isRtl(l)) loadUrduFont();
    this.panel.classList.toggle("rtl", isRtl(l));
    this.panel.setAttribute("dir", isRtl(l) ? "rtl" : "ltr");
    this.panel.setAttribute("aria-label", `${this.cfg.name} — ${t("title", l)}`);
    this.launcher.setAttribute("aria-label", t("open", l));
    this.closeBtn.setAttribute("aria-label", t("close", l));
    this.title.textContent = this.cfg.name;
    this.sub.textContent = t("title", l);
    this.input.placeholder = t("placeholder", l);
    this.sendBtn.textContent = t("send", l);
    this.waBtn.textContent = t("whatsapp", l);
    this.powered.textContent = t("powered", l);
    this.langs.replaceChildren(
      ...this.cfg.languages.map((code) => {
        const b = el("button", "", LANG_LABEL[code]);
        b.setAttribute("aria-pressed", String(code === l));
        b.addEventListener("click", () => {
          this.lang = code;
          this.applyLang();
          if (!this.lines.length) this.renderLog();
        });
        return b;
      }),
    );
  }

  private renderLog(): void {
    this.log.replaceChildren();
    if (!this.lines.length) {
      const welcome = this.cfg.welcome[this.lang];
      if (welcome) this.bubble("ai", welcome);
      this.quickReplies(this.cfg.suggested_questions[this.lang] ?? []);
      return;
    }
    for (const line of this.lines) this.bubble(line.role, line.text);
  }

  private scroll(): void {
    this.log.scrollTop = this.log.scrollHeight;
  }

  private bubble(role: "me" | "ai", text: string): HTMLElement {
    const b = el("div", `m ${role}`);
    if (role === "ai") b.append(renderMarkdown(text));
    else b.textContent = text;
    this.log.appendChild(b);
    this.scroll();
    return b;
  }

  private setStatus(text: string | null): void {
    if (text === null) {
      this.statusEl?.remove();
      this.statusEl = null;
      return;
    }
    if (!this.statusEl) {
      this.statusEl = el("div", "status");
      this.log.appendChild(this.statusEl);
    }
    const dots = el("span", "dots");
    dots.append(el("span"), el("span"), el("span"));
    this.statusEl.replaceChildren(dots, document.createTextNode(text));
    this.scroll();
  }

  private quickReplies(items: string[]): void {
    if (!items.length) return;
    const box = el("div", "qr");
    for (const q of items) {
      const b = el("button", "", q);
      b.addEventListener("click", () => {
        box.remove();
        void this.send(q);
      });
      box.appendChild(b);
    }
    this.log.appendChild(box);
    this.scroll();
  }

  private slots(list: Slot[]): void {
    const card = el("div", "card");
    const wrap = el("div", "slots");
    for (const s of list.slice(0, 8)) {
      const b = el("button", "slot", s.label);
      b.addEventListener("click", () => {
        card.remove();
        this.pendingSlot = s.slot_time;
        void this.send(t("iWant", this.lang, { slot: s.label }));
      });
      wrap.appendChild(b);
    }
    card.append(el("h4", "", t("pickSlot", this.lang)), wrap);
    this.log.appendChild(card);
    this.scroll();
  }

  private leadForm(): void {
    if (this.leadDone || this.log.querySelector(".lead")) return;
    const card = el("form", "card lead");
    const name = el("input");
    const phone = el("input");
    const err = el("div", "err");
    const btn = el("button", "primary", t("submit", this.lang));
    name.placeholder = t("name", this.lang);
    name.required = true;
    name.maxLength = 120;
    name.autocomplete = "name";
    phone.placeholder = t("phone", this.lang);
    phone.required = true;
    phone.type = "tel";
    phone.maxLength = 32;
    phone.autocomplete = "tel";
    btn.type = "submit";
    card.append(el("h4", "", t("leadTitle", this.lang)), name, phone, err, btn);
    card.addEventListener("submit", (e) => {
      e.preventDefault();
      btn.disabled = true;
      this.api
        .lead({ name: name.value.trim(), phone: phone.value.trim() })
        .then(() => {
          this.leadDone = true;
          this.persist();
          card.remove();
          if (this.pendingSlot) {
            this.pendingSlot = null;
            void this.send(
              t("myDetails", this.lang, { name: name.value.trim(), phone: phone.value.trim() }),
            );
          } else {
            this.bubble("ai", t("thanks", this.lang));
          }
        })
        .catch((x: unknown) => {
          btn.disabled = false;
          err.textContent =
            x instanceof HttpError && x.status === 422
              ? t("badPhone", this.lang)
              : t("error", this.lang);
        });
    });
    this.log.appendChild(card);
    this.scroll();
  }

  private citations(
    b: HTMLElement,
    cites: { title: string; page: number | null; quote: string | null }[],
  ): void {
    const box = el("div", "cites");
    for (const c of cites) {
      const label = c.page ? `${c.title}, ${t("page", this.lang)} ${c.page}` : c.title;
      const chip = el("button", "chip", `${t("source", this.lang)}: ${label}`);
      chip.setAttribute("aria-expanded", "false");
      chip.addEventListener("click", () => {
        const open = b.querySelector(".quote");
        if (open) {
          open.remove();
          chip.setAttribute("aria-expanded", "false");
        } else if (c.quote) {
          b.appendChild(el("div", "quote", c.quote));
          chip.setAttribute("aria-expanded", "true");
        }
      });
      box.appendChild(chip);
    }
    b.appendChild(box);
  }

  private submit(): void {
    const text = this.input.value.trim();
    if (!text || this.busy) return;
    this.input.value = "";
    void this.send(text);
  }

  private setBusy(v: boolean): void {
    this.busy = v;
    this.sendBtn.disabled = v;
  }

  async send(text: string): Promise<void> {
    if (this.busy) return;
    this.setBusy(true);
    this.log.querySelectorAll(".qr").forEach((n) => n.remove());
    this.bubble("me", text);
    this.lines.push({ role: "me", text });
    this.persist();
    let aiBubble: HTMLElement | null = null;
    let revealed: Promise<void> = Promise.resolve();
    const after = (fn: () => void): void => {
      revealed = revealed.then(fn);
    };
    const onEvent = (e: ServerEvent): void => {
      switch (e.type) {
        case "status":
          if (e.human) {
            this.setStatus(null);
            this.bubble("ai", e.text);
          } else this.setStatus(e.text);
          break;
        case "message": {
          this.setStatus(null);
          const b = el("div", "m ai");
          const body = el("div");
          b.appendChild(body);
          this.log.appendChild(b);
          aiBubble = b;
          this.lines.push({ role: "ai", text: e.text });
          this.persist();
          revealed = new Promise((res) => reveal(body, e.text, () => (this.scroll(), res())));
          break;
        }
        case "citation":
          after(() => aiBubble && this.citations(aiBubble, e.citations));
          break;
        case "slots":
          after(() => this.slots(e.slots));
          break;
        case "quick_replies":
          after(() => this.quickReplies(e.items));
          break;
        case "lead_form":
          after(() => this.leadForm());
          break;
        case "error":
          this.setStatus(null);
          this.bubble("ai", e.text);
          break;
        case "done":
          break;
      }
    };
    try {
      this.setStatus("…");
      await this.api.send(text, this.lang, onEvent);
    } catch (x) {
      this.setStatus(null);
      this.bubble(
        "ai",
        t(x instanceof HttpError && x.status === 429 ? "busy" : "error", this.lang),
      );
    } finally {
      this.setStatus(null);
      await revealed;
      this.setBusy(false);
      this.scroll();
    }
  }

  private async openWhatsApp(): Promise<void> {
    try {
      window.open(await this.api.whatsappLink(this.lang), "_blank", "noopener");
    } catch {
      this.bubble("ai", t("error", this.lang));
    }
  }
}

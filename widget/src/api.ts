/** Public widget API client (`/api/v1/widget/*`). Only the visitor id and the session token are
 * persisted in localStorage (PLAN §15.1: no other PII there). */
import { SseParser } from "./sse";
import type { Lang } from "./i18n";

export interface WidgetConfig {
  slug: string;
  name: string;
  type: string;
  languages: Lang[];
  default_language: Lang;
  theme: { primary: string; position: "left" | "right" };
  welcome: Partial<Record<Lang, string>>;
  suggested_questions: Partial<Record<Lang, string[]>>;
  whatsapp: boolean;
}

interface Session {
  session_id: string;
  token: string;
  visitor_id: string;
  expires_at: string;
}

export type ServerEvent =
  | { type: "status"; text: string; tool?: string; human?: boolean }
  | { type: "message"; id: string | null; text: string; language: string; kind: string }
  | { type: "citation"; citations: { title: string; page: number | null; quote: string | null }[] }
  | { type: "quick_replies"; items: string[] }
  | { type: "slots"; kind: string; slots: Slot[] }
  | { type: "lead_form"; fields: string[] }
  | { type: "error"; text: string }
  | { type: "done"; status: string };

export interface Slot {
  slot_time: string;
  label: string;
  location: string | null;
  seats_left: number;
}

export class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const STORE_PREFIX = "raabta:";

function load(slug: string): Session | null {
  try {
    const raw = localStorage.getItem(STORE_PREFIX + slug);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function save(slug: string, s: Session): void {
  try {
    localStorage.setItem(STORE_PREFIX + slug, JSON.stringify(s));
  } catch {
    /* storage disabled (Safari private mode) — session lives in memory only */
  }
}

export class WidgetApi {
  private session: Session | null;

  constructor(
    private base: string,
    private slug: string,
  ) {
    this.session = load(slug);
  }

  private url(path: string): string {
    return `${this.base}/api/v1/widget${path}`;
  }

  async config(): Promise<WidgetConfig> {
    const r = await fetch(this.url(`/config/${encodeURIComponent(this.slug)}`));
    if (!r.ok) throw new HttpError(r.status, "config");
    return (await r.json()) as WidgetConfig;
  }

  private async ensureSession(force = false): Promise<Session> {
    const s = this.session;
    const fresh = s && Date.parse(s.expires_at) - Date.now() > 5 * 60_000;
    if (s && fresh && !force) return s;
    const r = await fetch(this.url("/sessions"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: this.slug, visitor_id: s?.visitor_id ?? null }),
    });
    if (!r.ok) throw new HttpError(r.status, "session");
    const next = (await r.json()) as Session;
    this.session = next;
    save(this.slug, next);
    return next;
  }

  private async authed(path: string, init: RequestInit, retry = true): Promise<Response> {
    const s = await this.ensureSession();
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${s.token}`);
    const r = await fetch(this.url(`/sessions/${s.session_id}${path}`), { ...init, headers });
    if (r.status === 401 && retry) {
      await this.ensureSession(true);
      return this.authed(path, init, false);
    }
    return r;
  }

  /** Sends a message and calls `onEvent` for every SSE event until `done`. */
  async send(text: string, lang: Lang, onEvent: (e: ServerEvent) => void): Promise<void> {
    const r = await this.authed("/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ text, lang, client_msg_id: crypto.randomUUID?.() ?? null }),
    });
    if (!r.ok || !r.body) throw new HttpError(r.status, "send");
    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const ev of parser.push(decoder.decode(value, { stream: true }))) {
        try {
          onEvent({ type: ev.event, ...JSON.parse(ev.data) } as ServerEvent);
        } catch {
          /* malformed event — ignore */
        }
      }
    }
  }

  async lead(body: { name: string; phone: string; interest?: string }): Promise<void> {
    const r = await this.authed("/lead", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new HttpError(r.status, "lead");
  }

  async whatsappLink(lang: Lang): Promise<string> {
    const r = await this.authed(`/whatsapp-link?lang=${lang}`, { method: "GET" });
    if (!r.ok) throw new HttpError(r.status, "whatsapp");
    return ((await r.json()) as { url: string }).url;
  }
}

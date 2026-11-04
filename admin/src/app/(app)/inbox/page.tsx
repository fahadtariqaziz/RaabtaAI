"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Bot,
  CheckCheck,
  Flag,
  Globe,
  MessageCircle,
  Radio,
  RotateCcw,
  Search,
  StickyNote,
  UserRound,
  Wrench,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyState, NativeSelect, Pill, QueryView, SkeletonRows } from "@/components/common";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useAuth, useMe } from "@/lib/auth";
import { fmtDateTime, fmtRelative, fmtTime } from "@/lib/format";
import { useInboxEvents } from "@/lib/hooks/use-inbox-events";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Row = Schemas["ConversationRow"];
type Detail = Schemas["ConversationDetail"];
type Msg = Schemas["MessageOut"];
type Filters = {
  mode?: "ai" | "human";
  channel?: "widget" | "whatsapp";
  assigned?: "me" | "unassigned";
  flagged?: boolean;
  awaiting?: boolean;
  status?: "open" | "pending" | "closed";
  q?: string;
};

function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

export default function InboxPage() {
  const t = useTranslations("inbox");
  const { institutionId } = useAuth();
  const live = useInboxEvents(institutionId);
  const [filters, setFilters] = useState<Filters>({});
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const composerRef = useRef<{ focus: (mode: "reply" | "note") => void; takeover: () => void }>(
    null,
  );

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const f: Filters = {};
    if (p.get("mode") === "human") f.mode = "human";
    if (p.get("flagged")) f.flagged = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial filters from the URL
    if (Object.keys(f).length) setFilters(f);
  }, []);

  useEffect(() => {
    const h = setTimeout(() => setFilters((f) => ({ ...f, q: search.trim() || undefined })), 300);
    return () => clearTimeout(h);
  }, [search]);

  const list = useQuery({
    queryKey: ["conversations", institutionId, filters],
    queryFn: () => unwrap(api.GET("/api/v1/conversations", { params: { query: filters } })),
    enabled: !!institutionId,
    refetchInterval: live ? false : 20_000,
  });
  const rows = useMemo(() => list.data ?? [], [list.data]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      const i = rows.findIndex((r) => r.id === selected);
      if (e.key === "j" && rows.length) setSelected(rows[Math.min(i + 1, rows.length - 1)].id);
      else if (e.key === "k" && rows.length) setSelected(rows[Math.max(i - 1, 0)].id);
      else if (e.key === "r" && selected) composerRef.current?.focus("reply");
      else if (e.key === "n" && selected) composerRef.current?.focus("note");
      else if (e.key === "t" && selected) composerRef.current?.takeover();
      else return;
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, selected]);

  const toggle = (key: "flagged" | "awaiting") =>
    setFilters((f) => ({ ...f, [key]: f[key] ? undefined : true }));

  return (
    <div className="-m-4 flex h-[calc(100dvh-3.5rem)] md:-m-6">
      {/* list pane */}
      <section
        aria-label={t("title")}
        className={cn(
          "flex w-full flex-col border-e md:w-80 lg:w-96",
          selected ? "hidden md:flex" : "flex",
        )}
      >
        <div className="space-y-2 border-b p-3">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold">{t("title")}</h1>
            <span
              className={cn(
                "inline-flex items-center gap-1 text-xs",
                live ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground",
              )}
            >
              <Radio className="size-3" aria-hidden />
              {live ? t("live") : "…"}
            </span>
          </div>
          <div className="relative">
            <Search className="text-muted-foreground absolute start-2 top-2 size-4" aria-hidden />
            <Input
              aria-label="Search"
              className="ps-8"
              placeholder="…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap gap-1.5">
            <NativeSelect
              aria-label="Mode"
              value={filters.mode ?? ""}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  mode: (e.target.value || undefined) as Filters["mode"],
                }))
              }
            >
              <option value="">AI + {t("humanMode")}</option>
              <option value="ai">{t("aiMode")}</option>
              <option value="human">{t("humanMode")}</option>
            </NativeSelect>
            <NativeSelect
              aria-label="Channel"
              value={filters.channel ?? ""}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  channel: (e.target.value || undefined) as Filters["channel"],
                }))
              }
            >
              <option value="">Web + WhatsApp</option>
              <option value="widget">Web</option>
              <option value="whatsapp">WhatsApp</option>
            </NativeSelect>
            <NativeSelect
              aria-label="Assigned"
              value={filters.assigned ?? ""}
              onChange={(e) =>
                setFilters((f) => ({
                  ...f,
                  assigned: (e.target.value || undefined) as Filters["assigned"],
                }))
              }
            >
              <option value="">—</option>
              <option value="me">{t("mine")}</option>
              <option value="unassigned">{t("unassigned")}</option>
            </NativeSelect>
            <Button
              size="sm"
              variant={filters.awaiting ? "default" : "outline"}
              aria-pressed={!!filters.awaiting}
              onClick={() => toggle("awaiting")}
            >
              {t("waiting")}
            </Button>
            <Button
              size="sm"
              variant={filters.flagged ? "default" : "outline"}
              aria-pressed={!!filters.flagged}
              onClick={() => toggle("flagged")}
            >
              <Flag /> {t("flagged")}
            </Button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          <QueryView q={list} skeleton={<SkeletonRows rows={8} className="p-3" />}>
            {(data) =>
              data.length === 0 ? (
                <EmptyState className="m-3" />
              ) : (
                <ul aria-label={t("title")}>
                  {data.map((r) => (
                    <ConversationItem
                      key={r.id}
                      row={r}
                      active={r.id === selected}
                      onSelect={() => setSelected(r.id)}
                    />
                  ))}
                </ul>
              )
            }
          </QueryView>
        </div>
        <p className="text-muted-foreground hidden border-t p-2 text-center text-xs md:block">
          {t("shortcuts")}
        </p>
      </section>

      {/* conversation + context panes */}
      {selected ? (
        <ConversationPane
          key={selected}
          id={selected}
          onBack={() => setSelected(null)}
          controlRef={composerRef}
        />
      ) : (
        <div className="hidden flex-1 items-center justify-center md:flex">
          <EmptyState title={t("pick")} icon={<MessageCircle className="size-5" />} />
        </div>
      )}
    </div>
  );
}

function ConversationItem({
  row,
  active,
  onSelect,
}: {
  row: Row;
  active: boolean;
  onSelect: () => void;
}) {
  const { locale } = useLocale();
  const t = useTranslations("inbox");
  const name = row.contact.name || row.contact.phone || `Visitor ${row.contact.id.slice(0, 4)}`;
  return (
    <li>
      <button
        onClick={onSelect}
        aria-current={active ? "true" : undefined}
        className={cn(
          "hover:bg-muted/60 flex w-full gap-3 border-b px-3 py-3 text-start",
          active && "bg-muted",
        )}
      >
        <div className="bg-muted text-muted-foreground grid size-9 shrink-0 place-items-center rounded-full">
          {row.channel === "whatsapp" ? (
            <MessageCircle className="size-4" />
          ) : (
            <Globe className="size-4" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={cn("truncate text-sm", row.awaiting_reply && "font-semibold")}>
              {name}
            </span>
            <span className="text-muted-foreground ms-auto shrink-0 text-xs">
              {fmtRelative(row.updated_at, locale)}
            </span>
          </div>
          <p className="text-muted-foreground truncate text-sm">
            {row.last_message?.sender === "staff" ? "↩ " : ""}
            {row.last_message?.text ?? "—"}
          </p>
          <div className="mt-1 flex gap-1">
            <Pill tone={row.mode === "human" ? "warn" : "info"}>
              {row.mode === "human" ? <UserRound className="size-3" /> : <Bot className="size-3" />}
              {row.mode === "human" ? t("humanMode") : t("aiMode")}
            </Pill>
            {row.flagged ? (
              <Pill tone="bad">
                <Flag className="size-3" /> {t("flagged")}
              </Pill>
            ) : null}
            {row.status === "closed" ? <Pill>✓</Pill> : null}
          </div>
        </div>
      </button>
    </li>
  );
}

function ConversationPane({
  id,
  onBack,
  controlRef,
}: {
  id: string;
  onBack: () => void;
  controlRef: React.RefObject<{
    focus: (m: "reply" | "note") => void;
    takeover: () => void;
  } | null>;
}) {
  const t = useTranslations("inbox");
  const { locale } = useLocale();
  const { user } = useMe();
  const qc = useQueryClient();
  const path = { conversation_id: id };
  const detail = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => unwrap(api.GET("/api/v1/conversations/{conversation_id}", { params: { path } })),
  });
  const messages = useQuery({
    queryKey: ["messages", id],
    queryFn: () =>
      unwrap(api.GET("/api/v1/conversations/{conversation_id}/messages", { params: { path } })),
    refetchInterval: 20_000,
  });
  const [mode, setMode] = useState<"reply" | "note">("reply");
  const [text, setText] = useState("");
  const [returnOpen, setReturnOpen] = useState(false);
  const [returnNote, setReturnNote] = useState("");
  const textRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const refresh = (d?: Detail) => {
    if (d) qc.setQueryData(["conversation", id], d);
    void qc.invalidateQueries({ queryKey: ["messages", id] });
    void qc.invalidateQueries({ queryKey: ["conversations"] });
  };
  const takeover = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/v1/conversations/{conversation_id}/takeover", { params: { path } })),
    onSuccess: refresh,
  });
  const giveBack = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/conversations/{conversation_id}/return-to-ai", {
          params: { path },
          body: { note: returnNote.trim() || null },
        }),
      ),
    onSuccess: (d) => {
      setReturnOpen(false);
      setReturnNote("");
      refresh(d);
    },
  });
  const patch = useMutation({
    mutationFn: (body: Schemas["PatchIn"]) =>
      unwrap(api.PATCH("/api/v1/conversations/{conversation_id}", { params: { path }, body })),
    onSuccess: refresh,
  });
  // The text travels as the mutation variable: onMutate clears the composer, and a closure over
  // `text` would then send "" (v5 re-applies the latest options to the in-flight mutation).
  const send = useMutation({
    mutationFn: async ({ value, kind }: { value: string; kind: "reply" | "note" }) => {
      const body = { text: value };
      return kind === "reply"
        ? unwrap(
            api.POST("/api/v1/conversations/{conversation_id}/messages", {
              params: { path },
              body,
            }),
          )
        : unwrap(
            api.POST("/api/v1/conversations/{conversation_id}/notes", { params: { path }, body }),
          );
    },
    onMutate: ({ value, kind }) => {
      // optimistic bubble
      const optimistic = {
        id: `tmp-${Date.now()}`,
        seq: Number.MAX_SAFE_INTEGER,
        direction: "out",
        sender: "staff",
        author_user_id: user?.id ?? null,
        author_name: user?.name ?? null,
        type: kind === "note" ? "note" : "text",
        text: value,
        transcript: null,
        media_path: null,
        template_name: null,
        status: "queued",
        citations: null,
        tool_calls: null,
        created_at: new Date().toISOString(),
      } as Msg;
      qc.setQueryData<Msg[]>(["messages", id], (old) => [...(old ?? []), optimistic]);
      setText("");
    },
    onSettled: () => refresh(),
  });

  useEffect(() => {
    controlRef.current = {
      focus: (m) => {
        setMode(m);
        textRef.current?.focus();
      },
      takeover: () => {
        if (detail.data?.mode === "ai") takeover.mutate();
      },
    };
  });

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.data?.length]);

  const d = detail.data;
  const name = d ? d.contact.name || d.contact.phone || `Visitor ${d.contact.id.slice(0, 4)}` : "";
  const optedOut = !!d?.contact.opted_out_at;
  // WhatsApp 24h window (6.3.2): free-form replies only while the parent's last message is < 24h old.
  const windowClosed = d?.window_open === false;

  return (
    <div className="flex min-w-0 flex-1">
      <section aria-label={name} className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-2 border-b p-3">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            onClick={onBack}
            aria-label="Back"
          >
            <ArrowLeft />
          </Button>
          <div className="min-w-0">
            <h2 className="truncate font-semibold">{name || "…"}</h2>
            {d ? (
              <p className="text-muted-foreground text-xs">
                {d.channel} · {d.module} · {d.assigned_user_name ?? t("unassigned")}
              </p>
            ) : null}
          </div>
          {d ? (
            <div className="ms-auto flex flex-wrap gap-1.5">
              {d.mode === "ai" ? (
                <Button size="sm" onClick={() => takeover.mutate()} disabled={takeover.isPending}>
                  <UserRound /> {t("takeOver")}
                </Button>
              ) : (
                <Button size="sm" variant="secondary" onClick={() => setReturnOpen(true)}>
                  <Bot /> {t("returnToAi")}
                </Button>
              )}
              {!d.assigned_user_id || d.assigned_user_id !== user?.id ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => user && patch.mutate({ assigned_user_id: user.id })}
                >
                  {t("assignMe")}
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="outline"
                aria-pressed={d.flagged}
                onClick={() => patch.mutate({ flagged: !d.flagged })}
              >
                <Flag /> {d.flagged ? t("unflag") : t("flag")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => patch.mutate({ status: d.status === "closed" ? "open" : "closed" })}
              >
                {d.status === "closed" ? <RotateCcw /> : <CheckCheck />}
                {d.status === "closed" ? t("reopen") : t("resolve")}
              </Button>
            </div>
          ) : null}
        </header>

        <div className="flex-1 space-y-3 overflow-y-auto p-4" aria-live="polite">
          <QueryView q={messages} skeleton={<SkeletonRows rows={6} />}>
            {(msgs) =>
              msgs.length === 0 ? (
                <EmptyState />
              ) : (
                msgs.map((m) => <Bubble key={m.id} m={m} locale={locale} />)
              )
            }
          </QueryView>
          <div ref={endRef} />
        </div>

        <form
          className="space-y-2 border-t p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) send.mutate({ value: text.trim(), kind: mode });
          }}
        >
          <div role="tablist" className="flex gap-1">
            {(["reply", "note"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-sm",
                  mode === m ? "bg-muted font-medium" : "text-muted-foreground",
                )}
              >
                {m === "reply" ? t("reply") : t("note")}
              </button>
            ))}
            {d?.mode === "ai" && mode === "reply" ? (
              <span className="text-muted-foreground ms-2 self-center text-xs">
                → {t("takeOver")}
              </span>
            ) : null}
          </div>
          {optedOut && mode === "reply" ? (
            <p className="text-destructive text-sm">{t("optedOut")}</p>
          ) : windowClosed && mode === "reply" ? (
            <p
              role="status"
              className="rounded-md bg-amber-500/15 px-2 py-1 text-sm text-amber-900 dark:text-amber-300"
            >
              {t("windowClosed")}
            </p>
          ) : null}
          <div className="flex gap-2">
            <Textarea
              ref={textRef}
              aria-label={mode === "reply" ? t("reply") : t("note")}
              placeholder={mode === "reply" ? t("replyPlaceholder") : t("notePlaceholder")}
              value={text}
              rows={2}
              className={cn(
                "min-h-10 resize-none",
                mode === "note" && "bg-amber-50 dark:bg-amber-950/30",
              )}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (text.trim()) send.mutate({ value: text.trim(), kind: mode });
                }
                if (e.key === "Escape") textRef.current?.blur();
              }}
            />
            <Button
              type="submit"
              disabled={
                !text.trim() || send.isPending || ((optedOut || windowClosed) && mode === "reply")
              }
            >
              {t("send")}
            </Button>
          </div>
        </form>
      </section>

      {d ? <ContextPane d={d} /> : null}

      <Dialog open={returnOpen} onOpenChange={setReturnOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("returnToAi")}</DialogTitle>
          </DialogHeader>
          <label htmlFor="return-note" className="text-sm">
            {t("returnNote")}
          </label>
          <Textarea
            id="return-note"
            value={returnNote}
            onChange={(e) => setReturnNote(e.target.value)}
            rows={3}
          />
          <DialogFooter>
            <Button onClick={() => giveBack.mutate()} disabled={giveBack.isPending}>
              <Bot /> {t("returnToAi")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Bubble({ m, locale }: { m: Msg; locale: string }) {
  const t = useTranslations("inbox");
  if (m.type === "note" && m.sender === "system") {
    return (
      <p className="text-muted-foreground text-center text-xs">
        {m.text} · {fmtTime(m.created_at, locale)}
      </p>
    );
  }
  const mine = m.direction === "out";
  const note = m.type === "note";
  return (
    <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap",
          note
            ? "border border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100"
            : mine
              ? m.sender === "staff"
                ? "bg-primary text-primary-foreground"
                : "bg-secondary"
              : "bg-muted",
        )}
      >
        <div className="mb-0.5 flex items-center gap-1 text-[11px] font-medium">
          {note ? (
            <StickyNote className="size-3" />
          ) : m.sender === "ai" ? (
            <Bot className="size-3" />
          ) : null}
          {m.sender === "staff"
            ? (m.author_name ?? "Staff")
            : m.sender === "contact"
              ? ""
              : m.sender.toUpperCase()}
          <span className="ms-auto">{fmtTime(m.created_at, locale)}</span>
        </div>
        {m.text ?? m.transcript ?? (m.media_path ? `[${m.type}]` : "")}
        {m.transcript && m.text !== m.transcript ? (
          <p className="mt-1 text-xs italic opacity-80">🎙 {m.transcript}</p>
        ) : null}
        {m.citations?.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {m.citations.map((c, i) => (
              <span
                key={i}
                className="bg-background/60 rounded px-1.5 py-0.5 text-[11px]"
                title={String(c.quote ?? "")}
              >
                {String(c.title ?? t("sources"))}
                {c.page ? ` p.${String(c.page)}` : ""}
              </span>
            ))}
          </div>
        ) : null}
        {m.status === "failed" ? (
          <p className="mt-1 text-[11px] font-medium">
            ⚠ {t("notDelivered")}
            {m.error ? ` — ${m.error}` : ""}
          </p>
        ) : null}
        {m.tool_calls?.length ? (
          <details className="mt-2 text-[11px] opacity-80">
            <summary className="cursor-pointer">
              <Wrench className="inline size-3" /> {t("toolCalls")} ({m.tool_calls.length})
            </summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap">
              {JSON.stringify(m.tool_calls, null, 1)}
            </pre>
          </details>
        ) : null}
      </div>
    </div>
  );
}

function ContextPane({ d }: { d: Detail }) {
  const t = useTranslations("inbox");
  const tl = useTranslations("leads");
  const { locale } = useLocale();
  const summary = d.summary as Record<string, unknown> | null;
  return (
    <aside
      tabIndex={0}
      aria-label={t("context")}
      className="focus-visible:ring-ring hidden w-72 shrink-0 space-y-4 overflow-y-auto border-s p-4 text-sm focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset xl:block"
    >
      <section>
        <h3 className="text-muted-foreground mb-1 text-xs font-medium uppercase">{t("contact")}</h3>
        <p className="font-medium">{d.contact.name ?? "—"}</p>
        <p className="text-muted-foreground">{d.contact.phone ?? d.contact.wa_id ?? "—"}</p>
        <p className="text-muted-foreground text-xs">
          {d.contact.preferred_language ?? "—"} · {fmtDateTime(d.contact.created_at, locale)}
        </p>
      </section>
      {d.lead ? (
        <section>
          <h3 className="text-muted-foreground mb-1 text-xs font-medium uppercase">{t("lead")}</h3>
          <p>{d.lead.student_name ?? d.lead.guardian_name ?? "—"}</p>
          <p className="text-muted-foreground">{d.lead.interest ?? ""}</p>
          <Pill tone="info">{tl(`st_${d.lead.status}`)}</Pill>
        </section>
      ) : null}
      {d.bookings.length ? (
        <section>
          <h3 className="text-muted-foreground mb-1 text-xs font-medium uppercase">
            {t("bookings")}
          </h3>
          <ul className="space-y-1">
            {d.bookings.map((b) => (
              <li key={b.id}>
                {b.kind} · {fmtDateTime(b.starts_at, locale)} ·{" "}
                <span className="font-mono">{b.code}</span> <Pill>{b.status}</Pill>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {summary ? (
        <section>
          <h3 className="text-muted-foreground mb-1 text-xs font-medium uppercase">
            {t("summary")}
          </h3>
          <dl className="space-y-1">
            {Object.entries(summary)
              .filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0))
              .map(([k, v]) => (
                <div key={k}>
                  <dt className="text-muted-foreground text-xs">{k.replaceAll("_", " ")}</dt>
                  <dd>
                    {Array.isArray(v)
                      ? v.join(", ")
                      : typeof v === "object"
                        ? JSON.stringify(v)
                        : String(v)}
                  </dd>
                </div>
              ))}
          </dl>
        </section>
      ) : null}
    </aside>
  );
}

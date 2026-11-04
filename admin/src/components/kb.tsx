"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileUp, Pencil, RefreshCw, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { EmptyState, Field, Pill, QueryView, SkeletonRows } from "@/components/common";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, rawFetch, unwrap, type Schemas } from "@/lib/api/client";
import { useAuth, useMe } from "@/lib/auth";
import { fmtDateTime, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

type Doc = Schemas["DocumentOut"];
type Fact = Schemas["FactOut"];
export type FactKind = "fee_items" | "programs" | "key_dates" | "scholarships" | "transport_routes";
export const FACT_KINDS: FactKind[] = [
  "fee_items",
  "programs",
  "key_dates",
  "scholarships",
  "transport_routes",
];
const BUSY = new Set(["uploaded", "parsing", "chunking", "embedding", "extracting"]);

function statusTone(s: string) {
  return s === "ready" ? "good" : s === "failed" ? "bad" : s === "superseded" ? "neutral" : "warn";
}

export function DocumentsPanel() {
  const t = useTranslations("kb");
  const tc = useTranslations("common");
  const { institutionId } = useAuth();
  const { can } = useMe();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState<string[]>([]);
  const [chunksOf, setChunksOf] = useState<Doc | null>(null);
  const docs = useQuery({
    queryKey: ["documents", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/kb/documents")),
    enabled: !!institutionId,
    // poll while anything is still in the pipeline (statuses advance in the worker)
    refetchInterval: (q) => (q.state.data?.some((d) => BUSY.has(d.status)) ? 2000 : false),
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["documents"] });
    void qc.invalidateQueries({ queryKey: ["facts"] });
    void qc.invalidateQueries({ queryKey: ["onboarding"] });
  };
  const reindex = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/kb/documents/{document_id}/reindex", {
          params: { path: { document_id: id } },
        }),
      ),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/v1/kb/documents/{document_id}", { params: { path: { document_id: id } } }),
      ),
    onSuccess: invalidate,
  });

  async function upload(files: FileList | File[]) {
    for (const f of Array.from(files)) {
      setUploading((u) => [...u, f.name]);
      const form = new FormData();
      form.append("file", f);
      form.append("title", f.name.replace(/\.[^.]+$/, ""));
      try {
        const r = await rawFetch("/api/v1/kb/documents", { method: "POST", body: form });
        if (!r.ok) {
          const body = (await r.json().catch(() => ({}))) as { detail?: unknown };
          toast.error(`${f.name}: ${typeof body.detail === "string" ? body.detail : r.status}`);
        }
      } finally {
        setUploading((u) => u.filter((n) => n !== f.name));
        invalidate();
      }
    }
  }

  return (
    <div className="space-y-4">
      {can("admin") ? (
        <button
          type="button"
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            void upload(e.dataTransfer.files);
          }}
          className={cn(
            "text-muted-foreground flex w-full flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-sm transition-colors",
            dragging && "border-primary bg-primary/5",
          )}
        >
          <FileUp className="size-6" aria-hidden />
          <span className="text-foreground font-medium">{t("upload")}</span>
          <span>{t("dropHint")}</span>
          {uploading.length ? <span aria-live="polite">⏳ {uploading.join(", ")}</span> : null}
          <input
            ref={input}
            type="file"
            multiple
            hidden
            accept=".pdf,.docx,.xlsx,.csv"
            onChange={(e) => e.target.files && void upload(e.target.files)}
          />
        </button>
      ) : null}
      <QueryView q={docs}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Title</TableHead>
                    <TableHead>{tc("status")}</TableHead>
                    <TableHead>{t("pages")}</TableHead>
                    <TableHead>{t("version")}</TableHead>
                    <TableHead>Updated</TableHead>
                    <TableHead className="text-end">{tc("actions")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.map((d) => (
                    <TableRow key={d.id}>
                      <TableCell>
                        <p className="font-medium">{d.title}</p>
                        <p className="text-muted-foreground text-xs">
                          {d.filename} · {(d.size_bytes / 1024).toFixed(0)} KB
                        </p>
                        {d.error ? <p className="text-destructive text-xs">{d.error}</p> : null}
                      </TableCell>
                      <TableCell>
                        <Pill tone={statusTone(d.status)}>
                          {BUSY.has(d.status) ? "⏳ " : ""}
                          {d.status}
                        </Pill>
                      </TableCell>
                      <TableCell className="tabular-nums">{d.pages ?? "—"}</TableCell>
                      <TableCell className="tabular-nums">v{d.version}</TableCell>
                      <TableCell>{fmtDateTime(d.updated_at)}</TableCell>
                      <TableCell className="text-end whitespace-nowrap">
                        <Button size="sm" variant="ghost" onClick={() => setChunksOf(d)}>
                          {t("chunks")}
                        </Button>
                        {can("admin") ? (
                          <>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={t("reindex")}
                              title={t("reindex")}
                              onClick={() => reindex.mutate(d.id)}
                            >
                              <RefreshCw />
                            </Button>
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={tc("delete")}
                              title={tc("delete")}
                              onClick={() =>
                                confirm(`${tc("delete")} “${d.title}”?`) && remove.mutate(d.id)
                              }
                            >
                              <Trash2 />
                            </Button>
                          </>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )
        }
      </QueryView>
      {chunksOf ? <ChunkViewer doc={chunksOf} onClose={() => setChunksOf(null)} /> : null}
    </div>
  );
}

function ChunkViewer({ doc, onClose }: { doc: Doc; onClose: () => void }) {
  const t = useTranslations("kb");
  const chunks = useQuery({
    queryKey: ["chunks", doc.id],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/kb/documents/{document_id}/chunks", {
          params: { path: { document_id: doc.id } },
        }),
      ),
  });
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>
            {doc.title} — {t("chunks")}
          </SheetTitle>
        </SheetHeader>
        <div className="space-y-3 px-4 pb-6">
          <QueryView q={chunks}>
            {(list) =>
              list.length === 0 ? (
                <EmptyState />
              ) : (
                list.map((c) => (
                  <article key={c.id} className="rounded-lg border p-3 text-sm">
                    <div className="text-muted-foreground mb-1 flex flex-wrap gap-2 text-xs">
                      <span>#{c.ordinal}</span>
                      {c.page ? <span>p.{c.page}</span> : null}
                      <span>{c.lang}</span>
                      <span>{c.tokens} tok</span>
                      {c.suspicious ? <Pill tone="bad">suspicious</Pill> : null}
                      {!c.embedded ? <Pill tone="warn">not embedded</Pill> : null}
                    </div>
                    {c.heading ? <p className="font-medium">{c.heading}</p> : null}
                    <p
                      className="whitespace-pre-wrap"
                      dir={c.lang === "ur" ? "rtl" : undefined}
                      lang={c.lang === "ur" ? "ur" : undefined}
                    >
                      {c.text}
                    </p>
                  </article>
                ))
              )
            }
          </QueryView>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function FactsPanel({ initialKind = "fee_items" }: { initialKind?: FactKind }) {
  const t = useTranslations("kb");
  const tc = useTranslations("common");
  const { institutionId } = useAuth();
  const { can } = useMe();
  const qc = useQueryClient();
  const [kind, setKind] = useState<FactKind>(initialKind);
  const [status, setStatus] = useState<"pending" | "approved" | "rejected" | "">("");
  const [editing, setEditing] = useState<Fact | null>(null);
  const facts = useQuery({
    queryKey: ["facts", institutionId, kind, status],
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/kb/facts/{kind}", {
          params: { path: { kind }, query: status ? { status } : {} },
        }),
      ),
    enabled: !!institutionId,
  });
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["facts"] });
    void qc.invalidateQueries({ queryKey: ["onboarding"] });
    void qc.invalidateQueries({ queryKey: ["metrics"] });
  };
  const bulk = useMutation({
    mutationFn: (body: Schemas["FactsBulkStatus"]) =>
      unwrap(api.PATCH("/api/v1/kb/facts/{kind}", { params: { path: { kind } }, body })),
    onSuccess: invalidate,
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["FactPatch"] }) =>
      unwrap(
        api.PATCH("/api/v1/kb/facts/{kind}/{fact_id}", {
          params: { path: { kind, fact_id: id } },
          body,
        }),
      ),
    onSuccess: () => {
      invalidate();
      setEditing(null);
    },
  });
  const pending = (facts.data ?? []).filter((f) => f.status === "pending");
  const columns = Array.from(
    new Set((facts.data ?? []).flatMap((f) => Object.keys(f.fields))),
  ).slice(0, 6);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" className="bg-muted inline-flex flex-wrap rounded-lg p-0.5">
          {FACT_KINDS.map((k) => (
            <button
              key={k}
              role="tab"
              aria-selected={kind === k}
              onClick={() => setKind(k)}
              className={cn(
                "rounded-md px-3 py-1 text-sm",
                kind === k ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
              )}
            >
              {t(k)}
            </button>
          ))}
        </div>
        <select
          aria-label={tc("status")}
          className="border-input bg-background h-8 rounded-lg border px-2 text-sm"
          value={status}
          onChange={(e) => setStatus(e.target.value as typeof status)}
        >
          <option value="">{tc("all")}</option>
          <option value="pending">pending</option>
          <option value="approved">approved</option>
          <option value="rejected">rejected</option>
        </select>
        {can("admin") && pending.length ? (
          <Button
            size="sm"
            className="ms-auto"
            onClick={() => bulk.mutate({ ids: pending.map((f) => f.id), status: "approved" })}
          >
            <Check /> {t("approveAll")} ({pending.length})
          </Button>
        ) : null}
      </div>
      <QueryView q={facts} skeleton={<SkeletonRows rows={6} />}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState />
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              <Table>
                <TableHeader>
                  <TableRow>
                    {columns.map((c) => (
                      <TableHead key={c}>{c.replaceAll("_", " ")}</TableHead>
                    ))}
                    <TableHead>Source</TableHead>
                    <TableHead>{tc("status")}</TableHead>
                    {can("admin") ? (
                      <TableHead className="text-end">{tc("actions")}</TableHead>
                    ) : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.map((f) => (
                    <TableRow key={f.id}>
                      {columns.map((c) => (
                        <TableCell key={c} className="max-w-48 truncate">
                          {f.fields[c] == null ? "—" : String(f.fields[c])}
                        </TableCell>
                      ))}
                      <TableCell
                        className="text-muted-foreground max-w-40 truncate text-xs"
                        title={f.source?.quote ?? ""}
                      >
                        {f.source
                          ? `${f.source.title ?? ""}${f.source.page ? ` p.${f.source.page}` : ""}`
                          : f.origin}
                      </TableCell>
                      <TableCell>
                        <Pill
                          tone={
                            f.status === "approved"
                              ? "good"
                              : f.status === "pending"
                                ? "warn"
                                : "neutral"
                          }
                        >
                          {f.status}
                        </Pill>
                      </TableCell>
                      {can("admin") ? (
                        <TableCell className="text-end whitespace-nowrap">
                          {f.status !== "approved" ? (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={t("approve")}
                              title={t("approve")}
                              onClick={() =>
                                patch.mutate({ id: f.id, body: { status: "approved" } })
                              }
                            >
                              <Check />
                            </Button>
                          ) : null}
                          {f.status !== "rejected" ? (
                            <Button
                              size="icon-sm"
                              variant="ghost"
                              aria-label={t("reject")}
                              title={t("reject")}
                              onClick={() =>
                                patch.mutate({ id: f.id, body: { status: "rejected" } })
                              }
                            >
                              <X />
                            </Button>
                          ) : null}
                          <Button
                            size="icon-sm"
                            variant="ghost"
                            aria-label={tc("edit")}
                            title={tc("edit")}
                            onClick={() => setEditing(f)}
                          >
                            <Pencil />
                          </Button>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )
        }
      </QueryView>
      {editing ? (
        <FactEditor
          fact={editing}
          busy={patch.isPending}
          onClose={() => setEditing(null)}
          onSave={(body) => patch.mutate({ id: editing.id, body })}
        />
      ) : null}
    </div>
  );
}

function FactEditor({
  fact,
  busy,
  onClose,
  onSave,
}: {
  fact: Fact;
  busy: boolean;
  onClose: () => void;
  onSave: (b: Schemas["FactPatch"]) => void;
}) {
  const t = useTranslations("kb");
  const tc = useTranslations("common");
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(
      Object.entries(fact.fields).map(([k, v]) => [k, v == null ? "" : String(v)]),
    ),
  );
  const [notes, setNotes] = useState(fact.notes ?? "");
  function save(approve: boolean) {
    const fields: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(values)) {
      const orig = fact.fields[k];
      fields[k] = v === "" ? null : typeof orig === "number" ? Number(v) : v;
    }
    onSave({ fields, notes: notes || null, ...(approve ? { status: "approved" } : {}) });
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {tc("edit")} · {t(fact.kind)}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {Object.keys(values).map((k) => (
            <Field key={k} label={k.replaceAll("_", " ")} htmlFor={`f-${k}`}>
              <Input
                id={`f-${k}`}
                value={values[k]}
                onChange={(e) => setValues({ ...values, [k]: e.target.value })}
              />
            </Field>
          ))}
          <Field label="Notes" htmlFor="f-notes">
            <Textarea id="f-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </Field>
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => save(false)}>
            {tc("save")}
          </Button>
          <Button disabled={busy} onClick={() => save(true)}>
            {tc("save")} + {t("approve")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type AgentRun = {
  status: string;
  reply: string | null;
  reply_kind: string | null;
  citations: { title?: string; page?: number; quote?: string }[];
  sources: { id?: string; title?: string; text?: string }[];
  check: Record<string, unknown> | null;
  route: Record<string, unknown> | null;
  runs: { node: string; model: string; cost_usd: string | null; latency_ms: number | null }[];
  cost_usd: string;
};

export function Playground() {
  const t = useTranslations("kb");
  const [query, setQuery] = useState("");
  const [full, setFull] = useState(false);
  const [sessionKey, setSessionKey] = useState(() => Math.random().toString(36).slice(2, 10));
  const retrieval = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/kb/playground", { body: { query, top_k: 5 } })),
  });
  const agent = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/kb/playground/agent", { body: { query, session_key: sessionKey } }),
      ) as Promise<AgentRun>,
  });
  const run = () => (full ? agent.mutate() : retrieval.mutate());
  const busy = retrieval.isPending || agent.isPending;
  return (
    <div className="space-y-4">
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) run();
        }}
      >
        <Input
          aria-label={t("ask")}
          placeholder={t("askPlaceholder")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button type="submit" disabled={busy || !query.trim()}>
          {t("ask")}
        </Button>
      </form>
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          <input type="radio" checked={!full} onChange={() => setFull(false)} /> {t("retrieval")}
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" checked={full} onChange={() => setFull(true)} /> {t("fullRun")}
        </label>
        {full ? (
          <Button
            size="xs"
            variant="ghost"
            onClick={() => setSessionKey(Math.random().toString(36).slice(2, 10))}
          >
            ↺ new chat
          </Button>
        ) : null}
      </div>
      {busy ? <SkeletonRows rows={3} /> : null}
      {full && agent.data ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <section className="space-y-2 rounded-xl border p-4 lg:col-span-2">
            <h3 className="text-sm font-medium">
              {t("answer")}{" "}
              <Pill tone={agent.data.reply_kind === "answer" ? "good" : "warn"}>
                {agent.data.reply_kind ?? agent.data.status}
              </Pill>
            </h3>
            <p className="text-sm whitespace-pre-wrap">{agent.data.reply ?? "—"}</p>
            {agent.data.citations.length ? (
              <ul className="text-muted-foreground space-y-1 text-xs">
                {agent.data.citations.map((c, i) => (
                  <li key={i}>
                    📎 {c.title} {c.page ? `p.${c.page}` : ""} — “{c.quote}”
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
          <section className="space-y-2 rounded-xl border p-4 text-xs">
            <p>
              <span className="font-medium">{t("cost")}:</span> {fmtUsd(agent.data.cost_usd)}
            </p>
            <p>
              <span className="font-medium">{t("check")}:</span>{" "}
              {agent.data.check
                ? String(
                    (agent.data.check as { ok?: boolean }).ok ?? JSON.stringify(agent.data.check),
                  )
                : "—"}
            </p>
            <details>
              <summary className="cursor-pointer font-medium">{t("route")}</summary>
              <pre className="whitespace-pre-wrap">{JSON.stringify(agent.data.route, null, 1)}</pre>
            </details>
            <details>
              <summary className="cursor-pointer font-medium">
                LLM runs ({agent.data.runs.length})
              </summary>
              <ul>
                {agent.data.runs.map((r, i) => (
                  <li key={i}>
                    {r.node} · {r.model} · {fmtUsd(r.cost_usd)} · {r.latency_ms ?? "—"}ms
                  </li>
                ))}
              </ul>
            </details>
          </section>
        </div>
      ) : null}
      {!full && retrieval.data ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="space-y-2">
            <h3 className="text-sm font-medium">
              {t("chunks")} ({retrieval.data.packed_tokens} tok)
            </h3>
            {retrieval.data.chunks.map((c) => (
              <article key={c.chunk_id} className="rounded-lg border p-3 text-sm">
                <p className="text-muted-foreground mb-1 text-xs">
                  score {c.score} ·{" "}
                  {Object.entries(c.legs)
                    .map(([k, v]) => `${k}#${v}`)
                    .join(" ")}
                </p>
                {c.heading ? <p className="font-medium">{c.heading}</p> : null}
                <p className="line-clamp-6 whitespace-pre-wrap">{c.text}</p>
              </article>
            ))}
            {retrieval.data.chunks.length === 0 ? <EmptyState className="p-6" /> : null}
          </section>
          <section className="space-y-2">
            <h3 className="text-sm font-medium">{t("facts")}</h3>
            {retrieval.data.facts.map((f) => (
              <article key={f.id} className="rounded-lg border p-3 text-xs">
                <Pill>{t(f.kind)}</Pill>
                <pre className="mt-1 whitespace-pre-wrap">{JSON.stringify(f.fields, null, 1)}</pre>
              </article>
            ))}
            {retrieval.data.facts.length === 0 ? <EmptyState className="p-6" /> : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}

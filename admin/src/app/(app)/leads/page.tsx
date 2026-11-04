"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  EmptyState,
  Field,
  NativeSelect,
  PageHeader,
  Pill,
  QueryView,
  SkeletonRows,
} from "@/components/common";
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
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/format";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Lead = Schemas["LeadOut"];
type Status = "new" | "contacted" | "visit_booked" | "applied" | "admitted" | "lost";
const STATUSES: Status[] = ["new", "contacted", "visit_booked", "applied", "admitted", "lost"];
type SortKey = "created_at" | "updated_at" | "next_followup_at" | "student_name";

export default function LeadsPage() {
  const t = useTranslations("leads");
  const tc = useTranslations("common");
  const { institutionId } = useAuth();
  const qc = useQueryClient();
  const [view, setView] = useState<"board" | "table">("board");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState<string | undefined>();
  const [sort, setSort] = useState<SortKey>("created_at");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());

  useEffect(() => {
    const h = setTimeout(() => setQ(search.trim() || undefined), 300);
    return () => clearTimeout(h);
  }, [search]);

  const key = ["leads", institutionId, q, sort, order];
  const leads = useQuery({
    queryKey: key,
    queryFn: () => unwrap(api.GET("/api/v1/leads", { params: { query: { q, sort, order } } })),
    enabled: !!institutionId,
  });
  const members = useQuery({
    queryKey: ["members", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/members")),
    enabled: !!institutionId,
  });
  const memberName = useMemo(
    () => new Map((members.data ?? []).map((m) => [m.user_id, m.name])),
    [members.data],
  );

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["LeadPatch"] }) =>
      unwrap(api.PATCH("/api/v1/leads/{lead_id}", { params: { path: { lead_id: id } }, body })),
    onMutate: async ({ id, body }) => {
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueryData<Lead[]>(key);
      qc.setQueryData<Lead[]>(key, (old) =>
        old?.map((l) => (l.id === id ? ({ ...l, ...body } as Lead) : l)),
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(key, ctx.prev),
    onSettled: (_d, _e, v) => {
      void qc.invalidateQueries({ queryKey: ["leads"] });
      void qc.invalidateQueries({ queryKey: ["lead", v.id] });
    },
  });

  async function exportCsv() {
    const params = new URLSearchParams(q ? { q } : {});
    const r = await rawFetch(`/api/v1/leads/export.csv?${params}`);
    if (!r.ok) return toast.error(tc("error"));
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "leads.csv" });
    a.click();
    URL.revokeObjectURL(url);
  }

  function bulkStatus(status: Status) {
    for (const id of checked) patch.mutate({ id, body: { status } });
    setChecked(new Set());
  }

  const sortBy = (k: SortKey) => {
    if (sort === k) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(k);
      setOrder("desc");
    }
  };
  const sortIcon = (k: SortKey) => (sort === k ? (order === "asc" ? " ↑" : " ↓") : "");

  return (
    <>
      <PageHeader
        title={t("title")}
        description={view === "board" ? t("dragHint") : undefined}
        actions={
          <>
            <div className="relative">
              <Search className="text-muted-foreground absolute start-2 top-2 size-4" aria-hidden />
              <Input
                aria-label={tc("search")}
                placeholder={tc("search")}
                className="w-48 ps-8"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div role="group" className="bg-muted inline-flex rounded-lg p-0.5">
              {(["board", "table"] as const).map((v) => (
                <button
                  key={v}
                  aria-pressed={view === v}
                  onClick={() => setView(v)}
                  className={cn(
                    "rounded-md px-3 py-1 text-sm",
                    view === v ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
                  )}
                >
                  {t(v)}
                </button>
              ))}
            </div>
            <Button variant="outline" onClick={() => void exportCsv()}>
              <Download /> {tc("export")}
            </Button>
            <Button onClick={() => setCreating(true)}>
              <Plus /> {t("new")}
            </Button>
          </>
        }
      />
      <QueryView q={leads} skeleton={<SkeletonRows rows={8} />}>
        {(data) =>
          data.length === 0 ? (
            <EmptyState
              action={
                <Button size="sm" onClick={() => setCreating(true)}>
                  <Plus /> {t("new")}
                </Button>
              }
            />
          ) : view === "board" ? (
            <Board
              leads={data}
              onOpen={setOpen}
              onMove={(id, status) => patch.mutate({ id, body: { status } })}
            />
          ) : (
            <div className="space-y-2">
              {checked.size ? (
                <div className="bg-muted flex items-center gap-2 rounded-lg p-2 text-sm">
                  <span>{checked.size} ✓</span>
                  <NativeSelect
                    aria-label={tc("status")}
                    defaultValue=""
                    onChange={(e) => e.target.value && bulkStatus(e.target.value as Status)}
                  >
                    <option value="">{tc("status")}…</option>
                    {STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {t(`st_${s}`)}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              ) : null}
              <div className="overflow-x-auto rounded-xl border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-8">
                        <input
                          type="checkbox"
                          aria-label="Select all"
                          checked={checked.size === data.length}
                          onChange={(e) =>
                            setChecked(
                              e.target.checked ? new Set(data.map((l) => l.id)) : new Set(),
                            )
                          }
                        />
                      </TableHead>
                      <TableHead>
                        <button onClick={() => sortBy("student_name")}>
                          {t("student")}
                          {sortIcon("student_name")}
                        </button>
                      </TableHead>
                      <TableHead>{t("guardian")}</TableHead>
                      <TableHead>{t("phone")}</TableHead>
                      <TableHead>{t("interest")}</TableHead>
                      <TableHead>{tc("status")}</TableHead>
                      <TableHead>{t("owner")}</TableHead>
                      <TableHead>
                        <button onClick={() => sortBy("next_followup_at")}>
                          {t("followup")}
                          {sortIcon("next_followup_at")}
                        </button>
                      </TableHead>
                      <TableHead>
                        <button onClick={() => sortBy("created_at")}>
                          {t("created")}
                          {sortIcon("created_at")}
                        </button>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.map((l) => (
                      <TableRow key={l.id} className="cursor-pointer" onClick={() => setOpen(l.id)}>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            aria-label={`Select ${l.student_name ?? l.id}`}
                            checked={checked.has(l.id)}
                            onChange={(e) => {
                              const next = new Set(checked);
                              if (e.target.checked) next.add(l.id);
                              else next.delete(l.id);
                              setChecked(next);
                            }}
                          />
                        </TableCell>
                        <TableCell className="font-medium">{l.student_name ?? "—"}</TableCell>
                        <TableCell>{l.guardian_name ?? "—"}</TableCell>
                        <TableCell className="tabular-nums">{l.phone ?? "—"}</TableCell>
                        <TableCell>{l.interest ?? "—"}</TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <NativeSelect
                            aria-label={tc("status")}
                            value={l.status}
                            onChange={(e) =>
                              patch.mutate({ id: l.id, body: { status: e.target.value as Status } })
                            }
                          >
                            {STATUSES.map((s) => (
                              <option key={s} value={s}>
                                {t(`st_${s}`)}
                              </option>
                            ))}
                          </NativeSelect>
                        </TableCell>
                        <TableCell>
                          {l.owner_user_id ? (memberName.get(l.owner_user_id) ?? "—") : "—"}
                        </TableCell>
                        <TableCell>{fmtDateTime(l.next_followup_at)}</TableCell>
                        <TableCell>{fmtDateTime(l.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )
        }
      </QueryView>
      {open ? (
        <LeadDrawer
          id={open}
          onClose={() => setOpen(null)}
          members={members.data ?? []}
          onPatch={(body) => patch.mutate({ id: open, body })}
        />
      ) : null}
      <NewLeadDialog open={creating} onOpenChange={setCreating} />
    </>
  );
}

function Board({
  leads,
  onOpen,
  onMove,
}: {
  leads: Lead[];
  onOpen: (id: string) => void;
  onMove: (id: string, s: Status) => void;
}) {
  const t = useTranslations("leads");
  const tc = useTranslations("common");
  const [over, setOver] = useState<Status | null>(null);
  return (
    <div className="grid auto-cols-[minmax(14rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-2">
      {STATUSES.map((s) => {
        const items = leads.filter((l) => l.status === s);
        return (
          <section
            key={s}
            aria-label={t(`st_${s}`)}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(s);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              const id = e.dataTransfer.getData("text/lead");
              if (id) onMove(id, s);
            }}
            className={cn(
              "bg-muted/50 flex min-h-64 flex-col gap-2 rounded-xl p-2",
              over === s && "ring-primary ring-2",
            )}
          >
            <h2 className="flex items-center justify-between px-1 text-sm font-medium">
              {t(`st_${s}`)}{" "}
              <span className="text-muted-foreground tabular-nums">{items.length}</span>
            </h2>
            {items.map((l) => (
              <article
                key={l.id}
                draggable
                data-lead={l.id}
                onDragStart={(e) => e.dataTransfer.setData("text/lead", l.id)}
                className="bg-card cursor-grab rounded-lg border p-3 text-sm shadow-xs active:cursor-grabbing"
              >
                <button className="w-full text-start" onClick={() => onOpen(l.id)}>
                  <p className="font-medium">
                    {l.student_name ?? l.guardian_name ?? l.phone ?? "—"}
                  </p>
                  <p className="text-muted-foreground truncate">{l.interest ?? ""}</p>
                  <div className="mt-1 flex items-center gap-1">
                    <Pill>{l.source}</Pill>
                    {l.phone ? (
                      <span className="text-muted-foreground text-xs">{l.phone}</span>
                    ) : null}
                  </div>
                </button>
                {/* keyboard alternative to drag-and-drop */}
                <NativeSelect
                  aria-label={tc("status")}
                  className="mt-2 h-7 w-full text-xs"
                  value={l.status}
                  onChange={(e) => onMove(l.id, e.target.value as Status)}
                >
                  {STATUSES.map((x) => (
                    <option key={x} value={x}>
                      {t(`st_${x}`)}
                    </option>
                  ))}
                </NativeSelect>
              </article>
            ))}
          </section>
        );
      })}
    </div>
  );
}

function LeadDrawer({
  id,
  onClose,
  members,
  onPatch,
}: {
  id: string;
  onClose: () => void;
  members: Schemas["MemberOut"][];
  onPatch: (b: Schemas["LeadPatch"]) => void;
}) {
  const t = useTranslations("leads");
  const tc = useTranslations("common");
  const { locale } = useLocale();
  const lead = useQuery({
    queryKey: ["lead", id],
    queryFn: () =>
      unwrap(api.GET("/api/v1/leads/{lead_id}", { params: { path: { lead_id: id } } })),
  });
  const [notes, setNotes] = useState<string | null>(null);
  const [followup, setFollowup] = useState<string | null>(null);
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{lead.data?.student_name ?? lead.data?.guardian_name ?? "…"}</SheetTitle>
        </SheetHeader>
        <div className="space-y-5 px-4 pb-6">
          <QueryView q={lead}>
            {(l) => (
              <>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-muted-foreground text-xs">{t("guardian")}</dt>
                    <dd>{l.guardian_name ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs">{t("phone")}</dt>
                    <dd className="tabular-nums">{l.phone ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs">{t("interest")}</dt>
                    <dd>{l.interest ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground text-xs">{t("source")}</dt>
                    <dd>{l.source}</dd>
                  </div>
                </dl>
                <div className="grid grid-cols-2 gap-3">
                  <Field label={tc("status")} htmlFor="ls">
                    <NativeSelect
                      id="ls"
                      className="w-full"
                      value={l.status}
                      onChange={(e) => onPatch({ status: e.target.value as Status })}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {t(`st_${s}`)}
                        </option>
                      ))}
                    </NativeSelect>
                  </Field>
                  <Field label={t("owner")} htmlFor="lo">
                    <NativeSelect
                      id="lo"
                      className="w-full"
                      value={l.owner_user_id ?? ""}
                      onChange={(e) =>
                        onPatch(
                          e.target.value
                            ? { owner_user_id: e.target.value }
                            : { clear_owner: true },
                        )
                      }
                    >
                      <option value="">—</option>
                      {members
                        .filter((m) => m.status === "active")
                        .map((m) => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.name}
                          </option>
                        ))}
                    </NativeSelect>
                  </Field>
                </div>
                <Field label={t("followup")} htmlFor="lf">
                  <div className="flex gap-2">
                    <Input
                      id="lf"
                      type="datetime-local"
                      value={
                        followup ?? (l.next_followup_at ? l.next_followup_at.slice(0, 16) : "")
                      }
                      onChange={(e) => setFollowup(e.target.value)}
                    />
                    <Button
                      variant="outline"
                      disabled={followup === null}
                      onClick={() => {
                        onPatch({
                          next_followup_at: followup ? new Date(followup).toISOString() : null,
                        });
                        setFollowup(null);
                      }}
                    >
                      {tc("save")}
                    </Button>
                  </div>
                </Field>
                <Field label={t("notes")} htmlFor="ln">
                  <Textarea
                    id="ln"
                    rows={4}
                    value={notes ?? l.notes ?? ""}
                    onChange={(e) => setNotes(e.target.value)}
                  />
                  <Button
                    size="sm"
                    className="mt-2"
                    disabled={notes === null}
                    onClick={() => {
                      onPatch({ notes: notes ?? "" });
                      setNotes(null);
                    }}
                  >
                    {tc("save")}
                  </Button>
                </Field>
                <section>
                  <h3 className="mb-2 text-sm font-medium">{t("timeline")}</h3>
                  <ol className="border-muted space-y-3 border-s ps-4 text-sm">
                    {l.timeline.map((ev, i) => (
                      <li key={i}>
                        <p>{ev.text}</p>
                        <p className="text-muted-foreground text-xs">
                          {ev.kind} · {fmtDateTime(ev.at, locale)}
                        </p>
                      </li>
                    ))}
                  </ol>
                </section>
              </>
            )}
          </QueryView>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function NewLeadDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const t = useTranslations("leads");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [form, setForm] = useState({
    student_name: "",
    guardian_name: "",
    phone: "",
    interest: "",
  });
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/leads", {
          body: {
            student_name: form.student_name || null,
            guardian_name: form.guardian_name || null,
            phone: form.phone || null,
            interest: form.interest || null,
          },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["leads"] });
      setForm({ student_name: "", guardian_name: "", phone: "", interest: "" });
      onOpenChange(false);
    },
  });
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("new")}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field label={t("student")} htmlFor="ns">
            <Input id="ns" value={form.student_name} onChange={set("student_name")} />
          </Field>
          <Field label={t("guardian")} htmlFor="ng">
            <Input id="ng" value={form.guardian_name} onChange={set("guardian_name")} />
          </Field>
          <Field label={t("phone")} htmlFor="np" hint="03XX XXXXXXX">
            <Input id="np" inputMode="tel" value={form.phone} onChange={set("phone")} />
          </Field>
          <Field label={t("interest")} htmlFor="ni">
            <Input id="ni" value={form.interest} onChange={set("interest")} />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={create.isPending}>
              {tc("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

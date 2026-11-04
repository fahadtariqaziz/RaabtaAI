"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, ChevronLeft, ChevronRight, Repeat } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { EmptyState, Field, NativeSelect, PageHeader, Pill, QueryView } from "@/components/common";
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
import { Skeleton } from "@/components/ui/skeleton";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useAuth, useMe } from "@/lib/auth";
import { fmtDateTime, fmtTime, localDate } from "@/lib/format";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Slot = Schemas["SlotOut"];
type Booking = Schemas["BookingOut"];
type Kind = "visit" | "test" | "counselling";
const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const KIND_COLOR: Record<string, string> = {
  visit: "border-s-[var(--chart-1)]",
  test: "border-s-[var(--chart-2)]",
  counselling: "border-s-[var(--chart-3)]",
};

/** Monday 00:00 (Karachi, UTC+5, no DST) of the week containing `d`, as a UTC Date. */
function weekStart(d: Date): Date {
  const local = new Date(d.getTime() + 5 * 3600_000);
  const dow = (local.getUTCDay() + 6) % 7;
  const monday = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() - dow);
  return new Date(monday - 5 * 3600_000);
}
/** "YYYY-MM-DDTHH:MM" (Karachi wall time) → ISO with +05:00. */
function karachiIso(local: string): string {
  return `${local}:00+05:00`;
}

export default function SlotsPage() {
  const t = useTranslations("slots");
  const { institutionId } = useAuth();
  const { can } = useMe();
  const { locale } = useLocale();
  const [anchor, setAnchor] = useState(() => weekStart(new Date()));
  const [newOpen, setNewOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [slot, setSlot] = useState<Slot | null>(null);
  const end = new Date(anchor.getTime() + 7 * 86400_000);
  const range = { from: anchor.toISOString(), to: end.toISOString() };

  const slots = useQuery({
    queryKey: ["slots", institutionId, range.from],
    queryFn: () => unwrap(api.GET("/api/v1/slots", { params: { query: range } })),
    enabled: !!institutionId,
  });
  const bookings = useQuery({
    queryKey: ["bookings", institutionId, range.from],
    queryFn: () => unwrap(api.GET("/api/v1/bookings", { params: { query: range } })),
    enabled: !!institutionId,
  });

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => new Date(anchor.getTime() + i * 86400_000)),
    [anchor],
  );
  const byDay = useMemo(() => {
    const m = new Map<string, Slot[]>();
    for (const s of slots.data ?? []) {
      const k = localDate(new Date(s.starts_at));
      m.set(k, [...(m.get(k) ?? []), s]);
    }
    return m;
  }, [slots.data]);
  const dayFmt = new Intl.DateTimeFormat(locale === "ur" ? "ur-PK" : "en-PK", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "Asia/Karachi",
  });

  return (
    <>
      <PageHeader
        title={t("title")}
        description={t("week", { date: dayFmt.format(anchor) })}
        actions={
          <>
            <Button
              variant="outline"
              size="icon"
              aria-label="Previous week"
              onClick={() => setAnchor(new Date(anchor.getTime() - 7 * 86400_000))}
            >
              <ChevronLeft className="rtl:rotate-180" />
            </Button>
            <Button variant="outline" onClick={() => setAnchor(weekStart(new Date()))}>
              {t("today")}
            </Button>
            <Button
              variant="outline"
              size="icon"
              aria-label="Next week"
              onClick={() => setAnchor(end)}
            >
              <ChevronRight className="rtl:rotate-180" />
            </Button>
            {can("admin") ? (
              <>
                <Button variant="outline" onClick={() => setBulkOpen(true)}>
                  <Repeat /> {t("bulk")}
                </Button>
                <Button onClick={() => setNewOpen(true)}>
                  <CalendarPlus /> {t("newSlot")}
                </Button>
              </>
            ) : null}
          </>
        }
      />
      <QueryView
        q={slots}
        skeleton={
          <div className="grid gap-2 md:grid-cols-7">
            {Array.from({ length: 7 }, (_, i) => (
              <Skeleton key={i} className="h-64" />
            ))}
          </div>
        }
      >
        {() => (
          <div className="grid gap-2 md:grid-cols-7">
            {days.map((d) => {
              const k = localDate(d);
              const list = byDay.get(k) ?? [];
              const today = k === localDate(new Date());
              return (
                <section
                  key={k}
                  aria-label={dayFmt.format(d)}
                  className={cn(
                    "bg-muted/40 min-h-40 rounded-xl p-2",
                    today && "ring-primary ring-2",
                  )}
                >
                  <h2 className="mb-2 text-sm font-medium">{dayFmt.format(d)}</h2>
                  <ul className="space-y-1.5">
                    {list.map((s) => (
                      <li key={s.id}>
                        <button
                          onClick={() => setSlot(s)}
                          className={cn(
                            "bg-card hover:bg-muted w-full rounded-lg border border-s-4 p-2 text-start text-xs",
                            KIND_COLOR[s.kind],
                          )}
                        >
                          <span className="block font-medium">
                            {fmtTime(s.starts_at, locale)}–{fmtTime(s.ends_at, locale)}
                          </span>
                          <span className="text-muted-foreground">
                            {t(s.kind as Kind)} · {s.booked_count}/{s.capacity}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {list.length === 0 ? <p className="text-muted-foreground text-xs">—</p> : null}
                </section>
              );
            })}
          </div>
        )}
      </QueryView>

      <h2 className="mt-8 mb-3 text-lg font-semibold">{t("bookings")}</h2>
      <QueryView q={bookings}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState />
          ) : (
            <BookingList bookings={list} slots={slots.data ?? []} />
          )
        }
      </QueryView>

      <NewSlotDialog open={newOpen} onOpenChange={setNewOpen} />
      <BulkDialog open={bulkOpen} onOpenChange={setBulkOpen} />
      {slot ? (
        <SlotSheet
          slot={slot}
          bookings={(bookings.data ?? []).filter((b) => b.slot.id === slot.id)}
          slots={slots.data ?? []}
          onClose={() => setSlot(null)}
        />
      ) : null}
    </>
  );
}

function useBookingPatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["BookingPatch"] }) =>
      unwrap(
        api.PATCH("/api/v1/bookings/{booking_id}", { params: { path: { booking_id: id } }, body }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["bookings"] });
      void qc.invalidateQueries({ queryKey: ["slots"] });
    },
  });
}

function BookingList({ bookings, slots }: { bookings: Booking[]; slots: Slot[] }) {
  const t = useTranslations("slots");
  const { locale } = useLocale();
  const patch = useBookingPatch();
  const tone = (s: string) =>
    s === "confirmed" || s === "attended"
      ? "good"
      : s === "cancelled" || s === "no_show"
        ? "bad"
        : "info";
  return (
    <ul className="divide-y rounded-xl border">
      {bookings.map((b) => (
        <li key={b.id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
          <span className="font-mono text-xs">{b.code}</span>
          <span className="font-medium">{b.student_name ?? b.contact_name ?? "—"}</span>
          <span className="text-muted-foreground tabular-nums">{b.contact_phone ?? ""}</span>
          <span className="text-muted-foreground">
            {t(b.slot.kind as Kind)} · {fmtDateTime(b.slot.starts_at, locale)}
          </span>
          <Pill tone={tone(b.status)}>{b.status}</Pill>
          {b.status !== "cancelled" ? (
            <div className="ms-auto flex flex-wrap gap-1">
              {b.status === "booked" ? (
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => patch.mutate({ id: b.id, body: { status: "confirmed" } })}
                >
                  {t("confirm")}
                </Button>
              ) : null}
              <Button
                size="xs"
                variant="outline"
                onClick={() => patch.mutate({ id: b.id, body: { status: "attended" } })}
              >
                {t("attended")}
              </Button>
              <Button
                size="xs"
                variant="outline"
                onClick={() => patch.mutate({ id: b.id, body: { status: "no_show" } })}
              >
                {t("noShow")}
              </Button>
              <NativeSelect
                aria-label={t("reschedule")}
                className="h-6 text-xs"
                value=""
                onChange={(e) =>
                  e.target.value && patch.mutate({ id: b.id, body: { slot_id: e.target.value } })
                }
              >
                <option value="">{t("reschedule")}…</option>
                {slots
                  .filter(
                    (s) =>
                      s.id !== b.slot.id && s.booked_count < s.capacity && s.kind === b.slot.kind,
                  )
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {fmtDateTime(s.starts_at, locale)}
                    </option>
                  ))}
              </NativeSelect>
              <Button
                size="xs"
                variant="destructive"
                onClick={() => patch.mutate({ id: b.id, body: { status: "cancelled" } })}
              >
                {t("cancelBooking")}
              </Button>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function SlotSheet({
  slot,
  bookings,
  slots,
  onClose,
}: {
  slot: Slot;
  bookings: Booking[];
  slots: Slot[];
  onClose: () => void;
}) {
  const t = useTranslations("slots");
  const tc = useTranslations("common");
  const { can } = useMe();
  const { locale } = useLocale();
  const qc = useQueryClient();
  const [capacity, setCapacity] = useState(String(slot.capacity));
  const [location, setLocation] = useState(slot.location ?? "");
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/slots/{slot_id}", {
          params: { path: { slot_id: slot.id } },
          body: { capacity: Number(capacity), location: location || null },
        }),
      ),
    onSuccess: () => {
      toast.success(tc("saved"));
      void qc.invalidateQueries({ queryKey: ["slots"] });
    },
  });
  const del = useMutation({
    mutationFn: () =>
      unwrap(api.DELETE("/api/v1/slots/{slot_id}", { params: { path: { slot_id: slot.id } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["slots"] });
      onClose();
    },
  });
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader>
          <SheetTitle>
            {t(slot.kind as Kind)} · {fmtDateTime(slot.starts_at, locale)}
          </SheetTitle>
        </SheetHeader>
        <div className="space-y-4 px-4 pb-6">
          {can("admin") ? (
            <div className="space-y-3">
              <Field label={t("capacity")} htmlFor="sc">
                <Input
                  id="sc"
                  type="number"
                  min={1}
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                />
              </Field>
              <Field label={t("location")} htmlFor="sl">
                <Input id="sl" value={location} onChange={(e) => setLocation(e.target.value)} />
              </Field>
              <div className="flex gap-2">
                <Button onClick={() => save.mutate()} disabled={save.isPending}>
                  {tc("save")}
                </Button>
                <Button variant="destructive" onClick={() => del.mutate()} disabled={del.isPending}>
                  {tc("delete")}
                </Button>
              </div>
            </div>
          ) : null}
          <h3 className="font-medium">
            {t("bookings")} ({slot.booked_count}/{slot.capacity})
          </h3>
          {bookings.length ? (
            <BookingList bookings={bookings} slots={slots} />
          ) : (
            <EmptyState className="p-6" />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function NewSlotDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const t = useTranslations("slots");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [kind, setKind] = useState<Kind>("visit");
  const [starts, setStarts] = useState("");
  const [duration, setDuration] = useState("60");
  const [capacity, setCapacity] = useState("5");
  const [location, setLocation] = useState("");
  const create = useMutation({
    mutationFn: () => {
      const s = new Date(karachiIso(starts));
      return unwrap(
        api.POST("/api/v1/slots", {
          body: {
            kind,
            starts_at: s.toISOString(),
            ends_at: new Date(s.getTime() + Number(duration) * 60_000).toISOString(),
            capacity: Number(capacity),
            location: location || null,
          },
        }),
      );
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["slots"] });
      onOpenChange(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("newSlot")}</DialogTitle>
        </DialogHeader>
        <form
          className="grid grid-cols-2 gap-3"
          onSubmit={(e) => (e.preventDefault(), create.mutate())}
        >
          <Field label={t("kind")} htmlFor="nk">
            <NativeSelect
              id="nk"
              className="w-full"
              value={kind}
              onChange={(e) => setKind(e.target.value as Kind)}
            >
              <option value="visit">{t("visit")}</option>
              <option value="test">{t("test")}</option>
              <option value="counselling">{t("counselling")}</option>
            </NativeSelect>
          </Field>
          <Field label={t("starts")} htmlFor="nst">
            <Input
              id="nst"
              type="datetime-local"
              required
              value={starts}
              onChange={(e) => setStarts(e.target.value)}
            />
          </Field>
          <Field label={t("duration")} htmlFor="nd">
            <Input
              id="nd"
              type="number"
              min={10}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </Field>
          <Field label={t("capacity")} htmlFor="nc">
            <Input
              id="nc"
              type="number"
              min={1}
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
            />
          </Field>
          <div className="col-span-2">
            <Field label={t("location")} htmlFor="nl">
              <Input id="nl" value={location} onChange={(e) => setLocation(e.target.value)} />
            </Field>
          </div>
          <DialogFooter className="col-span-2">
            <Button type="submit" disabled={!starts || create.isPending}>
              {tc("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BulkDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useTranslations("slots");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const [kind, setKind] = useState<Kind>("visit");
  const [from, setFrom] = useState(() => localDate(new Date()));
  const [to, setTo] = useState(() => localDate(new Date(Date.now() + 27 * 86400_000)));
  const [weekdays, setWeekdays] = useState<Set<string>>(
    new Set(["mon", "tue", "wed", "thu", "fri", "sat"]),
  );
  const [times, setTimes] = useState("10:00, 11:00, 12:00");
  const [duration, setDuration] = useState("60");
  const [capacity, setCapacity] = useState("5");
  const [location, setLocation] = useState("");
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/slots/bulk", {
          body: {
            kind,
            date_from: from,
            date_to: to,
            weekdays: [...weekdays] as (typeof WEEKDAYS)[number][],
            times: times
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
            duration_minutes: Number(duration),
            capacity: Number(capacity),
            location: location || null,
          },
        }),
      ),
    onSuccess: (r) => {
      toast.success(t("created", { n: r.created, skipped: r.skipped }));
      void qc.invalidateQueries({ queryKey: ["slots"] });
      onOpenChange(false);
    },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("bulk")}</DialogTitle>
        </DialogHeader>
        <form
          className="grid grid-cols-2 gap-3"
          onSubmit={(e) => (e.preventDefault(), create.mutate())}
        >
          <Field label={t("kind")} htmlFor="bk">
            <NativeSelect
              id="bk"
              className="w-full"
              value={kind}
              onChange={(e) => setKind(e.target.value as Kind)}
            >
              <option value="visit">{t("visit")}</option>
              <option value="test">{t("test")}</option>
              <option value="counselling">{t("counselling")}</option>
            </NativeSelect>
          </Field>
          <Field label={t("capacity")} htmlFor="bc">
            <Input
              id="bc"
              type="number"
              min={1}
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
            />
          </Field>
          <Field label={t("from")} htmlFor="bf">
            <Input id="bf" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          </Field>
          <Field label={t("to")} htmlFor="bt">
            <Input id="bt" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          </Field>
          <fieldset className="col-span-2">
            <legend className="mb-1.5 text-sm font-medium">{t("weekdays")}</legend>
            <div className="flex flex-wrap gap-1">
              {WEEKDAYS.map((d) => (
                <label
                  key={d}
                  className={cn(
                    "cursor-pointer rounded-md border px-2 py-1 text-xs uppercase",
                    weekdays.has(d) && "bg-primary text-primary-foreground",
                  )}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={weekdays.has(d)}
                    onChange={() => {
                      const n = new Set(weekdays);
                      if (n.has(d)) n.delete(d);
                      else n.add(d);
                      setWeekdays(n);
                    }}
                  />
                  {d}
                </label>
              ))}
            </div>
          </fieldset>
          <Field label={t("times")} htmlFor="btm">
            <Input id="btm" value={times} onChange={(e) => setTimes(e.target.value)} />
          </Field>
          <Field label={t("duration")} htmlFor="bd">
            <Input
              id="bd"
              type="number"
              min={10}
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </Field>
          <div className="col-span-2">
            <Field label={t("location")} htmlFor="bl">
              <Input id="bl" value={location} onChange={(e) => setLocation(e.target.value)} />
            </Field>
          </div>
          <DialogFooter className="col-span-2">
            <Button type="submit" disabled={create.isPending || weekdays.size === 0}>
              {tc("create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

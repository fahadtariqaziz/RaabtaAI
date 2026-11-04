"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Bot, CircleAlert, Flag, UserRound } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState, ErrorState, PageHeader } from "@/components/common";
import { TrendChart } from "@/components/dashboard/trend-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDuration, fmtNumber, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";

type Range = "7d" | "30d" | "90d";
type Kpis = Schemas["Kpis"];

function Delta({ now, prev }: { now: number; prev?: number }) {
  const t = useTranslations("overview");
  if (prev === undefined || prev === 0) return null;
  const pct = Math.round(((now - prev) / prev) * 100);
  const up = pct >= 0;
  return (
    <span
      className="text-muted-foreground inline-flex items-center gap-0.5 text-xs"
      title={t("vsPrev")}
    >
      {up ? (
        <ArrowUpRight className="size-3" aria-hidden />
      ) : (
        <ArrowDownRight className="size-3" aria-hidden />
      )}
      {up ? "+" : ""}
      {pct}%<span className="sr-only"> {t("vsPrev")}</span>
    </span>
  );
}

function Tile({
  label,
  value,
  delta,
  hint,
}: {
  label: string;
  value: string;
  delta?: React.ReactNode;
  hint?: string;
}) {
  return (
    <Card size="sm">
      <CardContent className="space-y-1">
        <p className="text-muted-foreground text-sm">{label}</p>
        <p className="text-2xl font-semibold tabular-nums">{value}</p>
        <div className="min-h-4">
          {delta ?? (hint ? <span className="text-muted-foreground text-xs">{hint}</span> : null)}
        </div>
      </CardContent>
    </Card>
  );
}

const ATTENTION_ICON = {
  human_waiting: UserRound,
  flagged: Flag,
  facts_pending: CircleAlert,
  documents_failed: CircleAlert,
} as const;
const ATTENTION_HREF = {
  human_waiting: "/inbox?mode=human",
  flagged: "/inbox?flagged=1",
  facts_pending: "/knowledge?tab=facts",
  documents_failed: "/knowledge",
} as const;

export default function OverviewPage() {
  const t = useTranslations("overview");
  const tl = useTranslations("leads");
  const { institutionId } = useAuth();
  const [range, setRange] = useState<Range>("30d");
  const [table, setTable] = useState(false);
  const q = useQuery({
    queryKey: ["metrics", institutionId, range],
    queryFn: () => unwrap(api.GET("/api/v1/metrics/overview", { params: { query: { range } } })),
    enabled: !!institutionId,
  });
  const k = q.data?.kpis;
  const p = q.data?.previous ?? undefined;
  const tile = (
    label: string,
    key: keyof Kpis,
    fmt: (v: number) => string = (v) => fmtNumber(v),
  ) =>
    k ? (
      <Tile
        label={label}
        value={fmt(Number(k[key] ?? 0))}
        delta={<Delta now={Number(k[key] ?? 0)} prev={p ? Number(p[key] ?? 0) : undefined} />}
      />
    ) : null;

  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          <div role="group" aria-label="Range" className="bg-muted inline-flex rounded-lg p-0.5">
            {(["7d", "30d", "90d"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                aria-pressed={range === r}
                className={cn(
                  "rounded-md px-3 py-1 text-sm",
                  range === r ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
                )}
              >
                {t(r === "7d" ? "range7" : r === "30d" ? "range30" : "range90")}
              </button>
            ))}
          </div>
        }
      />
      {q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !q.data || !k ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
          <Skeleton className="col-span-2 h-72 lg:col-span-4" />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {tile(t("conversations"), "conversations")}
            {tile(t("leads"), "leads")}
            {tile(t("visits"), "visits_booked")}
            <Tile
              label={`${t("aiResolved")} / ${t("handedOff")}`}
              value={`${fmtNumber(k.ai_resolved)} / ${fmtNumber(k.handed_off)}`}
              hint={
                k.conversations
                  ? `${Math.round((k.ai_resolved / k.conversations) * 100)}% AI`
                  : undefined
              }
            />
            <Tile label={t("firstResponse")} value={fmtDuration(k.median_first_response_s)} />
            <Tile label={t("staffResponse")} value={fmtDuration(k.median_staff_response_s)} />
            <Tile label={t("aiCost")} value={fmtUsd(k.ai_cost_usd)} />
            <Tile label={t("feeRecovered")} value="—" hint={t("feeLater")} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>{t("trend")}</CardTitle>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setTable((v) => !v)}
                  aria-pressed={table}
                >
                  {t("tableView")}
                </Button>
              </CardHeader>
              <CardContent>
                {table ? (
                  <div className="max-h-64 overflow-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Date</TableHead>
                          <TableHead className="text-end">{t("conversations")}</TableHead>
                          <TableHead className="text-end">{t("leads")}</TableHead>
                          <TableHead className="text-end">{t("messagesIn")}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {q.data.trend.map((d) => (
                          <TableRow key={d.date}>
                            <TableCell>{d.date}</TableCell>
                            <TableCell className="text-end tabular-nums">
                              {d.conversations}
                            </TableCell>
                            <TableCell className="text-end tabular-nums">{d.leads}</TableCell>
                            <TableCell className="text-end tabular-nums">{d.messages_in}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <TrendChart
                    data={q.data.trend}
                    labels={{ conversations: t("conversations"), leads: t("leads") }}
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>{t("attention")}</CardTitle>
              </CardHeader>
              <CardContent>
                {q.data.attention.every((a) => a.count === 0) ? (
                  <EmptyState
                    title={t("allClear")}
                    icon={<Bot className="size-5" />}
                    className="p-6"
                  />
                ) : (
                  <ul className="space-y-2">
                    {q.data.attention
                      .filter((a) => a.count > 0)
                      .map((a) => {
                        const kind = a.kind as keyof typeof ATTENTION_ICON;
                        const Icon = ATTENTION_ICON[kind] ?? CircleAlert;
                        return (
                          <li key={a.kind}>
                            <Link
                              href={ATTENTION_HREF[kind] ?? "/"}
                              className="hover:bg-muted flex items-center gap-3 rounded-lg border p-3 text-sm"
                            >
                              <Icon className="text-muted-foreground size-4" aria-hidden />
                              <span className="flex-1">{t(kind)}</span>
                              <span className="font-semibold tabular-nums">{a.count}</span>
                            </Link>
                          </li>
                        );
                      })}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{t("funnel")}</CardTitle>
              </CardHeader>
              <CardContent>
                <Funnel
                  data={q.data.funnel as { stage: string; count: number }[]}
                  label={(s) => tl(`st_${s}`)}
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>{t("channels")}</CardTitle>
              </CardHeader>
              <CardContent>
                <Bars
                  data={Object.entries(q.data.channels).map(([k2, v]) => ({ label: k2, count: v }))}
                  color={() => "var(--chart-1)"}
                />
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}

/** Ordinal stages → one-hue ramp (ramp-1 nearest the surface still clears 2:1), value labels in
 * text ink, 4px rounded ends, hover title. */
function Funnel({
  data,
  label,
}: {
  data: { stage: string; count: number }[];
  label: (s: string) => string;
}) {
  const stages = data.filter((d) => d.stage !== "lost");
  const lost = data.find((d) => d.stage === "lost");
  return (
    <div className="space-y-3">
      <Bars
        data={stages.map((d) => ({ label: label(d.stage), count: d.count }))}
        color={(i) => `var(--ramp-${Math.min(i + 1, 5)})`}
      />
      {lost ? (
        <p className="text-muted-foreground text-xs">
          {label("lost")}: {lost.count}
        </p>
      ) : null}
    </div>
  );
}

function Bars({
  data,
  color,
}: {
  data: { label: string; count: number }[];
  color: (i: number) => string;
}) {
  const max = Math.max(1, ...data.map((d) => d.count));
  if (!data.length) return <EmptyState className="p-6" />;
  return (
    <ul className="space-y-2">
      {data.map((d, i) => (
        <li
          key={d.label}
          className="grid grid-cols-[7rem_1fr_3rem] items-center gap-2 text-sm"
          title={`${d.label}: ${d.count}`}
        >
          <span className="truncate capitalize">{d.label}</span>
          <span className="bg-muted h-5 overflow-hidden rounded">
            <span
              className="block h-full rounded"
              style={{
                width: `${(d.count / max) * 100}%`,
                background: color(i),
                minWidth: d.count ? 4 : 0,
              }}
            />
          </span>
          <span className="text-end tabular-nums">{d.count}</span>
        </li>
      ))}
    </ul>
  );
}

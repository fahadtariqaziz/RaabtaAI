"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader, QueryView } from "@/components/common";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, unwrap } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtNumber, fmtUsd, localDate } from "@/lib/format";

export default function UsagePage() {
  const t = useTranslations("usage");
  const { institutionId } = useAuth();
  const [month, setMonth] = useState(() => localDate(new Date()).slice(0, 7));
  const from = `${month}-01`;
  const [y, m] = month.split("-").map(Number);
  const to = localDate(new Date(Date.UTC(y, m, 0, 12)));
  const limits = useQuery({
    queryKey: ["usage-limits", institutionId, month],
    queryFn: () => unwrap(api.GET("/api/v1/usage/limits", { params: { query: { month } } })),
    enabled: !!institutionId,
  });
  const daily = useQuery({
    queryKey: ["usage", institutionId, month],
    queryFn: () => unwrap(api.GET("/api/v1/usage", { params: { query: { from, to } } })),
    enabled: !!institutionId,
  });
  const bar = (
    label: string,
    used: number | string,
    limit: number | string | null | undefined,
    money = false,
  ) => {
    const u = Number(used);
    const l = limit == null ? null : Number(limit);
    const pct = l ? Math.min(100, (u / l) * 100) : 0;
    return (
      <Card size="sm" key={label}>
        <CardContent className="space-y-2">
          <div className="flex items-baseline justify-between">
            <span className="text-muted-foreground text-sm">{label}</span>
            <span className="text-sm tabular-nums">
              <strong>{money ? fmtUsd(u) : fmtNumber(u)}</strong> /{" "}
              {l == null ? t("unlimited") : money ? fmtUsd(l) : fmtNumber(l)}
            </span>
          </div>
          <Progress value={pct} aria-label={label} />
        </CardContent>
      </Card>
    );
  };
  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          <label className="flex items-center gap-2 text-sm">
            {t("month")}
            <Input
              type="month"
              value={month}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
              className="w-40"
            />
          </label>
        }
      />
      <QueryView q={limits}>
        {(l) => (
          <div className="space-y-3">
            <p className="text-sm">
              {t("plan")}: <strong>{l.plan ?? t("noPlan")}</strong>
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              {bar(t("conversations"), l.conversations.used, l.conversations.limit)}
              {bar(t("templateSends"), l.template_sends.used, l.template_sends.limit)}
              {bar(t("aiCost"), l.ai_cost_usd.used, l.ai_cost_usd.limit, true)}
              {bar(t("seats"), l.seats.used, l.seats.limit)}
            </div>
          </div>
        )}
      </QueryView>
      <Card className="mt-6">
        <CardHeader>
          <CardTitle>{t("daily")}</CardTitle>
        </CardHeader>
        <CardContent>
          <QueryView q={daily}>
            {(d) => (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead className="text-end">{t("conversations")}</TableHead>
                      <TableHead className="text-end">In</TableHead>
                      <TableHead className="text-end">Out</TableHead>
                      <TableHead className="text-end">{t("templateSends")}</TableHead>
                      <TableHead className="text-end">{t("aiCost")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {d.days.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-muted-foreground text-center">
                          —
                        </TableCell>
                      </TableRow>
                    ) : (
                      d.days.map((r) => (
                        <TableRow key={r.date}>
                          <TableCell>{r.date}</TableCell>
                          <TableCell className="text-end tabular-nums">{r.conversations}</TableCell>
                          <TableCell className="text-end tabular-nums">{r.messages_in}</TableCell>
                          <TableCell className="text-end tabular-nums">{r.messages_out}</TableCell>
                          <TableCell className="text-end tabular-nums">
                            {r.template_sends}
                          </TableCell>
                          <TableCell className="text-end tabular-nums">
                            {fmtUsd(r.llm_cost_usd)}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            )}
          </QueryView>
        </CardContent>
      </Card>
    </>
  );
}

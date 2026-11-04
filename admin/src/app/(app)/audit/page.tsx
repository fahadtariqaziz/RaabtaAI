"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Fragment, useState } from "react";
import {
  EmptyState,
  ErrorState,
  NativeSelect,
  PageHeader,
  SkeletonRows,
} from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { fmtDateTime } from "@/lib/format";
import { useLocale } from "@/lib/i18n";

type Row = Schemas["AuditOut"];
const ENTITIES = [
  "",
  "lead",
  "conversation",
  "slot",
  "booking",
  "membership",
  "institution",
  "fact",
  "document",
  "http",
];

/** Field-level diff of before/after (keys whose values changed). */
function Diff({ before, after }: { before: Row["before"]; after: Row["after"] }) {
  const t = useTranslations("audit");
  const keys = Array.from(new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]));
  const changed = keys.filter((k) => JSON.stringify(before?.[k]) !== JSON.stringify(after?.[k]));
  if (!changed.length) return <p className="text-muted-foreground text-xs">—</p>;
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-muted-foreground">
          <th className="text-start font-normal">field</th>
          <th className="text-start font-normal">{t("before")}</th>
          <th className="text-start font-normal">{t("after")}</th>
        </tr>
      </thead>
      <tbody>
        {changed.map((k) => (
          <tr key={k} className="align-top">
            <td className="pe-3 font-mono">{k}</td>
            <td className="pe-3 text-red-700 dark:text-red-400">
              <pre className="whitespace-pre-wrap">
                {before?.[k] === undefined ? "—" : JSON.stringify(before[k], null, 1)}
              </pre>
            </td>
            <td className="text-emerald-700 dark:text-emerald-400">
              <pre className="whitespace-pre-wrap">
                {after?.[k] === undefined ? "—" : JSON.stringify(after[k], null, 1)}
              </pre>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AuditPage() {
  const t = useTranslations("audit");
  const { institutionId } = useAuth();
  const { locale } = useLocale();
  const [entity, setEntity] = useState("");
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const q = useInfiniteQuery({
    queryKey: ["audit", institutionId, entity, action, since],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/audit-log", {
          params: {
            query: {
              entity: entity || undefined,
              action: action || undefined,
              since: since ? new Date(since).toISOString() : undefined,
              before: pageParam,
              limit: 50,
            },
          },
        }),
      ),
    getNextPageParam: (last) => (last.length === 50 ? last[last.length - 1].created_at : undefined),
    enabled: !!institutionId,
  });
  const rows = q.data?.pages.flat() ?? [];
  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          <>
            <NativeSelect
              aria-label={t("entity")}
              value={entity}
              onChange={(e) => setEntity(e.target.value)}
            >
              {ENTITIES.map((e) => (
                <option key={e} value={e}>
                  {e || `${t("entity")}: *`}
                </option>
              ))}
            </NativeSelect>
            <Input
              aria-label={t("action")}
              placeholder={`${t("action")} (e.g. lead.)`}
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="w-44"
            />
            <Input
              aria-label="Since"
              type="date"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className="w-40"
            />
          </>
        }
      />
      {q.isPending ? (
        <SkeletonRows rows={10} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState />
      ) : (
        <div className="overflow-x-auto rounded-xl border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("when")}</TableHead>
                <TableHead>{t("actor")}</TableHead>
                <TableHead>{t("action")}</TableHead>
                <TableHead>{t("entity")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((r) => (
                <Fragment key={r.id}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => setOpen(open === r.id ? null : r.id)}
                  >
                    <TableCell className="whitespace-nowrap">
                      <button
                        type="button"
                        className="focus-visible:ring-ring rounded-sm underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
                        aria-expanded={open === r.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(open === r.id ? null : r.id);
                        }}
                      >
                        {fmtDateTime(r.created_at, locale)}
                      </button>
                    </TableCell>
                    <TableCell>{r.actor_email ?? "system"}</TableCell>
                    <TableCell className="font-mono text-xs">{r.action}</TableCell>
                    <TableCell className="text-xs">
                      {r.entity}
                      {r.entity_id ? ` · ${r.entity_id.slice(0, 8)}` : ""}
                    </TableCell>
                  </TableRow>
                  {open === r.id ? (
                    <TableRow>
                      <TableCell colSpan={4} className="bg-muted/40">
                        <Diff before={r.before} after={r.after} />
                        <p className="text-muted-foreground mt-2 text-xs">IP {r.ip ?? "—"}</p>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {q.hasNextPage ? (
        <Button
          variant="outline"
          className="mt-4"
          onClick={() => q.fetchNextPage()}
          disabled={q.isFetchingNextPage}
        >
          {t("loadMore")}
        </Button>
      ) : null}
    </>
  );
}

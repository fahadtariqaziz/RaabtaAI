"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { EmptyState, Field, NativeSelect, PageHeader, Pill, QueryView } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useAuth, useMe } from "@/lib/auth";
import { fmtDateTime, fmtNumber, fmtUsd } from "@/lib/format";

export default function SuperadminPage() {
  const t = useTranslations("super");
  const { isSuperadmin } = useMe();
  const { startImpersonation } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const tenants = useQuery({
    queryKey: ["sa-tenants"],
    queryFn: () => unwrap(api.GET("/api/v1/superadmin/institutions")),
    enabled: isSuperadmin,
  });
  const plans = useQuery({
    queryKey: ["sa-plans"],
    queryFn: () => unwrap(api.GET("/api/v1/superadmin/plans")),
    enabled: isSuperadmin,
  });
  const usage = useQuery({
    queryKey: ["sa-usage"],
    queryFn: () => unwrap(api.GET("/api/v1/superadmin/usage")),
    enabled: isSuperadmin,
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Schemas["TenantPatch"] }) =>
      unwrap(
        api.PATCH("/api/v1/superadmin/institutions/{institution_id}", {
          params: { path: { institution_id: id } },
          body,
        }),
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sa-tenants"] }),
  });
  const impersonate = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/superadmin/impersonate/{institution_id}", {
          params: { path: { institution_id: id } },
        }),
      ),
    onSuccess: (r) => {
      const imp = r as {
        institution_id: string;
        institution_name: string;
        institution_slug: string;
        expires_at: string;
      };
      startImpersonation(imp);
      router.push("/");
    },
  });
  if (!isSuperadmin) return <EmptyState title="403" />;
  const totals = (usage.data?.totals ?? {}) as Record<string, number | string>;
  return (
    <>
      <PageHeader
        title={t("title")}
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> {t("newTenant")}
          </Button>
        }
      />
      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <Card size="sm">
          <CardContent>
            <p className="text-muted-foreground text-sm">{t("tenants")}</p>
            <p className="text-2xl font-semibold">{fmtNumber(totals.tenants)}</p>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardContent>
            <p className="text-muted-foreground text-sm">Active users</p>
            <p className="text-2xl font-semibold">{fmtNumber(totals.active_users)}</p>
          </CardContent>
        </Card>
        <Card size="sm">
          <CardContent>
            <p className="text-muted-foreground text-sm">{t("globalUsage")}</p>
            <p className="text-2xl font-semibold">{fmtUsd(totals.cost_usd)}</p>
          </CardContent>
        </Card>
      </div>
      <QueryView q={tenants}>
        {(list) => (
          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("tenants")}</TableHead>
                  <TableHead>{t("plan")}</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-end">{t("members")}</TableHead>
                  <TableHead className="text-end">{t("conv30")}</TableHead>
                  <TableHead className="text-end">{t("cost30")}</TableHead>
                  <TableHead>{t("lastActivity")}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <p className="font-medium">{r.name}</p>
                      <p className="text-muted-foreground text-xs">
                        {r.slug} · {r.type} · {r.city}
                      </p>
                    </TableCell>
                    <TableCell>
                      <NativeSelect
                        aria-label={t("plan")}
                        value={r.plan_id ?? ""}
                        onChange={(e) =>
                          patch.mutate({
                            id: r.id,
                            body: e.target.value
                              ? { plan_id: e.target.value }
                              : { clear_plan: true },
                          })
                        }
                      >
                        <option value="">—</option>
                        {(plans.data ?? []).map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </NativeSelect>
                    </TableCell>
                    <TableCell>
                      <NativeSelect
                        aria-label="Status"
                        value={r.status}
                        onChange={(e) =>
                          patch.mutate({
                            id: r.id,
                            body: { status: e.target.value as "trial" | "active" | "suspended" },
                          })
                        }
                      >
                        <option value="trial">trial</option>
                        <option value="active">active</option>
                        <option value="suspended">suspended</option>
                      </NativeSelect>
                    </TableCell>
                    <TableCell className="text-end tabular-nums">{r.members}</TableCell>
                    <TableCell className="text-end tabular-nums">{r.conversations_30d}</TableCell>
                    <TableCell className="text-end tabular-nums">
                      {fmtUsd(r.ai_cost_30d_usd)}
                    </TableCell>
                    <TableCell>{fmtDateTime(r.last_activity_at)}</TableCell>
                    <TableCell>
                      <Button size="sm" variant="outline" onClick={() => impersonate.mutate(r.id)}>
                        {t("impersonate")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </QueryView>
      <NewTenant open={creating} onOpenChange={setCreating} plans={plans.data ?? []} />
    </>
  );
}

function NewTenant({
  open,
  onOpenChange,
  plans,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  plans: Schemas["PlanOut"][];
}) {
  const t = useTranslations("super");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const empty = {
    slug: "",
    name: "",
    type: "school" as const,
    city: "",
    owner_email: "",
    owner_name: "",
    plan_id: "",
  };
  const [f, setF] = useState<{
    slug: string;
    name: string;
    type: "school" | "college" | "university";
    city: string;
    owner_email: string;
    owner_name: string;
    plan_id: string;
  }>(empty);
  const [link, setLink] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/superadmin/institutions", { body: { ...f, plan_id: f.plan_id || null } }),
      ),
    onSuccess: (r) => {
      const res = r as { owner_invite_url?: string | null };
      void qc.invalidateQueries({ queryKey: ["sa-tenants"] });
      setF(empty);
      if (res.owner_invite_url) setLink(res.owner_invite_url);
      else {
        toast.success(tc("saved"));
        onOpenChange(false);
      }
    },
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open={open} onOpenChange={(o) => (onOpenChange(o), setLink(null))}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("newTenant")}</DialogTitle>
        </DialogHeader>
        {link ? (
          <div className="space-y-2 text-sm">
            <Pill tone="good">✓</Pill>
            <p>Owner invite link:</p>
            <Input
              readOnly
              value={link}
              aria-label="Invite link"
              onFocus={(e) => e.target.select()}
            />
          </div>
        ) : (
          <form
            className="grid grid-cols-2 gap-3"
            onSubmit={(e) => (e.preventDefault(), create.mutate())}
          >
            <Field label="Name" htmlFor="t-name">
              <Input id="t-name" required value={f.name} onChange={set("name")} />
            </Field>
            <Field label={t("slug")} htmlFor="t-slug">
              <Input
                id="t-slug"
                required
                pattern="[a-z0-9][a-z0-9-]{2,62}"
                value={f.slug}
                onChange={set("slug")}
              />
            </Field>
            <Field label="Type" htmlFor="t-type">
              <NativeSelect id="t-type" className="w-full" value={f.type} onChange={set("type")}>
                <option value="school">school</option>
                <option value="college">college</option>
                <option value="university">university</option>
              </NativeSelect>
            </Field>
            <Field label="City" htmlFor="t-city">
              <Input id="t-city" required value={f.city} onChange={set("city")} />
            </Field>
            <Field label={t("ownerName")} htmlFor="t-on">
              <Input id="t-on" required value={f.owner_name} onChange={set("owner_name")} />
            </Field>
            <Field label={t("ownerEmail")} htmlFor="t-oe">
              <Input
                id="t-oe"
                type="email"
                required
                value={f.owner_email}
                onChange={set("owner_email")}
              />
            </Field>
            <Field label={t("plan")} htmlFor="t-plan">
              <NativeSelect
                id="t-plan"
                className="w-full"
                value={f.plan_id}
                onChange={set("plan_id")}
              >
                <option value="">—</option>
                {plans.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <DialogFooter className="col-span-2">
              <Button type="submit" disabled={create.isPending}>
                {tc("create")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

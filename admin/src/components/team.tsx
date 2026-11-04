"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Field, NativeSelect, Pill, QueryView } from "@/components/common";
import { Button } from "@/components/ui/button";
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
import { api, unwrap } from "@/lib/api/client";
import { type Role, useAuth, useMe } from "@/lib/auth";

export function TeamPanel() {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const { institutionId } = useAuth();
  const { can, user } = useMe();
  const qc = useQueryClient();
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const [form, setForm] = useState({ email: "", name: "", role: "staff" as Role });
  const members = useQuery({
    queryKey: ["members", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/members")),
    enabled: !!institutionId,
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["members"] });
  const invite = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/members/invite", { body: form })),
    onSuccess: (r) => {
      setLink(r.invite_url);
      setForm({ email: "", name: "", role: "staff" });
      refresh();
    },
  });
  const update = useMutation({
    mutationFn: ({
      id,
      role,
      status,
    }: {
      id: string;
      role?: Role;
      status?: "active" | "disabled";
    }) =>
      unwrap(
        api.PATCH("/api/v1/members/{member_id}", {
          params: { path: { member_id: id } },
          body: { role, status },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/v1/members/{member_id}", { params: { path: { member_id: id } } })),
    onSuccess: refresh,
  });
  const admin = can("admin");
  return (
    <div className="max-w-3xl space-y-4">
      {admin ? (
        <Button onClick={() => (setLink(null), setInviting(true))}>
          <UserPlus /> {t("invite")}
        </Button>
      ) : null}
      <QueryView q={members}>
        {(list) => (
          <div className="overflow-x-auto rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("name")}</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>{t("role")}</TableHead>
                  <TableHead>{tc("status")}</TableHead>
                  {admin ? <TableHead className="text-end">{tc("actions")}</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="font-medium">{m.name}</TableCell>
                    <TableCell>{m.email}</TableCell>
                    <TableCell>
                      {admin && m.user_id !== user?.id ? (
                        <NativeSelect
                          aria-label={t("role")}
                          value={m.role}
                          onChange={(e) =>
                            update.mutate({ id: m.id, role: e.target.value as Role })
                          }
                        >
                          <option value="owner" disabled={!can("owner")}>
                            owner
                          </option>
                          <option value="admin">admin</option>
                          <option value="staff">staff</option>
                        </NativeSelect>
                      ) : (
                        m.role
                      )}
                    </TableCell>
                    <TableCell>
                      <Pill
                        tone={
                          m.status === "active"
                            ? "good"
                            : m.status === "invited"
                              ? "warn"
                              : "neutral"
                        }
                      >
                        {m.status}
                      </Pill>
                    </TableCell>
                    {admin ? (
                      <TableCell className="text-end">
                        {m.user_id !== user?.id ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() =>
                              confirm(`${t("remove")} ${m.name}?`) && remove.mutate(m.id)
                            }
                          >
                            {t("remove")}
                          </Button>
                        ) : null}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </QueryView>
      <Dialog open={inviting} onOpenChange={setInviting}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("invite")}</DialogTitle>
          </DialogHeader>
          {link ? (
            <div className="space-y-2">
              <p className="text-sm">{t("inviteLink")}</p>
              <div className="flex gap-2">
                <Input readOnly value={link} aria-label="Invite link" />
                <Button
                  size="icon"
                  variant="outline"
                  aria-label={tc("copy")}
                  onClick={() =>
                    navigator.clipboard.writeText(link).then(() => toast.success(tc("copied")))
                  }
                >
                  <Copy />
                </Button>
              </div>
            </div>
          ) : (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                invite.mutate();
              }}
            >
              <Field label={t("name")} htmlFor="i-name">
                <Input
                  id="i-name"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </Field>
              <Field label="Email" htmlFor="i-email">
                <Input
                  id="i-email"
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
              </Field>
              <Field label={t("role")} htmlFor="i-role">
                <NativeSelect
                  id="i-role"
                  className="w-full"
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
                >
                  <option value="staff">staff</option>
                  <option value="admin">admin</option>
                  {can("owner") ? <option value="owner">owner</option> : null}
                </NativeSelect>
              </Field>
              <DialogFooter>
                <Button type="submit" disabled={invite.isPending}>
                  {t("invite")}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

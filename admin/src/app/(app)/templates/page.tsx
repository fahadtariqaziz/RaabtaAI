"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { FileText, Plus, RefreshCw, Send, Sparkles, Trash2 } from "lucide-react";
import { EmptyState, Field, NativeSelect, PageHeader, Pill, QueryView } from "@/components/common";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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

type Tpl = Schemas["TemplateOut"];
type Lang = "en" | "ur" | "roman_ur";
const PLACEHOLDER = /\{\{\s*([a-z][a-z0-9_]{0,31})\s*\}\}/g;
const TONE: Record<string, "neutral" | "info" | "good" | "warn" | "bad"> = {
  draft: "neutral",
  pending: "info",
  approved: "good",
  rejected: "bad",
  paused: "warn",
  disabled: "bad",
};
const EDITABLE = new Set(["draft", "rejected"]);

function variablesOf(body: string): string[] {
  const out: string[] = [];
  for (const m of body.matchAll(PLACEHOLDER)) if (!out.includes(m[1])) out.push(m[1]);
  return out;
}

function preview(body: string, vars: string[], examples: string[]): string {
  return body.replace(PLACEHOLDER, (_, v: string) => examples[vars.indexOf(v)] || `{{${v}}}`);
}

export default function TemplatesPage() {
  const t = useTranslations("templates");
  const { institutionId } = useAuth();
  const { can } = useMe();
  const admin = can("admin");
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Tpl | "new" | null>(null);
  const list = useQuery({
    queryKey: ["templates", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/templates")),
    enabled: !!institutionId,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["templates"] });
  const seed = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/templates/seed")),
    onSuccess: (rows) => {
      toast.success(t("seeded", { n: rows.length }));
      void refresh();
    },
  });
  const sync = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/templates/sync")),
    onSuccess: (r) => {
      toast.success(t("synced", { n: r.updated }));
      void refresh();
    },
  });
  const submit = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.POST("/api/v1/templates/{template_id}/submit", {
          params: { path: { template_id: id } },
        }),
      ),
    onSuccess: () => {
      toast.success(t("submitted"));
      void refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/v1/templates/{template_id}", { params: { path: { template_id: id } } }),
      ),
    onSuccess: () => void refresh(),
  });

  return (
    <div>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          admin ? (
            <>
              <Button variant="outline" onClick={() => seed.mutate()} disabled={seed.isPending}>
                <Sparkles /> {t("seed")}
              </Button>
              <Button variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}>
                <RefreshCw /> {t("sync")}
              </Button>
              <Button onClick={() => setEditing("new")}>
                <Plus /> {t("new")}
              </Button>
            </>
          ) : null
        }
      />
      <QueryView q={list}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState
              icon={<FileText className="size-5" />}
              title={t("empty")}
              hint={t("emptyHint")}
            />
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("name")}</TableHead>
                    <TableHead>{t("language")}</TableHead>
                    <TableHead>{t("status")}</TableHead>
                    <TableHead className="w-1/2">{t("body")}</TableHead>
                    {admin ? (
                      <TableHead>
                        <span className="sr-only">{t("actions")}</span>
                      </TableHead>
                    ) : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell className="font-mono text-xs">
                        {r.name}
                        {r.meta_name !== r.name ? (
                          <span className="text-muted-foreground block">{r.meta_name}</span>
                        ) : null}
                      </TableCell>
                      <TableCell>{t(`lang_${r.language as Lang}`)}</TableCell>
                      <TableCell>
                        <Pill tone={TONE[r.status] ?? "neutral"}>{t(`st_${r.status}`)}</Pill>
                        {r.rejected_reason ? (
                          <span className="text-destructive mt-1 block text-xs">
                            {r.rejected_reason}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell
                        className="max-w-md truncate text-sm"
                        dir={r.language === "ur" ? "rtl" : undefined}
                        lang={r.language === "ur" ? "ur" : undefined}
                        title={r.body}
                      >
                        {r.body}
                      </TableCell>
                      {admin ? (
                        <TableCell className="whitespace-nowrap">
                          {EDITABLE.has(r.status) ? (
                            <div className="flex gap-1">
                              <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>
                                {t("edit")}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => submit.mutate(r.id)}
                                disabled={submit.isPending}
                              >
                                <Send /> {t("submit")}
                              </Button>
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                aria-label={t("delete", { name: r.name })}
                                onClick={() => remove.mutate(r.id)}
                              >
                                <Trash2 />
                              </Button>
                            </div>
                          ) : null}
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
        <Editor
          tpl={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function Editor({
  tpl,
  onClose,
  onSaved,
}: {
  tpl: Tpl | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("templates");
  const tc = useTranslations("common");
  const [name, setName] = useState(tpl?.name ?? "");
  const [language, setLanguage] = useState<Lang>((tpl?.language as Lang) ?? "roman_ur");
  const [category, setCategory] = useState<"utility" | "marketing">(
    (tpl?.category as "utility" | "marketing") ?? "utility",
  );
  const [body, setBody] = useState(tpl?.body ?? "");
  const vars = useMemo(() => variablesOf(body), [body]);
  const [examples, setExamples] = useState<string[]>(tpl?.examples ?? []);
  const rtl = language === "ur";
  const save = useMutation({
    mutationFn: () => {
      const ex = vars.map((_, i) => examples[i] ?? "");
      return tpl
        ? unwrap(
            api.PATCH("/api/v1/templates/{template_id}", {
              params: { path: { template_id: tpl.id } },
              body: { body, category, examples: ex },
            }),
          )
        : unwrap(
            api.POST("/api/v1/templates", {
              body: { name: name.trim(), language, category, body, examples: ex },
            }),
          );
    },
    onSuccess: () => {
      toast.success(tc("saved"));
      onSaved();
    },
  });
  return (
    <Dialog open onOpenChange={(o) => (o ? null : onClose())}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{tpl ? t("editTitle", { name: tpl.name }) : t("new")}</DialogTitle>
          <DialogDescription>{t("rules")}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            {!tpl ? (
              <Field label={t("name")} htmlFor="tpl-name" hint={t("nameHint")}>
                <Input
                  id="tpl-name"
                  value={name}
                  onChange={(e) =>
                    setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))
                  }
                />
              </Field>
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <Field label={t("language")} htmlFor="tpl-lang">
                <NativeSelect
                  id="tpl-lang"
                  value={language}
                  disabled={!!tpl}
                  onChange={(e) => setLanguage(e.target.value as Lang)}
                >
                  {(["roman_ur", "ur", "en"] as const).map((l) => (
                    <option key={l} value={l}>
                      {t(`lang_${l}`)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label={t("category")} htmlFor="tpl-cat">
                <NativeSelect
                  id="tpl-cat"
                  value={category}
                  onChange={(e) => setCategory(e.target.value as "utility" | "marketing")}
                >
                  <option value="utility">{t("utility")}</option>
                  <option value="marketing">{t("marketing")}</option>
                </NativeSelect>
              </Field>
            </div>
            <Field label={t("body")} htmlFor="tpl-body" hint={t("bodyHint")}>
              <Textarea
                id="tpl-body"
                rows={6}
                value={body}
                dir={rtl ? "rtl" : undefined}
                lang={rtl ? "ur" : undefined}
                onChange={(e) => setBody(e.target.value)}
              />
            </Field>
            {vars.map((v, i) => (
              <Field key={v} label={t("example", { name: v })} htmlFor={`tpl-ex-${v}`}>
                <Input
                  id={`tpl-ex-${v}`}
                  value={examples[i] ?? ""}
                  onChange={(e) => {
                    const next = [...examples];
                    next[i] = e.target.value;
                    setExamples(next);
                  }}
                />
              </Field>
            ))}
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">{t("preview")}</p>
            <div className="rounded-lg bg-[#e5ddd5] p-3 dark:bg-[#0b141a]">
              <div
                className="max-w-[90%] rounded-lg rounded-tl-none bg-white px-3 py-2 text-sm whitespace-pre-wrap text-black shadow-sm dark:bg-[#202c33] dark:text-white"
                dir={rtl ? "rtl" : undefined}
                lang={rtl ? "ur" : undefined}
              >
                {preview(body, vars, examples) || "…"}
              </div>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {tc("cancel")}
          </Button>
          <Button
            onClick={() => save.mutate()}
            disabled={save.isPending || !body.trim() || (!tpl && !name.trim())}
          >
            {tc("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

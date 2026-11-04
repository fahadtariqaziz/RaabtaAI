"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CircleDashed } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader, QueryView } from "@/components/common";
import { DocumentsPanel, FactsPanel } from "@/components/kb";
import { ProfileForm, useInstitution, WhatsAppCard, WidgetForm } from "@/components/settings";
import { Button } from "@/components/ui/button";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { cn } from "@/lib/utils";

const STEPS = ["profile", "documents", "facts", "whatsapp", "widget", "done"] as const;
type Step = (typeof STEPS)[number];

export default function OnboardingPage() {
  const t = useTranslations("onboarding");
  const { institutionId } = useAuth();
  const qc = useQueryClient();
  const inst = useInstitution();
  const ob = useQuery({
    queryKey: ["onboarding", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/institution/onboarding")),
    enabled: !!institutionId,
  });
  const [picked, setPicked] = useState<Step | null>(null);
  const step: Step = picked ?? (ob.data?.current as Step | undefined) ?? "profile";

  const complete = useMutation({
    mutationFn: ({ s, body }: { s: Step; body?: Schemas["OnboardingIn"] }) =>
      unwrap(
        api.POST("/api/v1/institution/onboarding/{step}", {
          params: { path: { step: s } },
          body: body ?? {},
        }),
      ),
    onSuccess: (data, { s }) => {
      qc.setQueryData(["onboarding", institutionId], data);
      void qc.invalidateQueries({ queryKey: ["institution"] });
      void qc.invalidateQueries({ queryKey: ["settings"] });
      setPicked(STEPS[Math.min(STEPS.indexOf(s) + 1, STEPS.length - 1)]);
    },
  });
  const next = (s: Step) => (
    <Button className="mt-6" onClick={() => complete.mutate({ s })} disabled={complete.isPending}>
      {t("continue")}
    </Button>
  );

  return (
    <>
      <PageHeader title={t("title")} />
      <QueryView q={ob}>
        {(o) => (
          <div className="grid gap-6 lg:grid-cols-[14rem_1fr]">
            <ol className="space-y-1" aria-label={t("title")}>
              {STEPS.map((s, i) => {
                const done = o.completed.includes(s);
                return (
                  <li key={s}>
                    <button
                      onClick={() => setPicked(s)}
                      aria-current={step === s ? "step" : undefined}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-start text-sm",
                        step === s ? "bg-muted font-medium" : "hover:bg-muted/60",
                      )}
                    >
                      {done ? (
                        <Check className="size-4 text-emerald-600" aria-label="done" />
                      ) : (
                        <CircleDashed className="text-muted-foreground size-4" aria-hidden />
                      )}
                      {i + 1}. {t(s)}
                    </button>
                  </li>
                );
              })}
            </ol>
            <section aria-label={t(step)}>
              <h2 className="mb-4 text-lg font-semibold">{t(step)}</h2>
              {step === "profile" ? (
                <QueryView q={inst}>
                  {(i) => (
                    <ProfileForm
                      key={i.id}
                      inst={i}
                      submitLabel={t("saveContinue")}
                      onSubmit={(profile) =>
                        complete.mutateAsync({ s: "profile", body: { profile } })
                      }
                    />
                  )}
                </QueryView>
              ) : step === "documents" ? (
                <>
                  <p className="text-muted-foreground mb-4 text-sm">{t("docsHint")}</p>
                  <DocumentsPanel />
                  {next("documents")}
                </>
              ) : step === "facts" ? (
                <>
                  <p className="text-muted-foreground mb-4 text-sm">{t("factsHint")}</p>
                  <FactsPanel />
                  {next("facts")}
                </>
              ) : step === "whatsapp" ? (
                <>
                  <QueryView q={inst}>{(i) => <WhatsAppCard inst={i} />}</QueryView>
                  {next("whatsapp")}
                </>
              ) : step === "widget" ? (
                <WidgetForm
                  submitLabel={t("saveContinue")}
                  onSubmit={(widget) => complete.mutateAsync({ s: "widget", body: { widget } })}
                />
              ) : (
                <Done checklist={o.checklist} />
              )}
            </section>
          </div>
        )}
      </QueryView>
    </>
  );
}

function Done({ checklist }: { checklist: Record<string, unknown> }) {
  const t = useTranslations("onboarding");
  const c = checklist as Record<string, number | boolean>;
  const items: [string, boolean][] = [
    [t("profile"), !!c.profile],
    [`${t("documents")}: ${c.documents_ready}/${c.documents_total}`, Number(c.documents_ready) > 0],
    [
      `${t("facts")}: ${c.facts_approved} ✓ · ${c.facts_pending} pending`,
      Number(c.facts_pending) === 0 && Number(c.facts_approved) > 0,
    ],
    [t("whatsapp"), !!c.whatsapp_connected],
    [`${t("widget")}: ${c.widget_origins} origin(s)`, Number(c.widget_origins) > 0],
  ];
  return (
    <div className="max-w-lg space-y-4">
      <p className="text-xl font-semibold">{t("allSet")} 🎉</p>
      <h3 className="text-sm font-medium">{t("checklist")}</h3>
      <ul className="space-y-2">
        {items.map(([label, ok]) => (
          <li key={label} className="flex items-center gap-2 text-sm">
            {ok ? (
              <Check className="size-4 text-emerald-600" aria-label="done" />
            ) : (
              <CircleDashed className="text-muted-foreground size-4" aria-label="pending" />
            )}
            {label}
          </li>
        ))}
      </ul>
      <Button render={<Link href="/inbox" />}>{t("goInbox")}</Button>
    </div>
  );
}

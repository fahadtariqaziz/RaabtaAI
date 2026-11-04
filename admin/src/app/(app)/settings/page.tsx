"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader, QueryView } from "@/components/common";
import {
  AssistantForm,
  ProfileForm,
  useInstitution,
  WhatsAppCard,
  WidgetForm,
} from "@/components/settings";
import { TeamPanel } from "@/components/team";
import { cn } from "@/lib/utils";

const TABS = ["profile", "assistant", "team", "widget", "whatsapp"] as const;

export default function SettingsPage() {
  const t = useTranslations("settings");
  const [tab, setTab] = useState<(typeof TABS)[number]>("profile");
  const inst = useInstitution();
  return (
    <>
      <PageHeader title={t("title")} />
      <div role="tablist" className="mb-6 flex gap-1 overflow-x-auto border-b">
        {TABS.map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm whitespace-nowrap",
              tab === k ? "border-primary font-medium" : "text-muted-foreground border-transparent",
            )}
          >
            {t(k)}
          </button>
        ))}
      </div>
      {tab === "profile" ? (
        <QueryView q={inst}>{(i) => <ProfileForm key={i.id} inst={i} />}</QueryView>
      ) : tab === "assistant" ? (
        <AssistantForm />
      ) : tab === "team" ? (
        <TeamPanel />
      ) : tab === "widget" ? (
        <WidgetForm />
      ) : (
        <QueryView q={inst}>{(i) => <WhatsAppCard inst={i} />}</QueryView>
      )}
    </>
  );
}

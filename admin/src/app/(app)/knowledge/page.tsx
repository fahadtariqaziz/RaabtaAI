"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/common";
import { DocumentsPanel, FactsPanel, Playground } from "@/components/kb";
import { cn } from "@/lib/utils";

type Tab = "documents" | "facts" | "playground";

export default function KnowledgePage() {
  const t = useTranslations("kb");
  const [tab, setTab] = useState<Tab>("documents");
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("tab");
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deep link from the dashboard
    if (p === "facts" || p === "playground") setTab(p);
  }, []);
  return (
    <>
      <PageHeader title={t("title")} />
      <div role="tablist" className="mb-4 flex gap-1 border-b">
        {(["documents", "facts", "playground"] as const).map((k) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-sm",
              tab === k ? "border-primary font-medium" : "text-muted-foreground border-transparent",
            )}
          >
            {t(k)}
          </button>
        ))}
      </div>
      {tab === "documents" ? <DocumentsPanel /> : tab === "facts" ? <FactsPanel /> : <Playground />}
    </>
  );
}

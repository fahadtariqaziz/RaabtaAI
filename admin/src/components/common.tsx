"use client";

import { AlertTriangle, Inbox as InboxIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import type * as React from "react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({
  title,
  hint,
  icon,
  action,
  className,
}: {
  title?: string;
  hint?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const t = useTranslations("common");
  return (
    <div
      className={cn(
        "text-muted-foreground flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed p-10 text-center",
        className,
      )}
    >
      <div className="bg-muted rounded-full p-3">{icon ?? <InboxIcon className="size-5" />}</div>
      <p className="text-foreground font-medium">{title ?? t("empty")}</p>
      {hint ? <p className="max-w-sm text-sm">{hint}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const t = useTranslations("common");
  return (
    <div
      role="alert"
      className="border-destructive/30 bg-destructive/5 flex flex-col items-center gap-3 rounded-xl border p-8 text-center"
    >
      <AlertTriangle className="text-destructive size-6" aria-hidden />
      <p className="font-medium">{t("error")}</p>
      <p className="text-muted-foreground text-sm">
        {error instanceof Error ? error.message : String(error)}
      </p>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t("retry")}
        </Button>
      ) : null}
    </div>
  );
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

/** Renders loading / error / empty / data for a TanStack query result. */
export function QueryView<T>({
  q,
  empty,
  skeleton,
  children,
}: {
  q: { data: T | undefined; isPending: boolean; error: unknown; refetch: () => unknown };
  empty?: (d: T) => boolean;
  skeleton?: ReactNode;
  children: (d: T) => ReactNode;
}) {
  if (q.isPending) return <>{skeleton ?? <SkeletonRows />}</>;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data as T;
  if (empty?.(d)) return <EmptyState />;
  return <>{children(d)}</>;
}

const TONES = {
  neutral: "bg-muted text-foreground",
  info: "bg-blue-500/10 text-blue-800 dark:text-blue-300",
  good: "bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
  warn: "bg-amber-500/15 text-amber-900 dark:text-amber-300",
  bad: "bg-red-500/10 text-red-800 dark:text-red-300",
} as const;

export function Pill({
  tone = "neutral",
  children,
  className,
}: {
  tone?: keyof typeof TONES;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  );
}

export function NativeSelect({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "border-input bg-background focus-visible:border-ring focus-visible:ring-ring/50 h-8 rounded-lg border px-2 text-sm outline-none focus-visible:ring-3 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

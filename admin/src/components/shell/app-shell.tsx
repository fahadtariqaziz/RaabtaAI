"use client";

import {
  BarChart3,
  BookOpen,
  CalendarDays,
  ClipboardList,
  Gauge,
  Inbox,
  Languages,
  LogOut,
  Menu,
  Moon,
  Rocket,
  Settings,
  ShieldCheck,
  Sun,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useState } from "react";
import { NativeSelect } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { type Role, useAuth, useMe } from "@/lib/auth";
import { useLocale } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type Item = { href: string; key: string; icon: typeof Inbox; min?: Role; super?: boolean };
const DAILY: Item[] = [
  { href: "/", key: "overview", icon: Gauge },
  { href: "/inbox", key: "inbox", icon: Inbox },
  { href: "/leads", key: "leads", icon: Users },
  { href: "/slots", key: "slots", icon: CalendarDays },
];
const MANAGE: Item[] = [
  { href: "/knowledge", key: "knowledge", icon: BookOpen },
  { href: "/onboarding", key: "onboarding", icon: Rocket, min: "admin" },
  { href: "/settings", key: "settings", icon: Settings },
  { href: "/usage", key: "usage", icon: BarChart3, min: "admin" },
  { href: "/audit", key: "audit", icon: ClipboardList, min: "admin" },
  { href: "/superadmin", key: "superadmin", icon: ShieldCheck, super: true },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const t = useTranslations("nav");
  const path = usePathname();
  const { can, isSuperadmin, institution } = useMe();
  const visible = (i: Item) => (i.super ? isSuperadmin : !!institution && (!i.min || can(i.min)));
  const group = (label: string, items: Item[]) => (
    <div className="space-y-1">
      <p className="text-muted-foreground px-3 pt-4 pb-1 text-xs font-medium tracking-wide uppercase">
        {label}
      </p>
      {items.filter(visible).map((i) => {
        const active = i.href === "/" ? path === "/" : path.startsWith(i.href);
        return (
          <Link
            key={i.href}
            href={i.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
              active
                ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60",
            )}
          >
            <i.icon className="size-4" aria-hidden />
            {t(i.key)}
          </Link>
        );
      })}
    </div>
  );
  return (
    <nav aria-label="Main" className="px-2">
      {group(t("daily"), DAILY)}
      {group(t("manage"), MANAGE)}
    </nav>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2 px-5 py-4">
      <div className="bg-primary text-primary-foreground grid size-8 place-items-center rounded-lg font-bold">
        ر
      </div>
      <span className="font-semibold">RaabtaAI</span>
    </div>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const tc = useTranslations("common");
  const { me, institutionId, selectInstitution, logout, impersonation } = useAuth();
  const { locale, setLocale } = useLocale();
  const { resolvedTheme, setTheme } = useTheme();
  const memberships = me?.memberships ?? [];
  return (
    <header className="bg-background/80 sticky top-0 z-20 flex h-14 items-center gap-2 border-b px-3 backdrop-blur md:px-6">
      <Button variant="ghost" size="icon" className="md:hidden" onClick={onMenu} aria-label="Menu">
        <Menu />
      </Button>
      {memberships.length > 1 && !impersonation ? (
        <NativeSelect
          aria-label={tc("institution")}
          value={institutionId ?? ""}
          onChange={(e) => selectInstitution(e.target.value)}
          className="max-w-56"
        >
          {memberships.map((m) => (
            <option key={m.institution_id} value={m.institution_id}>
              {m.institution_name}
            </option>
          ))}
        </NativeSelect>
      ) : (
        <span className="truncate text-sm font-medium">
          {impersonation?.institution_name ?? memberships[0]?.institution_name ?? ""}
        </span>
      )}
      <div className="ms-auto flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setLocale(locale === "en" ? "ur" : "en")}
          aria-label={tc("language")}
        >
          <Languages /> {locale === "en" ? "اردو" : "English"}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
          aria-label={tc("theme")}
        >
          {resolvedTheme === "dark" ? <Sun /> : <Moon />}
        </Button>
        <span className="text-muted-foreground hidden px-2 text-sm lg:inline">{me?.user.name}</span>
        <Button variant="ghost" size="icon" onClick={() => void logout()} aria-label={tc("logout")}>
          <LogOut />
        </Button>
      </div>
    </header>
  );
}

function ImpersonationBanner() {
  const t = useTranslations("super");
  const { impersonation, stopImpersonation } = useAuth();
  if (!impersonation) return null;
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-3 bg-amber-400 px-4 py-1.5 text-sm font-medium text-amber-950"
    >
      <ShieldCheck className="size-4" aria-hidden />
      {t("impersonating", { name: impersonation.institution_name })}
      <Button
        size="xs"
        variant="outline"
        className="bg-white/70"
        onClick={() => void stopImpersonation()}
      >
        {t("stop")}
      </Button>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-dvh flex-col">
      <ImpersonationBanner />
      <div className="flex flex-1">
        <aside className="bg-sidebar sticky top-0 hidden h-dvh w-60 shrink-0 border-e md:block">
          <Brand />
          <NavList />
        </aside>
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent side="left" className="bg-sidebar w-64 p-0">
            <SheetTitle className="sr-only">Menu</SheetTitle>
            <Brand />
            <NavList onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar onMenu={() => setOpen(true)} />
          <main id="main" className="flex-1 p-4 md:p-6">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}

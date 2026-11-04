"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { EmptyState } from "@/components/common";
import { AppShell } from "@/components/shell/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/lib/auth";

/** Client auth gate: nothing tenant-specific renders before the session is known (also keeps
 * the prerendered static shell free of time/user-dependent output under cacheComponents). */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { status, institution, me } = useAuth();
  const router = useRouter();
  const path = usePathname();

  useEffect(() => {
    if (status === "anon") router.replace("/login");
    // platform admins without a membership land on the platform page
    else if (
      status === "authed" &&
      !institution &&
      me?.user.is_superadmin &&
      path !== "/superadmin"
    )
      router.replace("/superadmin");
  }, [status, router, institution, me, path]);

  if (status !== "authed") {
    return (
      <div className="flex min-h-dvh" aria-busy="true">
        <div className="bg-sidebar hidden w-60 border-e md:block" />
        <div className="flex-1 space-y-4 p-6">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }
  return (
    <AppShell>
      {institution || me?.user.is_superadmin ? (
        children
      ) : (
        <EmptyState
          title="No institution"
          hint="Your account is not a member of any institution yet."
        />
      )}
    </AppShell>
  );
}

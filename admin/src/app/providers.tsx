"use client";

import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";
import { toast } from "sonner";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/client";
import { AuthProvider } from "@/lib/auth";
import { LocaleProvider } from "@/lib/i18n";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
          },
          mutations: {
            onError: (e) => toast.error(e instanceof Error ? e.message : String(e)),
          },
        },
        queryCache: new QueryCache({
          onError: (e, q) => {
            if (q.state.data !== undefined) toast.error(e.message); // background refetch failed
          },
        }),
      }),
  );
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <LocaleProvider>
          <AuthProvider>
            <TooltipProvider>{children}</TooltipProvider>
          </AuthProvider>
          <Toaster richColors position="top-center" />
        </LocaleProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

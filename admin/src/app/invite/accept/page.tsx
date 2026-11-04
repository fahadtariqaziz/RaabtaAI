"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Field } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, unwrap } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";

/** Invite link: `/invite/accept#token=…` (the token stays out of server logs). */
export default function AcceptInvitePage() {
  const t = useTranslations("auth");
  const { acceptSession } = useAuth();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read the URL fragment once
    setToken(new URLSearchParams(window.location.hash.slice(1)).get("token"));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const session = await unwrap(
        api.POST("/api/v1/auth/invitations/accept", {
          body: { token, password, name: name || null },
        }),
      );
      acceptSession(session);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="bg-muted/40 grid min-h-dvh place-items-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">
            <h1>{t("acceptTitle")}</h1>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {token === null ? (
            <p className="text-muted-foreground text-sm">{t("noToken")}</p>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <Field label={t("name")} htmlFor="name">
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <Field label={t("password")} htmlFor="pw" hint={t("passwordRules")}>
                <Input
                  id="pw"
                  type="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              {error ? (
                <p role="alert" className="text-destructive text-sm">
                  {error}
                </p>
              ) : null}
              <Button type="submit" className="w-full" disabled={busy || password.length < 8}>
                {t("accept")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}

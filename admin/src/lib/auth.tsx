"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  api,
  refreshAccess,
  setAccessToken,
  setAuthHint,
  setInstitution,
  setOnExpired,
  unwrap,
  type Schemas,
} from "@/lib/api/client";

type Me = Schemas["MeOut"];
type Membership = Schemas["MembershipOut"];
export type Role = "owner" | "admin" | "staff";

export type Impersonation = {
  institution_id: string;
  institution_name: string;
  expires_at: string;
};

type AuthState = {
  status: "loading" | "authed" | "anon";
  me: Me | null;
  institutionId: string | null;
  institution: { id: string; name: string; slug: string; role: Role } | null;
  impersonation: Impersonation | null;
  selectInstitution: (id: string) => void;
  startImpersonation: (imp: Impersonation & { institution_slug: string }) => void;
  stopImpersonation: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  acceptSession: (token: Schemas["TokenOut"]) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);
const INST_KEY = "raabta-institution";
const IMP_KEY = "raabta-impersonation";

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** `useMe` (5.1.2): current user + active institution + role helpers. */
export function useMe() {
  const { me, institution } = useAuth();
  const rank = { staff: 1, admin: 2, owner: 3 } as const;
  return {
    user: me?.user ?? null,
    memberships: me?.memberships ?? [],
    institution,
    can: (min: Role) => !!institution && rank[institution.role] >= rank[min],
    isSuperadmin: !!me?.user.is_superadmin,
  };
}

function pickInstitution(memberships: Membership[]): string | null {
  const saved = localStorage.getItem(INST_KEY);
  if (saved && memberships.some((m) => m.institution_id === saved)) return saved;
  return memberships[0]?.institution_id ?? null;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [status, setStatus] = useState<AuthState["status"]>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [institutionId, setInstitutionId] = useState<string | null>(null);
  const [impersonation, setImpersonation] = useState<
    (Impersonation & { institution_slug: string }) | null
  >(null);

  const apply = useCallback((token: Schemas["TokenOut"]) => {
    setAccessToken(token.access_token);
    setAuthHint(true);
    setMe({ user: token.user, memberships: token.memberships });
    let imp: (Impersonation & { institution_slug: string }) | null = null;
    try {
      imp = JSON.parse(localStorage.getItem(IMP_KEY) ?? "null");
    } catch {
      imp = null;
    }
    if (imp && (!token.user.is_superadmin || Date.parse(imp.expires_at) < Date.now())) {
      localStorage.removeItem(IMP_KEY);
      imp = null;
    }
    setImpersonation(imp);
    const id = imp?.institution_id ?? pickInstitution(token.memberships);
    setInstitution(id);
    setInstitutionId(id);
    setStatus("authed");
  }, []);

  const expire = useCallback(() => {
    setAccessToken(null);
    setAuthHint(false);
    setMe(null);
    setStatus("anon");
    qc.clear();
    router.replace("/login");
  }, [qc, router]);

  useEffect(() => {
    setOnExpired(expire);
    let live = true;
    refreshAccess().then((t) => {
      if (!live) return;
      if (t) apply(t);
      else {
        setAuthHint(false);
        setStatus("anon");
      }
    });
    return () => {
      live = false;
    };
  }, [apply, expire]);

  const value = useMemo<AuthState>(() => {
    const m = me?.memberships.find((x) => x.institution_id === institutionId);
    const institution = m
      ? { id: m.institution_id, name: m.institution_name, slug: m.institution_slug, role: m.role }
      : impersonation && impersonation.institution_id === institutionId
        ? {
            id: impersonation.institution_id,
            name: impersonation.institution_name,
            slug: impersonation.institution_slug,
            role: "owner" as const,
          }
        : null;
    return {
      status,
      me,
      institutionId,
      institution,
      impersonation,
      selectInstitution: (id) => {
        localStorage.setItem(INST_KEY, id);
        setInstitution(id);
        setInstitutionId(id);
        qc.clear();
      },
      startImpersonation: (imp) => {
        localStorage.setItem(IMP_KEY, JSON.stringify(imp));
        setImpersonation(imp);
        setInstitution(imp.institution_id);
        setInstitutionId(imp.institution_id);
        qc.clear();
      },
      stopImpersonation: async () => {
        if (impersonation) {
          await api.DELETE("/api/v1/superadmin/impersonate/{institution_id}", {
            params: { path: { institution_id: impersonation.institution_id } },
          });
        }
        localStorage.removeItem(IMP_KEY);
        setImpersonation(null);
        const id = me ? pickInstitution(me.memberships) : null;
        setInstitution(id);
        setInstitutionId(id);
        qc.clear();
      },
      login: async (email, password) => {
        apply(await unwrap(api.POST("/api/v1/auth/login", { body: { email, password } })));
      },
      acceptSession: apply,
      logout: async () => {
        await api.POST("/api/v1/auth/logout").catch(() => undefined);
        localStorage.removeItem(IMP_KEY);
        expire();
      },
    };
  }, [status, me, institutionId, impersonation, apply, expire, qc]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

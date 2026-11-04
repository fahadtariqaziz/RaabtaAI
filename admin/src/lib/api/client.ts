"use client";

import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];

/** Access token lives in memory only (15 min); the refresh token is an httpOnly cookie. */
let accessToken: string | null = null;
let institutionId: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onExpired: (() => void) | null = null;

const AUTH_HINT = "raabta_auth";

export function setAuthHint(on: boolean): void {
  document.cookie = on
    ? `${AUTH_HINT}=1; path=/; max-age=${30 * 86400}; samesite=strict`
    : `${AUTH_HINT}=; path=/; max-age=0; samesite=strict`;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
export function setInstitution(id: string | null): void {
  institutionId = id;
}
export function getInstitution(): string | null {
  return institutionId;
}
export function setOnExpired(fn: () => void): void {
  onExpired = fn;
}

/** Single-flight refresh (rotating refresh token: two parallel refreshes would trip reuse
 * detection and revoke the family). */
export async function refreshAccess(): Promise<Schemas["TokenOut"] | null> {
  let result: Schemas["TokenOut"] | null = null;
  refreshing ??= (async () => {
    const r = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "same-origin" });
    if (!r.ok) return false;
    result = (await r.json()) as Schemas["TokenOut"];
    accessToken = result.access_token;
    lastToken = result;
    return true;
  })().finally(() => {
    refreshing = null;
  });
  const ok = await refreshing;
  return ok ? (result ?? lastToken) : null;
}
let lastToken: Schemas["TokenOut"] | null = null;

function withAuth(req: Request): Request {
  const headers = new Headers(req.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (institutionId && !headers.has("X-Institution")) headers.set("X-Institution", institutionId);
  return new Request(req, { headers });
}

/** fetch with auth headers; on 401 refresh once and retry, else bounce to login. */
export async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const res = await fetch(withAuth(input));
  if (res.status !== 401 || input.url.includes("/auth/")) return res;
  if (await refreshAccess()) return fetch(withAuth(retry));
  onExpired?.();
  return res;
}

export const api = createClient<paths>({ baseUrl: "", fetch: authFetch });

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function detail(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const d = (error as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d))
      return d
        .map((e: { msg?: string; loc?: unknown[] }) =>
          [e.loc?.slice(1).join("."), e.msg?.replace(/^Value error, /, "")]
            .filter(Boolean)
            .join(": "),
        )
        .join("; ");
  }
  return "Something went wrong";
}

/** Unwrap an openapi-fetch result: data or a thrown ApiError with the API's detail. */
export async function unwrap<T>(
  p: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await p;
  if (error !== undefined || !response.ok) throw new ApiError(response.status, detail(error));
  return data as T;
}

/** Raw authed request for non-JSON bodies (CSV download, multipart upload, SSE). */
export function rawFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return authFetch(new Request(path, { ...init, credentials: "same-origin" }));
}

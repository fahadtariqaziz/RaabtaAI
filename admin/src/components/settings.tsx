"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Field, NativeSelect, Pill, QueryView } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, unwrap, type Schemas } from "@/lib/api/client";
import { useAuth, useMe } from "@/lib/auth";

type Inst = Schemas["InstitutionOut"];
type Lang = "en" | "ur" | "roman_ur";
const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "ur", label: "اردو" },
  { id: "roman_ur", label: "Roman Urdu" },
];
const TIMEZONES = ["Asia/Karachi", "Asia/Dubai", "Asia/Riyadh", "Europe/London"];

export function useInstitution() {
  const { institutionId } = useAuth();
  return useQuery({
    queryKey: ["institution", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/institution")),
    enabled: !!institutionId,
  });
}

export function useSettings() {
  const { institutionId } = useAuth();
  return useQuery({
    queryKey: ["settings", institutionId],
    queryFn: () => unwrap(api.GET("/api/v1/institution/settings")),
    enabled: !!institutionId,
  });
}

export type ProfileValues = Schemas["InstitutionPatch"];

/** Profile form; `onSubmit` lets the onboarding wizard save + advance in one call. */
export function ProfileForm({
  inst,
  submitLabel,
  onSubmit,
}: {
  inst: Inst;
  submitLabel?: string;
  onSubmit?: (v: ProfileValues) => Promise<unknown>;
}) {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const { can } = useMe();
  const [v, setV] = useState({
    name: inst.name,
    type: inst.type as "school" | "college" | "university",
    city: inst.city,
    timezone: inst.timezone,
    languages: inst.languages as Lang[],
    start: String(inst.quiet_hours.start ?? "21:00"),
    end: String(inst.quiet_hours.end ?? "09:00"),
  });
  const save = useMutation({
    mutationFn: async () => {
      const body: ProfileValues = {
        name: v.name,
        type: v.type,
        city: v.city,
        timezone: v.timezone,
        languages: v.languages,
        quiet_hours: { start: v.start, end: v.end },
      };
      return onSubmit ? onSubmit(body) : unwrap(api.PATCH("/api/v1/institution", { body }));
    },
    onSuccess: () => {
      toast.success(tc("saved"));
      void qc.invalidateQueries({ queryKey: ["institution"] });
      void qc.invalidateQueries({ queryKey: ["onboarding"] });
    },
  });
  const disabled = !can("admin");
  return (
    <form
      className="grid max-w-2xl gap-4 sm:grid-cols-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <Field label={t("name")} htmlFor="p-name">
        <Input
          id="p-name"
          disabled={disabled}
          value={v.name}
          onChange={(e) => setV({ ...v, name: e.target.value })}
        />
      </Field>
      <Field label={t("type")} htmlFor="p-type">
        <NativeSelect
          id="p-type"
          className="w-full"
          disabled={disabled}
          value={v.type}
          onChange={(e) => setV({ ...v, type: e.target.value as typeof v.type })}
        >
          <option value="school">School</option>
          <option value="college">College</option>
          <option value="university">University</option>
        </NativeSelect>
      </Field>
      <Field label={t("city")} htmlFor="p-city">
        <Input
          id="p-city"
          disabled={disabled}
          value={v.city}
          onChange={(e) => setV({ ...v, city: e.target.value })}
        />
      </Field>
      <Field label={t("timezone")} htmlFor="p-tz">
        <NativeSelect
          id="p-tz"
          className="w-full"
          disabled={disabled}
          value={v.timezone}
          onChange={(e) => setV({ ...v, timezone: e.target.value })}
        >
          {Array.from(new Set([v.timezone, ...TIMEZONES])).map((z) => (
            <option key={z}>{z}</option>
          ))}
        </NativeSelect>
      </Field>
      <fieldset className="sm:col-span-2">
        <legend className="mb-1.5 text-sm font-medium">{t("languages")}</legend>
        <div className="flex flex-wrap gap-3">
          {LANGS.map((l) => (
            <label key={l.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                disabled={disabled}
                checked={v.languages.includes(l.id)}
                onChange={(e) =>
                  setV({
                    ...v,
                    languages: e.target.checked
                      ? [...v.languages, l.id]
                      : v.languages.filter((x) => x !== l.id),
                  })
                }
              />
              {l.label}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="sm:col-span-2">
        <legend className="mb-1.5 text-sm font-medium">{t("quietHours")}</legend>
        <div className="flex items-center gap-2">
          <Input
            aria-label="Start"
            type="time"
            className="w-32"
            disabled={disabled}
            value={v.start}
            onChange={(e) => setV({ ...v, start: e.target.value })}
          />
          –
          <Input
            aria-label="End"
            type="time"
            className="w-32"
            disabled={disabled}
            value={v.end}
            onChange={(e) => setV({ ...v, end: e.target.value })}
          />
        </div>
      </fieldset>
      {!disabled ? (
        <div className="sm:col-span-2">
          <Button type="submit" disabled={save.isPending || v.languages.length === 0}>
            {submitLabel ?? tc("save")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}

export type WidgetValues = Schemas["WidgetSettings"];

export function WidgetForm({
  submitLabel,
  onSubmit,
}: {
  submitLabel?: string;
  onSubmit?: (v: WidgetValues) => Promise<unknown>;
}) {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const { can } = useMe();
  const { institution } = useAuth();
  const settings = useSettings();
  return (
    <QueryView q={settings}>
      {(s) => (
        <WidgetFormInner
          key={JSON.stringify(s.widget)}
          s={s}
          slug={institution?.slug ?? ""}
          disabled={!can("admin")}
          submitLabel={submitLabel ?? tc("save")}
          labels={{ t, tc }}
          onSave={async (body) => {
            if (onSubmit) await onSubmit(body);
            else
              await unwrap(api.PATCH("/api/v1/institution/settings", { body: { widget: body } }));
            toast.success(tc("saved"));
            void qc.invalidateQueries({ queryKey: ["settings"] });
            void qc.invalidateQueries({ queryKey: ["onboarding"] });
          }}
        />
      )}
    </QueryView>
  );
}

function WidgetFormInner({
  s,
  slug,
  disabled,
  submitLabel,
  labels: { t, tc },
  onSave,
}: {
  s: Schemas["SettingsOut"];
  slug: string;
  disabled: boolean;
  submitLabel: string;
  labels: { t: ReturnType<typeof useTranslations>; tc: ReturnType<typeof useTranslations> };
  onSave: (b: WidgetValues) => Promise<void>;
}) {
  const w = s.widget as Record<string, unknown>;
  const [color, setColor] = useState(String(w.primary_color ?? "#0f766e"));
  const [position, setPosition] = useState<"left" | "right">(
    w.position === "left" ? "left" : "right",
  );
  const [origins, setOrigins] = useState(((w.allowed_origins as string[]) ?? []).join("\n"));
  const [wa, setWa] = useState(String(w.whatsapp_number ?? ""));
  const [busy, setBusy] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);
  const preview = `/widget-preview.html?${new URLSearchParams({ slug, primary: color, position })}`;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await onSave({
        primary_color: color,
        position,
        allowed_origins: origins
          .split(/\s+/)
          .map((o) => o.trim())
          .filter(Boolean),
        whatsapp_number: wa.trim() || null,
      });
      setPreviewKey((k) => k + 1);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form className="space-y-4" onSubmit={submit}>
        <div className="grid grid-cols-2 gap-4">
          <Field label={t("primaryColor")} htmlFor="w-color">
            <div className="flex gap-2">
              <input
                id="w-color"
                type="color"
                disabled={disabled}
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="h-8 w-12 rounded border"
              />
              <Input
                aria-label={t("primaryColor")}
                disabled={disabled}
                value={color}
                onChange={(e) => setColor(e.target.value)}
              />
            </div>
          </Field>
          <Field label={t("position")} htmlFor="w-pos">
            <NativeSelect
              id="w-pos"
              className="w-full"
              disabled={disabled}
              value={position}
              onChange={(e) => setPosition(e.target.value as "left" | "right")}
            >
              <option value="right">Right</option>
              <option value="left">Left</option>
            </NativeSelect>
          </Field>
        </div>
        <Field label={t("origins")} htmlFor="w-origins" hint={t("originsHint")}>
          <Textarea
            id="w-origins"
            rows={3}
            disabled={disabled}
            value={origins}
            onChange={(e) => setOrigins(e.target.value)}
          />
        </Field>
        <Field label={t("waNumber")} htmlFor="w-wa" hint="923001234567">
          <Input
            id="w-wa"
            inputMode="tel"
            disabled={disabled}
            value={wa}
            onChange={(e) => setWa(e.target.value)}
          />
        </Field>
        <Field label={t("snippet")} htmlFor="w-snippet">
          <div className="relative">
            <pre id="w-snippet" className="bg-muted overflow-x-auto rounded-lg p-3 pe-12 text-xs">
              {s.snippet}
            </pre>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              className="absolute end-1 top-1"
              aria-label={tc("copy")}
              onClick={() =>
                navigator.clipboard.writeText(s.snippet).then(() => toast.success(tc("copied")))
              }
            >
              <Copy />
            </Button>
          </div>
        </Field>
        <p className="text-muted-foreground text-xs">
          WordPress: Appearance → Theme File Editor → footer.php, or a “header & footer scripts”
          plugin. Wix: Settings → Custom code → Body end.
        </p>
        {!disabled ? (
          <Button type="submit" disabled={busy}>
            {submitLabel}
          </Button>
        ) : null}
      </form>
      <div>
        <p className="mb-2 text-sm font-medium">{t("preview")}</p>
        <iframe
          key={previewKey + color + position}
          title={t("preview")}
          src={preview}
          className="h-[520px] w-full rounded-xl border bg-white"
        />
      </div>
    </div>
  );
}

export function AssistantForm() {
  const t = useTranslations("settings");
  const tc = useTranslations("common");
  const qc = useQueryClient();
  const { can } = useMe();
  const settings = useSettings();
  return (
    <QueryView q={settings}>
      {(s) => (
        <AssistantInner
          key={JSON.stringify([s.details, s.escalation])}
          s={s}
          disabled={!can("admin")}
          t={t}
          tc={tc}
          qc={qc}
        />
      )}
    </QueryView>
  );
}

function AssistantInner({
  s,
  disabled,
  t,
  tc,
  qc,
}: {
  s: Schemas["SettingsOut"];
  disabled: boolean;
  t: ReturnType<typeof useTranslations>;
  tc: ReturnType<typeof useTranslations>;
  qc: ReturnType<typeof useQueryClient>;
}) {
  const [rows, setRows] = useState<[string, string][]>(Object.entries(s.details));
  const esc = s.escalation as { keywords?: string[]; max_ai_turns?: number | null };
  const [keywords, setKeywords] = useState((esc.keywords ?? []).join(", "));
  const save = useMutation({
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/institution/settings", {
          body: {
            details: Object.fromEntries(
              rows.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), v]),
            ),
            escalation: {
              keywords: keywords
                .split(",")
                .map((k) => k.trim())
                .filter(Boolean),
              max_ai_turns: esc.max_ai_turns ?? null,
            },
          },
        }),
      ),
    onSuccess: () => {
      toast.success(tc("saved"));
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
  return (
    <form
      className="max-w-2xl space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("details")}</legend>
        <p className="text-muted-foreground text-xs">{t("detailsHint")}</p>
        {rows.map(([k, v], i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label="Key"
              className="w-44 font-mono text-xs"
              disabled={disabled}
              value={k}
              onChange={(e) => setRows(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))}
            />
            <Input
              aria-label={k || "Value"}
              disabled={disabled}
              value={v}
              onChange={(e) => setRows(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))}
            />
            {!disabled ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={tc("delete")}
                onClick={() => setRows(rows.filter((_, j) => j !== i))}
              >
                <Trash2 />
              </Button>
            ) : null}
          </div>
        ))}
        {!disabled ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setRows([...rows, ["", ""]])}
          >
            <Plus /> {t("addDetail")}
          </Button>
        ) : null}
      </fieldset>
      <Field label={t("escalation")} htmlFor="kw" hint={t("keywordsHint")}>
        <Input
          id="kw"
          disabled={disabled}
          value={keywords}
          onChange={(e) => setKeywords(e.target.value)}
        />
      </Field>
      {!disabled ? (
        <Button type="submit" disabled={save.isPending}>
          {tc("save")}
        </Button>
      ) : null}
    </form>
  );
}

export function WhatsAppCard({ inst }: { inst: Inst }) {
  const t = useTranslations("settings");
  return (
    <div className="max-w-xl space-y-2 rounded-xl border p-5">
      <div className="flex items-center gap-2">
        <h3 className="font-medium">{t("whatsapp")}</h3>
        {inst.wa_phone_number_id ? (
          <Pill tone="good">{t("waConnected")}</Pill>
        ) : (
          <Pill tone="warn">{t("waPending")}</Pill>
        )}
      </div>
      {inst.wa_phone_number_id ? (
        <p className="text-muted-foreground text-sm">Phone number id: {inst.wa_phone_number_id}</p>
      ) : null}
      <p className="text-muted-foreground text-sm">{t("waHint")}</p>
    </div>
  );
}

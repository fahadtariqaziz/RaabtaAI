"use client";

import { NextIntlClientProvider } from "next-intl";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import en from "@/messages/en.json";
import ur from "@/messages/ur.json";

export type Locale = "en" | "ur";
const MESSAGES = { en, ur } as const;
const KEY = "raabta-locale";

const LocaleContext = createContext<{ locale: Locale; setLocale: (l: Locale) => void }>({
  locale: "en",
  setLocale: () => {},
});

export function useLocale() {
  return useContext(LocaleContext);
}

/** Client-side locale (no i18n routing): EN/UR with `<html dir>` mirroring for RTL. */
export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setState] = useState<Locale>("en");

  useEffect(() => {
    const saved = localStorage.getItem(KEY);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate from storage once
    if (saved === "ur" || saved === "en") setState(saved);
  }, []);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = locale === "ur" ? "rtl" : "ltr";
  }, [locale]);

  const setLocale = useCallback((l: Locale) => {
    localStorage.setItem(KEY, l);
    setState(l);
  }, []);

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]} timeZone="Asia/Karachi">
        {children}
      </NextIntlClientProvider>
    </LocaleContext.Provider>
  );
}

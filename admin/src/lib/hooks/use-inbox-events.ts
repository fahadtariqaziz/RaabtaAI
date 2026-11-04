"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { rawFetch } from "@/lib/api/client";

/** Live inbox (5.4.1): reads `GET /conversations/events` (fetch-SSE, so the bearer header
 * works) and invalidates the affected queries. Reconnects with backoff; queries also poll
 * slowly as a fallback when a proxy buffers the stream. */
export function useInboxEvents(institutionId: string | null): boolean {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!institutionId) return;
    const ctrl = new AbortController();
    let delay = 1000;

    async function loop() {
      while (!ctrl.signal.aborted) {
        try {
          const r = await rawFetch("/api/v1/conversations/events", {
            signal: ctrl.signal,
            headers: { Accept: "text/event-stream" },
          });
          if (!r.ok || !r.body) throw new Error(String(r.status));
          setLive(true);
          delay = 1000;
          const reader = r.body.getReader();
          const dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            let i: number;
            while ((i = buf.indexOf("\n\n")) >= 0) {
              const block = buf.slice(0, i);
              buf = buf.slice(i + 2);
              const ev = /^event: (.*)$/m.exec(block)?.[1];
              const data = /^data: (.*)$/m.exec(block)?.[1];
              if (ev === "changed" && data) {
                const ids = (JSON.parse(data) as { ids: string[] }).ids;
                void qc.invalidateQueries({ queryKey: ["conversations"] });
                for (const id of ids) {
                  void qc.invalidateQueries({ queryKey: ["conversation", id] });
                  void qc.invalidateQueries({ queryKey: ["messages", id] });
                }
                void qc.invalidateQueries({ queryKey: ["metrics"] });
              }
            }
          }
        } catch {
          if (ctrl.signal.aborted) return;
        }
        setLive(false);
        await new Promise((res) => setTimeout(res, delay));
        delay = Math.min(delay * 2, 30_000);
      }
    }
    void loop();
    return () => ctrl.abort();
  }, [institutionId, qc]);

  return live;
}

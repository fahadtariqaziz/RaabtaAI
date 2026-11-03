/** Incremental `text/event-stream` parser (EventSource can't POST, so we read fetch bodies). */
export interface SseEvent {
  event: string;
  data: string;
}

export class SseParser {
  private buf = "";

  /** Feed a decoded chunk; returns every event completed by it. */
  push(chunk: string): SseEvent[] {
    this.buf += chunk.replace(/\r\n?/g, "\n");
    const out: SseEvent[] = [];
    let idx: number;
    while ((idx = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, idx);
      this.buf = this.buf.slice(idx + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length) out.push({ event, data: data.join("\n") });
    }
    return out;
  }
}

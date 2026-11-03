/** Safe minimal markdown → DOM (no innerHTML on model text): paragraphs, `-`/`1.` lists,
 * **bold**, and simple pipe tables. Everything else is plain text. */

function inline(parent: HTMLElement, text: string): void {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  for (const p of parts) {
    if (!p) continue;
    if (p.startsWith("**") && p.endsWith("**") && p.length > 4) {
      const b = document.createElement("strong");
      b.textContent = p.slice(2, -2);
      parent.appendChild(b);
    } else {
      parent.appendChild(document.createTextNode(p));
    }
  }
}

function table(lines: string[]): HTMLElement {
  const tbl = document.createElement("table");
  const rows = lines.filter((l) => !/^\s*\|?\s*:?-{2,}/.test(l));
  rows.forEach((line, i) => {
    const tr = document.createElement("tr");
    const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|");
    for (const c of cells) {
      const cell = document.createElement(i === 0 ? "th" : "td");
      inline(cell, c.trim());
      tr.appendChild(cell);
    }
    tbl.appendChild(tr);
  });
  return tbl;
}

export function renderMarkdown(text: string): DocumentFragment {
  const frag = document.createDocumentFragment();
  const blocks = text.split(/\n{2,}/);
  for (const block of blocks) {
    const lines = block.split("\n").filter((l) => l.trim() !== "");
    if (!lines.length) continue;
    if (lines.every((l) => l.trim().startsWith("|"))) {
      frag.appendChild(table(lines));
      continue;
    }
    if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
      const ordered = /^\s*\d/.test(lines[0] ?? "");
      const list = document.createElement(ordered ? "ol" : "ul");
      for (const l of lines) {
        const li = document.createElement("li");
        inline(li, l.replace(/^\s*([-*•]|\d+[.)])\s+/, "").replace(/^#+\s*/, ""));
        list.appendChild(li);
      }
      frag.appendChild(list);
      continue;
    }
    const p = document.createElement("p");
    lines.forEach((l, i) => {
      if (i) p.appendChild(document.createElement("br"));
      inline(p, l.replace(/^#+\s*/, ""));
    });
    frag.appendChild(p);
  }
  return frag;
}

/** Progressive reveal of an already-approved reply (purely cosmetic; text is final). */
export function reveal(el: HTMLElement, text: string, done: () => void): void {
  const words = text.split(/(\s+)/);
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  if (reduce || words.length < 8) {
    el.replaceChildren(renderMarkdown(text));
    done();
    return;
  }
  let i = 0;
  const step = Math.max(2, Math.ceil(words.length / 40));
  const tick = (): void => {
    i = Math.min(words.length, i + step);
    el.replaceChildren(renderMarkdown(words.slice(0, i).join("")));
    if (i < words.length) setTimeout(tick, 24);
    else done();
  };
  tick();
}

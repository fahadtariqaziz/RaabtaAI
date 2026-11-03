/** All widget CSS lives inside the shadow root. Theme via CSS vars set from /widget/config. */
export const CSS = `
:host{all:initial}
*{box-sizing:border-box}
.root{--p:#0f766e;--fg:#0f172a;--mut:#64748b;--bg:#fff;--bub:#f1f5f9;--bd:#e2e8f0;
font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--fg);
position:fixed;bottom:20px;right:20px;z-index:2147483000}
.root.left{right:auto;left:20px}
.rtl{direction:rtl;font-family:"Noto Nastaliq Urdu",system-ui,sans-serif;line-height:2.1}
button{font:inherit;cursor:pointer}
.launcher{width:56px;height:56px;border-radius:50%;border:0;background:var(--p);color:#fff;
box-shadow:0 6px 20px rgba(0,0,0,.2);display:grid;place-items:center}
.launcher svg{width:26px;height:26px}
.launcher:focus-visible,.panel button:focus-visible,.panel input:focus-visible,.panel textarea:focus-visible{outline:2px solid var(--p);outline-offset:2px}
.panel{position:absolute;bottom:72px;right:0;width:370px;height:min(600px,calc(100vh - 110px));
background:var(--bg);border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.22);display:flex;
flex-direction:column;overflow:hidden;border:1px solid var(--bd)}
.left .panel{right:auto;left:0}
.hidden{display:none!important}
.head{background:var(--p);color:#fff;padding:12px 14px;display:flex;align-items:center;gap:8px}
.head .t{flex:1;min-width:0}
.head .n{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.head .s{font-size:12px;opacity:.85}
.langs{display:flex;gap:2px;background:rgba(255,255,255,.18);border-radius:8px;padding:2px}
.langs button{border:0;background:none;color:#fff;padding:2px 7px;border-radius:6px;font-size:12px}
.langs button[aria-pressed=true]{background:#fff;color:var(--p)}
.x{border:0;background:none;color:#fff;font-size:22px;line-height:1;padding:0 4px}
.log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
.m{max-width:85%;padding:9px 12px;border-radius:14px;background:var(--bub);word-wrap:break-word}
.m p{margin:0 0 6px}.m p:last-child{margin:0}
.m ul,.m ol{margin:0 0 6px;padding-inline-start:18px}
.m table{border-collapse:collapse;margin:4px 0;font-size:13px}
.m th,.m td{border:1px solid var(--bd);padding:3px 6px;text-align:start}
.m.me{align-self:flex-end;background:var(--p);color:#fff;border-end-end-radius:4px}
.m.ai{align-self:flex-start;border-end-start-radius:4px}
.cites{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.chip{border:1px solid var(--bd);background:#fff;border-radius:999px;padding:2px 9px;font-size:12px;color:var(--mut)}
.quote{font-size:12px;color:var(--mut);border-inline-start:3px solid var(--bd);padding-inline-start:8px;margin-top:4px}
.status{color:var(--mut);font-size:13px;display:flex;align-items:center;gap:8px}
.dots span{display:inline-block;width:6px;height:6px;margin:0 1px;border-radius:50%;background:var(--mut);animation:b 1.2s infinite}
.dots span:nth-child(2){animation-delay:.15s}.dots span:nth-child(3){animation-delay:.3s}
@keyframes b{0%,80%,100%{opacity:.3}40%{opacity:1}}
.qr{display:flex;flex-wrap:wrap;gap:6px}
.qr button,.slot{border:1px solid var(--p);color:var(--p);background:#fff;border-radius:999px;padding:5px 11px;font-size:13px}
.qr button:hover,.slot:hover{background:var(--p);color:#fff}
.card{border:1px solid var(--bd);border-radius:12px;padding:10px;display:flex;flex-direction:column;gap:8px}
.card h4{margin:0;font-size:13px;font-weight:600}
.slots{display:flex;flex-wrap:wrap;gap:6px}
.card input{border:1px solid var(--bd);border-radius:8px;padding:7px 9px;font:inherit;width:100%}
.card .err{color:#b91c1c;font-size:12px}
.primary{border:0;background:var(--p);color:#fff;border-radius:8px;padding:8px}
.foot{border-top:1px solid var(--bd);padding:8px;display:flex;gap:6px;align-items:flex-end}
.foot textarea{flex:1;resize:none;border:1px solid var(--bd);border-radius:10px;padding:8px 10px;font:inherit;max-height:96px;min-height:38px}
.foot .send{border:0;background:var(--p);color:#fff;border-radius:10px;padding:8px 12px}
.foot .send:disabled{opacity:.5;cursor:default}
.wa{border:0;border-top:1px solid var(--bd);background:#f0fdf4;color:#15803d;padding:7px;font-size:13px}
.pw{font-size:11px;color:var(--mut);text-align:center;padding:0 0 6px}
@media (max-width:480px){.root{bottom:14px;right:14px}.root.left{left:14px}
.panel{position:fixed;inset:0;width:100%;height:100%;border-radius:0;border:0}}
`;

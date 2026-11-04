"""STT bake-off (step 6.4.3, D-02): transcribe real WhatsApp voice notes with each provider and
report WER / CER per language, confidence calibration and latency.
Writes `evals/reports/stt-bakeoff-<stamp>.md`.

    uv run python -m scripts.bakeoff_stt --dir ~/raabta-voice-samples [--providers openai,fake]

Sample layout (user-provided, never committed — parents' voices are PII):
    <dir>/<name>.ogg          the voice note (ogg/opus as WhatsApp sends it; mp3/m4a also work)
    <dir>/<name>.txt          the reference transcript (what was actually said)
    <dir>/<name>.lang         optional: ur | roman_ur | en (default: detected from the .txt)
Aim for 20 notes: ~8 Urdu, ~8 Roman-Urdu speakers, ~4 English/mixed, noisy + quiet.

Spends money for `openai` (gpt-4o-transcribe ≈ $0.006/min → cents for 20 notes).
"""

import argparse
import asyncio
import datetime as dt
import re
import statistics
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.channels.stt import LOW_CONFIDENCE, SpeechToTextProvider
from app.channels.stt.fake import FakeSTT
from app.channels.stt.openai import OpenAISTT
from app.core.config import get_settings
from app.kb.text import detect_lang

REPORTS = Path(__file__).resolve().parents[1] / "evals" / "reports"
AUDIO = {".ogg": "audio/ogg", ".opus": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4"}


def _norm(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text.lower())
    text = re.sub(r"[^\w\s؀-ۿ]", " ", text)
    return text.split()


def _edits(a: list[str], b: list[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r = _norm(ref)
    return _edits(r, _norm(hyp)) / max(1, len(r))


def cer(ref: str, hyp: str) -> float:
    r = list("".join(_norm(ref)))
    return _edits(r, list("".join(_norm(hyp)))) / max(1, len(r))


@dataclass
class Row:
    name: str
    lang: str
    provider: str
    wer: float
    cer: float
    confidence: float
    seconds: float
    text: str


def samples(folder: Path) -> list[tuple[Path, str, str]]:
    out = []
    for audio in sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO):
        ref = audio.with_suffix(".txt")
        if not ref.exists():
            print(f"skip {audio.name}: no {ref.name}", file=sys.stderr)
            continue
        text = ref.read_text(encoding="utf-8").strip()
        lang_file = audio.with_suffix(".lang")
        lang = lang_file.read_text().strip() if lang_file.exists() else detect_lang(text)
        out.append((audio, text, lang))
    return out


def make(name: str) -> SpeechToTextProvider:
    if name == "fake":
        return FakeSTT()
    if name == "openai":
        return OpenAISTT(get_settings().require("stt_api_key"))
    raise SystemExit(f"unknown provider {name!r}")


async def run(folder: Path, providers: list[str]) -> list[Row]:
    rows: list[Row] = []
    items = samples(folder)
    if not items:
        raise SystemExit(f"no <name>.ogg + <name>.txt pairs in {folder}")
    for pname in providers:
        stt = make(pname)
        for audio, ref, lang in items:
            started = time.perf_counter()
            tr = await stt.transcribe(audio.read_bytes(), AUDIO[audio.suffix.lower()])
            rows.append(
                Row(
                    audio.stem,
                    lang,
                    f"{pname}/{tr.model or pname}",
                    wer(ref, tr.text),
                    cer(ref, tr.text),
                    tr.confidence,
                    time.perf_counter() - started,
                    tr.text,
                )
            )
            print(f"{pname:7} {audio.stem:20} WER {rows[-1].wer:.2f} conf {tr.confidence:.2f}")
    return rows


def report(rows: list[Row]) -> str:
    lines = [
        f"# STT bake-off {dt.datetime.now():%Y-%m-%d %H:%M}",
        "",
        "| provider | lang | n | WER | CER | mean conf | ask-to-type rate | p50 s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple[str, str], list[Row]] = {}
    for r in rows:
        groups.setdefault((r.provider, r.lang), []).append(r)
        groups.setdefault((r.provider, "all"), []).append(r)
    for (prov, lang), rs in sorted(groups.items()):
        low = sum(r.confidence < LOW_CONFIDENCE for r in rs) / len(rs)
        lines.append(
            f"| {prov} | {lang} | {len(rs)} | {statistics.mean(r.wer for r in rs):.2f} | "
            f"{statistics.mean(r.cer for r in rs):.2f} | "
            f"{statistics.mean(r.confidence for r in rs):.2f} | {low:.0%} | "
            f"{statistics.median(r.seconds for r in rs):.1f} |"
        )
    lines += [
        "",
        f"Calibration (threshold {LOW_CONFIDENCE}): a good threshold puts most WER > 0.4 notes "
        "below it and most WER < 0.2 notes above it.",
        "",
        "| provider | note | lang | WER | conf | transcript |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.provider} | {r.name} | {r.lang} | {r.wer:.2f} | {r.confidence:.2f} | "
        f"{r.text[:80].replace('|', '/')} |"
        for r in rows
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--providers", default="openai")
    args = ap.parse_args()
    rows = asyncio.run(run(args.dir.expanduser(), args.providers.split(",")))
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"stt-bakeoff-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    out.write_text(report(rows), encoding="utf-8")
    print(f"report → {out}")


if __name__ == "__main__":
    main()

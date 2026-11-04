"""OpenAI transcription (`gpt-4o-transcribe`, fallback `whisper-1`) over plain httpx.

Confidence: `gpt-4o-transcribe` returns token logprobs (`include[]=logprobs`) → mean token
probability; `whisper-1` (verbose_json) → mean exp(avg_logprob) over segments, discounted by
`no_speech_prob`. Both are estimates; the bake-off (step 6.4.3) calibrates the 0.6 threshold."""

import math
from typing import Any

import httpx

from app.channels.stt.base import SpeechToTextError, Transcript

URL = "https://api.openai.com/v1/audio/transcriptions"
PRIMARY = "gpt-4o-transcribe"
FALLBACK = "whisper-1"
# WhatsApp voice notes are ogg/opus; the API infers the format from the filename.
EXT = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "m4a"}
PROMPT = (
    "Pakistani parent asking a school about admissions or fees, in Urdu, Roman Urdu or English. "
    "Terms: admission, fee, challan, voucher, campus visit, matric, FSc, O level, semester."
)


def _logprob_confidence(data: dict[str, Any]) -> float:
    lps = [lp.get("logprob") for lp in data.get("logprobs") or [] if isinstance(lp, dict)]
    vals = [math.exp(v) for v in lps if isinstance(v, int | float)]
    return sum(vals) / len(vals) if vals else 0.75  # no logprobs → neutral-ish default


def _segment_confidence(data: dict[str, Any]) -> float:
    segs = [s for s in data.get("segments") or [] if isinstance(s, dict)]
    if not segs:
        return 0.75
    vals = [
        math.exp(float(s.get("avg_logprob", -1.0))) * (1 - float(s.get("no_speech_prob", 0.0)))
        for s in segs
    ]
    return sum(vals) / len(vals)


class OpenAISTT:
    name = "openai"

    def __init__(self, api_key: str, *, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60.0, connect=5.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(
        self, model: str, audio: bytes, mime_type: str, language_hint: str | None
    ) -> Transcript:
        base_mime = mime_type.split(";")[0].strip()
        files = {"file": (f"voice.{EXT.get(base_mime, 'ogg')}", audio, base_mime)}
        form: dict[str, Any] = {"model": model, "prompt": PROMPT}
        if model == PRIMARY:
            form |= {"response_format": "json", "include[]": "logprobs"}
        else:
            form |= {"response_format": "verbose_json"}
        if language_hint == "ur":  # Roman Urdu / English: let the model detect
            form["language"] = "ur"
        resp = await self._http.post(URL, data=form, files=files)
        if not resp.is_success:
            raise SpeechToTextError(f"{model} HTTP {resp.status_code}")
        data = resp.json()
        text = str(data.get("text") or "").strip()
        conf = _logprob_confidence(data) if model == PRIMARY else _segment_confidence(data)
        return Transcript(
            text=text,
            confidence=round(conf if text else 0.0, 3),
            language=data.get("language"),
            provider=self.name,
            model=model,
        )

    async def transcribe(
        self, audio: bytes, mime_type: str, language_hint: str | None = None
    ) -> Transcript:
        try:
            return await self._call(PRIMARY, audio, mime_type, language_hint)
        except (SpeechToTextError, httpx.TransportError):
            try:
                return await self._call(FALLBACK, audio, mime_type, language_hint)
            except httpx.TransportError as exc:
                raise SpeechToTextError(f"transport error: {type(exc).__name__}") from exc

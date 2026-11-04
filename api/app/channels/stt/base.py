from dataclasses import dataclass
from typing import Protocol

LOW_CONFIDENCE = 0.6  # PLAN §15.2: below this → ask the parent to type instead


class SpeechToTextError(RuntimeError):
    pass


@dataclass(frozen=True)
class Transcript:
    text: str
    confidence: float  # 0..1 (provider-specific estimate)
    language: str | None = None
    provider: str = ""
    model: str = ""


class SpeechToTextProvider(Protocol):
    name: str

    async def transcribe(
        self, audio: bytes, mime_type: str, language_hint: str | None = None
    ) -> Transcript: ...

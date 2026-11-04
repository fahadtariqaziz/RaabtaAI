"""Deterministic STT for tests/dev (no spend). Returns the queued transcripts in order, else a
fixed Roman-Urdu line."""

from app.channels.stt.base import Transcript


class FakeSTT:
    name = "fake"

    def __init__(self, results: list[Transcript] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[int, str]] = []

    async def transcribe(
        self, audio: bytes, mime_type: str, language_hint: str | None = None
    ) -> Transcript:
        self.calls.append((len(audio), mime_type))
        if self.results:
            return self.results.pop(0)
        return Transcript(
            text="Class 3 ki fee kitni hai?", confidence=0.9, language="roman_ur", provider="fake"
        )

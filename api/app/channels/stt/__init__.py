"""Speech-to-text behind one interface (step 6.4.2, PLAN §4 STT, D-02 pending bake-off)."""

from app.channels.stt.base import (
    LOW_CONFIDENCE,
    SpeechToTextError,
    SpeechToTextProvider,
    Transcript,
)
from app.channels.stt.factory import make_stt

__all__ = [
    "LOW_CONFIDENCE",
    "SpeechToTextError",
    "SpeechToTextProvider",
    "Transcript",
    "make_stt",
]

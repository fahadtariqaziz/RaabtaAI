from app.channels.stt.base import SpeechToTextProvider
from app.core.config import Settings


def make_stt(settings: Settings) -> SpeechToTextProvider:
    """STT_PROVIDER=fake (tests/dev, no spend) | openai (needs STT_API_KEY)."""
    if settings.stt_provider == "fake":
        from app.channels.stt.fake import FakeSTT

        return FakeSTT()
    if settings.stt_provider == "openai":
        from app.channels.stt.openai import OpenAISTT

        return OpenAISTT(settings.require("stt_api_key"))
    raise ValueError(f"unknown STT_PROVIDER {settings.stt_provider!r}")

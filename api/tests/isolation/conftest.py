"""Re-export shared DB fixtures (see tests/support.py)."""

from tests.support import client, factory, it_settings

__all__ = ["client", "factory", "it_settings"]

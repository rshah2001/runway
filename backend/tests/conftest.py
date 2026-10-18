"""Tests always run against the built-in demo data, even on a laptop that has real keys in .env."""

import os

os.environ["RUNWAY_FORCE_MOCK"] = "1"

import pytest  # noqa: E402

from app import prefs  # noqa: E402


@pytest.fixture(autouse=True)
def ai_actions_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most agent tests are about what Ask Runway proposes once it's allowed to, so every demo person has
    turned on "Let Ask Runway set things up". Tests of the switch itself turn it off (test_ai_actions.py)."""
    monkeypatch.setattr(prefs, "_demo_settings", {})
    monkeypatch.setitem(prefs.DEFAULTS, "ai_actions", True)

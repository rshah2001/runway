"""Tests always run against the built-in demo data, even on a laptop that has real keys in .env."""

import os

os.environ["RUNWAY_FORCE_MOCK"] = "1"

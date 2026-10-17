"""Runtime configuration.

Live mode needs NESSIE_API_KEY and DATABASE_URL. Without them (CI, a teammate with no keys) the
API serves built-in demo data instead, so the app always has something to render.
"""

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import find_dotenv, load_dotenv

# local dev: walk up from the working directory to the repo-root .env. In Docker the variables
# come from docker compose, and load_dotenv never overrides variables that are already set.
load_dotenv(find_dotenv(usecwd=True))


@dataclass(frozen=True)
class Settings:
    nessie_api_key: str
    nessie_base_url: str
    database_url: str
    force_mock: bool
    live_transfers: bool  # real Nessie writes on "Fix it" — keep off until approve checks the Auth0 user
    sync_interval: int  # seconds between background Nessie → Tiger Data syncs; 0 disables

    @property
    def live(self) -> bool:
        return bool(self.nessie_api_key and self.database_url) and not self.force_mock


@lru_cache
def get_settings() -> Settings:
    return Settings(
        nessie_api_key=os.getenv("NESSIE_API_KEY", ""),
        nessie_base_url=os.getenv("NESSIE_BASE_URL", "https://api.nessieisreal.com").rstrip("/"),
        database_url=os.getenv("DATABASE_URL", ""),
        force_mock=os.getenv("RUNWAY_FORCE_MOCK") == "1",
        live_transfers=os.getenv("LIVE_TRANSFERS") == "1",
        sync_interval=int(os.getenv("SYNC_INTERVAL_SECONDS", "300")),
    )

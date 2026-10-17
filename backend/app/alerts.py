"""Heads-up alerts: one push to your phone a few days before a dip, so you never have to open the forecast.

In our buyer panel, 17 of the 20 people who said no avoid looking at their balance; what would
change their mind was "just ping me once before a real problem, with a one-tap fix". So:

  * once per dip — the dip's date is remembered, so a forecast that wobbles doesn't nag
  * only within ALERT_AHEAD_DAYS — near enough to be sure, far enough to fix
  * no amounts in the text — a lock screen is public; tapping it opens Today, where the fix is
    ("Cover this dip"), and nothing moves until you approve it there

Delivery is standard Web Push (VAPID): the website registers a service worker (app/public/sw.js)
and sends us its subscription. On iPhone that works once Runway is added to the Home Screen.
Without VAPID keys configured, everything else still works and alerts are simply off.
Subscribing is the opt-in; it's offered when someone turns on "Alerts only".
"""

import json
import logging
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime

from app.config import get_settings

log = logging.getLogger(__name__)

ALERT_AHEAD_DAYS = 5
_lock = threading.Lock()  # one alert pass at a time: two can't both decide a dip is new

# offline / demo mode only (live: Tiger Data tables push_subscriptions and alerts_sent)
_demo_subs: dict[str, dict] = {}  # endpoint -> {"slug", "endpoint", "p256dh", "auth"}
_demo_sent: set[tuple[str, date]] = set()


@dataclass(frozen=True)
class Vapid:
    public_key: str  # base64url, uncompressed P-256 point: the browser needs it to subscribe
    private_key: str  # base64url raw key; never leaves the server
    subject: str  # who push services contact about abuse


def vapid() -> Vapid | None:
    """The VAPID keys, or None when push alerts aren't configured."""
    pub, priv = os.getenv("VAPID_PUBLIC_KEY", ""), os.getenv("VAPID_PRIVATE_KEY", "")
    if not (pub and priv):
        return None
    return Vapid(pub, priv, os.getenv("VAPID_SUBJECT", "mailto:alerts@sixsevenbucksleft.vip"))


# ---------- what the alert says ----------
def first_dip(points, floor: float, today: date, ahead: int = ALERT_AHEAD_DAYS) -> date | None:
    """The first day within `ahead` days the balance goes under what this person keeps, if any."""
    for p in points:
        if (p.date - today).days > ahead:
            return None
        if p.balance < floor:
            return p.date
    return None


def message(dip: date, today: date) -> dict:
    """The notification: no amounts or merchants — anyone can read a lock screen."""
    when = "today" if dip == today else f"on {dip:%a}, {dip:%b} {dip.day}"
    body = (
        "You're under what you keep today." if dip == today else f"You'd run short {when}, before your next paycheck."
    )
    return {
        "title": "Heads up from Runway",
        "body": f"{body} Tap to cover it. Nothing moves until you say yes.",
        "url": "/",
        "tag": f"dip-{dip.isoformat()}",  # a newer alert about the same dip replaces the old one
    }


# ---------- subscriptions ----------
# We POST to whatever endpoint a browser hands us, so only the browsers' own push services are
# accepted — otherwise a caller could make the server call any URL (SSRF).
PUSH_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge on Android, most Android browsers
    "updates.push.services.mozilla.com",  # Firefox
    "web.push.apple.com",  # Safari, and iPhone home-screen web apps
    ".push.apple.com",
    ".notify.windows.com",  # Edge on Windows
)


def canonical_endpoint(endpoint: str) -> str | None:
    """The endpoint rebuilt from its parsed parts if it's a browser push service, else None. Anything
    two URL parsers could read differently (backslashes, user@host, whitespace, control characters)
    is refused, and only the rebuilt URL is ever stored or sent to."""
    from urllib.parse import urlsplit

    if any(c in endpoint for c in "\\@") or any(ord(c) <= 32 or ord(c) == 127 for c in endpoint):
        return None
    u = urlsplit(endpoint)
    if u.scheme != "https" or u.username or u.password or u.fragment:
        return None
    try:
        port = u.port
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if port not in (None, 443) or not any(host.endswith(h) if h.startswith(".") else host == h for h in PUSH_HOSTS):
        return None
    return f"https://{host}{u.path or '/'}" + (f"?{u.query}" if u.query else "")


def allowed_endpoint(endpoint: str) -> bool:
    return canonical_endpoint(endpoint) is not None


def subscribe(slug: str, endpoint: str, p256dh: str, auth: str) -> None:
    """Remember this browser for `slug` (re-subscribing the same browser just updates it)."""
    endpoint = canonical_endpoint(endpoint) or ""
    if not endpoint:
        raise ValueError("not a browser push service")
    if not get_settings().live:
        _demo_subs[endpoint] = {"slug": slug, "endpoint": endpoint, "p256dh": p256dh, "auth": auth}
        return
    from app.db import pool

    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (endpoint, slug, p256dh, auth) VALUES (%s, %s, %s, %s)
               ON CONFLICT (endpoint) DO UPDATE SET slug = EXCLUDED.slug, p256dh = EXCLUDED.p256dh,
                   auth = EXCLUDED.auth, created_at = now()""",
            (endpoint, slug, p256dh, auth),
        )
        conn.commit()


def subscriptions(slug: str | None = None) -> list[dict]:
    if not get_settings().live:
        return [s for s in _demo_subs.values() if slug is None or s["slug"] == slug]
    from app.db import pool

    with pool.connection() as conn:
        q = "SELECT endpoint, slug, p256dh, auth FROM push_subscriptions"
        rows = conn.execute(q + " WHERE slug = %s", (slug,)) if slug else conn.execute(q)
        return list(rows.fetchall())


def _forget(endpoint: str) -> None:
    """The push service says this browser is gone (unsubscribed, or app removed)."""
    if not get_settings().live:
        _demo_subs.pop(endpoint, None)
        return
    from app.db import pool

    with pool.connection() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        conn.commit()


# ---------- sending ----------
def send(sub: dict, payload: dict, keys: Vapid) -> bool:
    """Push one notification to one browser. False if it didn't go (a dead subscription is dropped)."""
    import requests
    from pywebpush import WebPushException, webpush

    endpoint = canonical_endpoint(sub["endpoint"])
    if endpoint is None:  # stored before the rules tightened, or tampered with: never send
        _forget(sub["endpoint"])
        return False
    session = requests.Session()
    session.max_redirects = 0  # a push service never redirects; following one could reach anywhere
    try:
        webpush(
            requests_session=session,
            subscription_info={"endpoint": endpoint, "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=json.dumps(payload),
            vapid_private_key=keys.private_key,
            vapid_claims={"sub": keys.subject},
            ttl=12 * 3600,  # a heads-up older than half a day isn't worth delivering
        )
        return True
    except requests.TooManyRedirects:
        log.warning("push to a %s browser was redirected; not followed", sub["slug"])
        return False
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            _forget(sub["endpoint"])
        else:
            log.warning("push to a %s browser failed (%s)", sub["slug"], status)
        return False


def _claim(slug: str, dip: date) -> bool:
    """Record that `slug` was told about the dip on `dip`. False if they already were."""
    if not get_settings().live:
        if (slug, dip) in _demo_sent:
            return False
        _demo_sent.add((slug, dip))
        return True
    from app.db import pool

    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO alerts_sent (slug, dip_date) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING slug",
            (slug, dip),
        ).fetchone()
        conn.commit()
    return row is not None


def run(today: date | None = None) -> int:
    """Alert everyone subscribed whose forecast dips within ALERT_AHEAD_DAYS, once per dip. Returns
    how many people were alerted. Called from the background pass; never raises."""
    keys = vapid()
    if keys is None:
        return 0
    from app.cashflow import LOCAL_TZ
    from app.forecast import engine

    alerted = 0
    with _lock:
        try:
            subs = subscriptions()
        except Exception:
            log.exception("alerts: couldn't read subscriptions")
            return 0
        by_slug: dict[str, list[dict]] = {}
        for s in subs:
            by_slug.setdefault(s["slug"], []).append(s)
        for slug, theirs in by_slug.items():
            try:
                f = engine.forecast(days=ALERT_AHEAD_DAYS + 1, persona=slug)
                day = today or datetime.now(LOCAL_TZ).date()
                dip = first_dip(f.points, f.safe_floor, day)
                if dip is None or not _claim(slug, dip):
                    continue
                payload = message(dip, day)
                if any([send(s, payload, keys) for s in theirs]):  # list: every browser gets it
                    alerted += 1
            except Exception:
                log.exception("alerts: pass failed for %s", slug)
    return alerted


def test(slug: str, today: date) -> int:
    """Send `slug` their current status now ("Alerts are on", or the dip). Returns browsers reached."""
    keys = vapid()
    if keys is None:
        return 0
    from app.forecast import engine

    f = engine.forecast(days=ALERT_AHEAD_DAYS + 1, persona=slug)
    dip = first_dip(f.points, f.safe_floor, today)
    payload = (
        message(dip, today)
        if dip
        else {
            "title": "Runway alerts are on",
            "body": "You're okay for now. We'll only speak up before a dip.",
            "url": "/",
            "tag": "alerts-on",
        }
    )
    return sum(send(s, payload, keys) for s in subscriptions(slug))


def reset(slugs: list[str]) -> None:
    """Forget which dips these people were told about (the demo reset: the dip is fresh again)."""
    for key in [k for k in _demo_sent if k[0] in slugs]:
        _demo_sent.discard(key)
    if get_settings().live:
        from app.db import pool

        with pool.connection() as conn:
            conn.execute("DELETE FROM alerts_sent WHERE slug = ANY(%s)", (slugs,))
            conn.commit()

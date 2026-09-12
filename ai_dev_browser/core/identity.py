"""Proxy-consistent browser identity — timezone + geolocation (and explicit
locale) overrides that survive adb's per-call session model.

Why a module and not a one-off `cdp_send`: `Emulation.*` overrides are
per-CDP-session, and every adb tool call attaches a FRESH session — so a
one-shot override is gone by the next call (and by a new tab / navigation).
`browser_start` records the desired identity in the instance registry;
`get_active_tab` re-applies it on every acquisition, the same per-call
re-assertion the desktop viewport already uses. That is what makes it hold
across new session / new tab / navigation — the three places the manual
`cdp_send` route died.

Distinction kept ON PURPOSE: timezone + geolocation are LOCATION signals and
align with the proxy egress; language is an IDENTITY signal, left alone unless
explicitly set. A zh-CN user behind a Tokyo IP is normal; auto-switching to
ja-JP would manufacture a fresh inconsistency and break usability.
"""

from __future__ import annotations

import json
import logging
import os

from ai_dev_browser.cdp import browser as cdp_browser
from ai_dev_browser.cdp import emulation as cdp_emulation

logger = logging.getLogger(__name__)

# Where --match-proxy derives the egress location from. Queried THROUGH the
# launched browser, so it uses the same proxy the browsing will — the geo
# service sees the proxy IP, never the host. Configurable; must return JSON with
# a `timezone` and (ideally) lat/lon + the egress ip.
GEO_ENDPOINT_ENV = "AI_DEV_BROWSER_GEO_ENDPOINT"
DEFAULT_GEO_ENDPOINT = "http://ip-api.com/json"


def parse_geo(value: str | None) -> list[float] | None:
    """'lat,lon' → [lat, lon]; None / malformed → None."""
    if not value:
        return None
    try:
        lat_s, lon_s = str(value).split(",", 1)
        return [float(lat_s.strip()), float(lon_s.strip())]
    except (ValueError, AttributeError):
        return None


def build_identity(
    timezone: str | None = None,
    geo: list[float] | None = None,
    locale: str | None = None,
    egress_ip: str | None = None,
) -> dict | None:
    """A JSON-serialisable identity record for the registry, or None if nothing
    to override (so a no-proxy / no-args launch stores no identity)."""
    record: dict = {}
    if timezone:
        record["timezone"] = timezone
    if geo and len(geo) == 2:
        record["geo"] = geo
    if locale:
        record["locale"] = locale
    if egress_ip:
        record["egress_ip"] = egress_ip
    return record or None


async def apply_identity(tab, identity: dict | None) -> None:
    """Re-assert the recorded overrides on `tab`'s session. Best-effort and
    idempotent — safe to call on every tab acquisition, never blocks it."""
    if not identity:
        return
    tz = identity.get("timezone")
    geo = identity.get("geo")
    locale = identity.get("locale")

    if tz:
        try:
            await tab.send(
                cdp_emulation.set_timezone_override(timezone_id=tz), _is_update=True
            )
        except Exception:
            logger.debug("setTimezoneOverride(%s) failed", tz, exc_info=True)

    if geo and len(geo) == 2:
        try:
            await tab.send(
                cdp_emulation.set_geolocation_override(
                    latitude=geo[0], longitude=geo[1], accuracy=50.0
                ),
                _is_update=True,
            )
            # Grant geolocation so a site that reads it sees the mocked position
            # instead of hanging on / being denied a permission prompt — without
            # that, the override value is consistent but unreadable.
            await tab.send(
                cdp_browser.set_permission(
                    permission=cdp_browser.PermissionDescriptor(name="geolocation"),
                    setting=cdp_browser.PermissionSetting.GRANTED,
                ),
                _is_update=True,
            )
        except Exception:
            logger.debug("setGeolocationOverride failed", exc_info=True)

    if locale:
        try:
            await tab.send(
                cdp_emulation.set_locale_override(locale=locale), _is_update=True
            )
        except Exception:
            logger.debug("setLocaleOverride(%s) failed", locale, exc_info=True)


def parse_geo_json(raw: str | None) -> dict | None:
    """Pull `{timezone, ip, lat?, lon?}` from a geo-IP service's JSON text.

    Handles both common schemas: ip-api.com (`timezone`, `lat`, `lon`, `query`)
    and ipinfo.io (`timezone`, `loc: "lat,lon"`, `ip`). None if no timezone."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else None
    except Exception:
        data = None
    if not isinstance(data, dict):
        return None
    tz = data.get("timezone")
    if not tz:
        return None
    lat = data.get("lat", data.get("latitude"))
    lon = data.get("lon", data.get("longitude"))
    if (lat is None or lon is None) and isinstance(data.get("loc"), str):
        pair = parse_geo(data["loc"])  # ipinfo.io "lat,lon"
        if pair:
            lat, lon = pair
    out: dict = {"timezone": tz, "ip": data.get("query") or data.get("ip")}
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        out["lat"], out["lon"] = float(lat), float(lon)
    return out


async def derive_from_proxy(
    port: int, endpoint: str | None = None, timeout: float = 15.0
):
    """Derive the egress location by fetching a geo-IP JSON THROUGH the launched
    browser (so it traverses the same proxy). Opens a throwaway tab at the
    endpoint, reads + parses the JSON, closes the tab. Returns `{timezone, ip,
    lat?, lon?}` or None on any failure (caller fails soft + warns)."""
    import asyncio
    import contextlib
    import time

    from ai_dev_browser.cdp import target as cdp_target

    from .connection import connect_browser

    endpoint = endpoint or os.environ.get(GEO_ENDPOINT_ENV) or DEFAULT_GEO_ENDPOINT
    try:
        browser = await connect_browser(port=port)
        lookup = await browser.get(endpoint)  # throwaway tab at the geo endpoint
    except Exception:
        logger.debug("proxy geo lookup: could not open endpoint", exc_info=True)
        return None
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = await lookup.evaluate(
                    "document.body && document.body.innerText", timeout=5
                )
            except Exception:
                raw = None
            parsed = parse_geo_json(raw) if raw else None
            if parsed:
                return parsed
            await asyncio.sleep(0.5)
        return None
    finally:
        with contextlib.suppress(Exception):
            await browser.connection.send(
                cdp_target.close_target(lookup._target.target_id)
            )
        # Close the throwaway BrowserClient so its cache entry (bound to this
        # temp event loop) doesn't linger for a same-process async consumer.
        with contextlib.suppress(Exception):
            await browser.close()

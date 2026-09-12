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

import logging

from ai_dev_browser.cdp import browser as cdp_browser
from ai_dev_browser.cdp import emulation as cdp_emulation

logger = logging.getLogger(__name__)


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

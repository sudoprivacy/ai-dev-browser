"""End-to-end: image_cap on page_screenshot and screenshot_by_ref.

`image_cap` is a per-call cap the caller wants the screenshot to
fit — typically the accept-limit of whichever downstream consumer
will receive the image. The contract:

  - When absent / empty → existing behaviour (PNG, static caps).
  - `max_dimension` → LANCZOS resize so longest edge fits.
  - `max_bytes`     → switch output to JPEG, quality-step search
                      [85, 70, 55, 40, 25], halve dimensions once
                      as fallback if no quality fits.
  - Metadata (scale_factor, viewport, image dims) still travels
    with the file — PNG text chunk for .png, EXIF UserComment
    (tag 0x9286) for .jpg — so `mouse_click --screenshot` still
    auto-scales coordinates regardless of format.

Strategy: drive a real headless Chrome (no mocks), navigate to
a data:URL fixture with predictable dimensions, capture, then
assert on actual file bytes + decoded image dims + round-tripped
metadata. Parametrized across both screenshot functions and four
cap shapes so a regression in any layer surfaces as a clean
failure on a named cell.
"""

from __future__ import annotations

import base64
import contextlib
import os
from pathlib import Path

import pytest

from ai_dev_browser.core import (
    page_discover,
    page_goto,
    page_screenshot,
    screenshot_by_ref,
)
from ai_dev_browser.core._image_cap import apply_image_cap, read_metadata
from ai_dev_browser.core.browser import browser_start, browser_stop
from ai_dev_browser.core.connection import connect_browser, get_active_tab

SKIP_INTEGRATION = os.environ.get("SKIP_INTEGRATION", "").lower() in (
    "1",
    "true",
    "yes",
)


@pytest.fixture(autouse=True)
def _integration_guard():
    if SKIP_INTEGRATION:
        pytest.skip("SKIP_INTEGRATION is set")


@pytest.fixture
async def tab():
    """Headless Chrome with the fixture page already loaded."""
    result = browser_start(headless=True, temp=True, reuse="none")
    assert "error" not in result, f"browser_start failed: {result}"
    port = result["port"]
    browser_client = None
    try:
        browser_client = await connect_browser(port=port)
        the_tab = await get_active_tab(browser_client)
        # Tall, colorful, predictable fixture. The h1 ref gives us a
        # known element for screenshot_by_ref. Each row uses a different
        # color so JPEG can't trivially zero-out high-frequency content.
        html = (
            "<html><body style='margin:0;font-family:sans-serif'>"
            "<h1 id='top' style='background:#abf;padding:40px;font-size:48px'>"
            "Cap Fixture</h1>"
            + "".join(
                f"<div style='height:80px;background:rgb({i * 7 % 256},"
                f"{(i * 13 + 50) % 256},{(i * 19 + 100) % 256});padding:12px;color:white;"
                f"font-size:24px'>Row {i} — quick brown fox jumps over the "
                "lazy dog 0123456789</div>"
                for i in range(40)
            )
            + "</body></html>"
        )
        data_url = "data:text/html;base64," + base64.b64encode(html.encode()).decode()
        await page_goto(the_tab, data_url)
        yield the_tab
    finally:
        if browser_client is not None:
            with contextlib.suppress(Exception):
                await browser_client.close()
        with contextlib.suppress(Exception):
            browser_stop(port=port)


CAP_CASES = {
    "no_cap": None,
    "dim_only": {"max_dimension": 400},
    # `bytes_only` deliberately doesn't set max_dimension, so the
    # helper exercises the dim-halving fallback path on the tall
    # fixture (~3200px). 100KB is generous enough that quality
    # alone or one halving must fit — with the
    # reserve_bytes_for_metadata budget the final EXIF-stamped file
    # stays under 100KB. The impossible-cap path is covered by
    # test_apply_image_cap_impossible_byte_target_returns_best_effort.
    "bytes_only": {"max_bytes": 100_000},
    # `both` can be tighter because max_dimension pre-shrinks first.
    "both": {"max_dimension": 400, "max_bytes": 15_000},
}


# ---------------------------------------------------------------------------
# page_screenshot — the primary surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_name", list(CAP_CASES))
async def test_page_screenshot_honors_image_cap(tab, tmp_path, case_name):
    """page_screenshot under each cap shape must produce a file that
    respects the constraint and round-trips its metadata."""
    cap = CAP_CASES[case_name]
    out = tmp_path / f"shot_{case_name}.png"
    result = await page_screenshot(tab, path=str(out), full_page=True, image_cap=cap)

    final = Path(result["path"])
    assert final.exists(), f"output file missing: {result}"
    assert result["width"] > 0 and result["height"] > 0

    if cap is None:
        # No-cap path: PNG, no `format`/`capped` keys (preserves old shape).
        assert final.suffix == ".png"
        assert "format" not in result, (
            "format key leaked into no-cap result; would break existing callers"
        )
    else:
        assert "format" in result and "capped" in result, (
            f"capped result missing required keys: {result}"
        )
        if "max_dimension" in cap:
            longest = max(result["width"], result["height"])
            assert longest <= cap["max_dimension"], (
                f"long edge {longest} > max_dimension {cap['max_dimension']}: {result}"
            )
        if "max_bytes" in cap:
            assert final.suffix == ".jpg", (
                f"max_bytes set should produce JPEG, got {final.suffix}: {result}"
            )
            assert result["format"] == "JPEG"
            # `capped=True` means we fit the byte target. False is best-effort
            # — still acceptable in principle, but our fixture is small enough
            # that the quality search must succeed.
            assert result["capped"] is True, (
                f"quality search missed byte cap on fixture: {result}"
            )
            assert result["size"] <= cap["max_bytes"], (
                f"file {result['size']}B > max_bytes {cap['max_bytes']}B: {result}"
            )

    # Metadata must round-trip on the final path regardless of format —
    # this is what mouse_click reads to translate click coordinates.
    meta = read_metadata(str(final))
    assert meta, f"no metadata embedded in {final}: {result}"
    assert meta["image_width"] == result["width"]
    assert meta["image_height"] == result["height"]
    assert "scale_factor" in meta and meta["scale_factor"] > 0


# ---------------------------------------------------------------------------
# screenshot_by_ref — the element-level surface, same contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case_name", list(CAP_CASES))
async def test_screenshot_by_ref_honors_image_cap(tab, tmp_path, case_name):
    """Same cap shapes must work on the element-level screenshot."""
    discover = await page_discover(tab, interactable_only=False)
    # page_discover may return either a list or a dict depending on
    # which API revision is live; tolerate both.
    nodes = discover
    h1 = next(
        (n for n in nodes if (n.get("name") or "").strip() == "Cap Fixture"),
        None,
    )
    assert h1 is not None, (
        f"could not find h1 in page_discover result; first 5: {nodes[:5]}"
    )
    ref = h1["ref"]

    cap = CAP_CASES[case_name]
    out = tmp_path / f"el_{case_name}.png"
    result = await screenshot_by_ref(tab, ref=ref, path=str(out), image_cap=cap)

    final = Path(result["path"])
    assert final.exists()
    assert result["ref"] == ref
    assert result["width"] > 0 and result["height"] > 0

    if cap is None:
        assert final.suffix == ".png"
        assert "format" not in result, "format key leaked into no-cap result"
    else:
        assert "format" in result and "capped" in result
        if "max_dimension" in cap:
            longest = max(result["width"], result["height"])
            assert longest <= cap["max_dimension"]
        if "max_bytes" in cap:
            assert final.suffix == ".jpg"
            assert result["format"] == "JPEG"
            assert result["capped"] is True
            assert result["size"] <= cap["max_bytes"]


# ---------------------------------------------------------------------------
# apply_image_cap — unit-level guarantees that don't need a browser
# ---------------------------------------------------------------------------


@pytest.fixture
def png_fixture(tmp_path):
    """A reasonably-large PNG we can drive through apply_image_cap
    without needing Chrome — exercises decode + resize + re-encode
    plus extension-change deterministically."""
    from PIL import Image

    path = tmp_path / "input.png"
    # 1200x900 with mixed colors so JPEG can't trivially zero-out
    img = Image.new("RGB", (1200, 900))
    px = img.load()
    for y in range(900):
        for x in range(1200):
            px[x, y] = ((x * 3) % 256, (y * 5 + 30) % 256, ((x + y) * 7) % 256)
    img.save(path, format="PNG")
    return path


def test_apply_image_cap_noop_when_cap_absent(png_fixture):
    """No cap → byte-for-byte identical file, dims unchanged."""
    orig_bytes = png_fixture.read_bytes()
    result = apply_image_cap(str(png_fixture), None)
    assert result["final_path"] == str(png_fixture)
    assert result["capped"] is False
    assert png_fixture.read_bytes() == orig_bytes, "no-cap path mutated the file"


def test_apply_image_cap_dim_only_keeps_png(png_fixture):
    """max_dimension only → stay PNG (lossless for OCR), enforce dim."""
    result = apply_image_cap(str(png_fixture), {"max_dimension": 500})
    assert Path(result["final_path"]).suffix == ".png"
    assert max(result["final_width"], result["final_height"]) <= 500
    assert result["format"] == "PNG"


def test_apply_image_cap_bytes_only_produces_jpg(png_fixture):
    """max_bytes only → switch to JPEG, hit the target, leave original
    PNG dim alone (no implicit downscale unless quality search fails)."""
    target = 60_000
    result = apply_image_cap(str(png_fixture), {"max_bytes": target})
    final = Path(result["final_path"])
    assert final.suffix == ".jpg", result
    assert result["capped"] is True, result
    assert result["final_bytes"] <= target, result
    # Original PNG must be cleaned up — we promise the file lives at
    # final_path, not a stale .png + .jpg pair.
    assert not png_fixture.exists() or png_fixture == final, (
        f"original PNG {png_fixture} should have been removed; .jpg is at {final}"
    )


def test_apply_image_cap_both_caps_combine(png_fixture):
    """max_dimension + max_bytes → both must be honored simultaneously."""
    cap = {"max_dimension": 300, "max_bytes": 20_000}
    result = apply_image_cap(str(png_fixture), cap)
    assert max(result["final_width"], result["final_height"]) <= 300
    assert result["final_bytes"] <= 20_000
    assert result["capped"] is True


def test_apply_image_cap_impossible_byte_target_returns_best_effort(png_fixture):
    """If even quality=25 after one dim-halving doesn't fit, we return
    the smallest we produced with capped=False — never raise. Caller
    decides whether to warn/escalate; raising in the screenshot path
    would break the agent loop."""
    cap = {"max_bytes": 100}  # 100 bytes — impossible for any real image
    result = apply_image_cap(str(png_fixture), cap)
    assert result["capped"] is False, (
        f"100-byte cap should be impossible to satisfy: {result}"
    )
    assert Path(result["final_path"]).exists(), "best-effort file must still be on disk"


def test_reserve_bytes_for_metadata_keeps_final_under_cap(png_fixture):
    """Regression for the v0.12.0 → v0.12.1 escape: apply_image_cap
    measured pre-metadata bytes, then write_metadata appended ~250B
    of EXIF UserComment that pushed borderline JPEGs over max_bytes
    (CI flake at 80462B > 80000B cap). With reserve_bytes_for_metadata
    the search runs against `max_bytes - METADATA_OVERHEAD_BUDGET` so
    the post-metadata file always fits."""
    from ai_dev_browser.core._image_cap import write_metadata

    # Cap chosen to fit the high-entropy 1200x900 fixture at quality 25
    # without triggering the dim-halving fallback — keeps this test
    # focused on the metadata-budget contract, not the fallback path
    # (which has its own test). Still tight enough that the EXIF
    # overhead (~250B) is non-negligible — pre-fix v0.12.0 would have
    # overshot by ~1% at this cap.
    target = 80_000
    result = apply_image_cap(
        str(png_fixture), {"max_bytes": target}, reserve_bytes_for_metadata=True
    )
    assert result["capped"] is True, result

    # Realistic screenshot metadata (matches page_screenshot's payload
    # shape): scale_factor, viewport_*, image_*, device_pixel_ratio.
    write_metadata(
        result["final_path"],
        {
            "scale_factor": 1.234567,
            "viewport_width": 1280,
            "viewport_height": 800,
            "image_width": result["final_width"],
            "image_height": result["final_height"],
            "device_pixel_ratio": 2,
        },
    )
    final_size = Path(result["final_path"]).stat().st_size
    assert final_size <= target, (
        f"reserve_bytes_for_metadata failed: image+EXIF {final_size}B > cap {target}B"
    )


# ---------------------------------------------------------------------------
# Metadata round-trip — the contract mouse_click depends on
# ---------------------------------------------------------------------------


def test_metadata_round_trips_through_png(png_fixture):
    """PNG path uses tEXt chunk — historic behaviour preserved."""
    from ai_dev_browser.core._image_cap import write_metadata

    payload = {"scale_factor": 1.5, "viewport_width": 1280, "image_width": 850}
    write_metadata(str(png_fixture), payload)
    out = read_metadata(str(png_fixture))
    assert out == payload, f"PNG metadata mismatch: {out!r} vs {payload!r}"


def test_metadata_round_trips_through_jpeg(png_fixture):
    """JPEG path uses EXIF UserComment (0x9286). New code path — must
    work end-to-end so mouse_click can read it after image_cap forces JPG."""
    from ai_dev_browser.core._image_cap import write_metadata

    # Force JPEG conversion via apply_image_cap, then write+read metadata.
    apply_image_cap(str(png_fixture), {"max_bytes": 50_000})
    jpg = png_fixture.with_suffix(".jpg")
    assert jpg.exists()
    payload = {"scale_factor": 2.0, "viewport_width": 800, "image_width": 400}
    write_metadata(str(jpg), payload)
    out = read_metadata(str(jpg))
    assert out == payload, f"JPEG metadata mismatch: {out!r} vs {payload!r}"


# ---------------------------------------------------------------------------
# resolve_cap — env-fallback precedence (per-call arg > env > None)
# ---------------------------------------------------------------------------


def test_resolve_cap_explicit_arg_wins_over_env(monkeypatch):
    """Per-call arg always overrides env — a dynamic per-call cap
    must beat any stale process-wide env inherited from the shell."""
    from ai_dev_browser.core._image_cap import (
        ENV_MAX_BYTES,
        ENV_MAX_DIMENSION,
        resolve_cap,
    )

    monkeypatch.setenv(ENV_MAX_BYTES, "5242880")
    monkeypatch.setenv(ENV_MAX_DIMENSION, "8000")
    got = resolve_cap({"max_bytes": 100_000})
    assert got == {"max_bytes": 100_000}, f"explicit arg should win verbatim, got {got}"


def test_resolve_cap_env_fallback_when_arg_missing(monkeypatch):
    """No per-call arg → env-derived cap. Both env vars set → both
    keys present. This is the inject-once-in-parent-process workflow."""
    from ai_dev_browser.core._image_cap import (
        ENV_MAX_BYTES,
        ENV_MAX_DIMENSION,
        resolve_cap,
    )

    monkeypatch.setenv(ENV_MAX_BYTES, "524288")
    monkeypatch.setenv(ENV_MAX_DIMENSION, "1568")
    assert resolve_cap(None) == {"max_bytes": 524288, "max_dimension": 1568}


def test_resolve_cap_partial_env_produces_partial_dict(monkeypatch):
    """Only one env set → only that key. resolve_cap doesn't invent
    a value for the missing knob."""
    from ai_dev_browser.core._image_cap import (
        ENV_MAX_BYTES,
        ENV_MAX_DIMENSION,
        resolve_cap,
    )

    monkeypatch.setenv(ENV_MAX_BYTES, "1048576")
    monkeypatch.delenv(ENV_MAX_DIMENSION, raising=False)
    assert resolve_cap(None) == {"max_bytes": 1048576}


def test_resolve_cap_no_env_returns_none(monkeypatch):
    """Neither env nor arg → None, so callers hit their uncapped
    default (page_screenshot's max_long_edge/max_total_pixels path)."""
    from ai_dev_browser.core._image_cap import (
        ENV_MAX_BYTES,
        ENV_MAX_DIMENSION,
        resolve_cap,
    )

    monkeypatch.delenv(ENV_MAX_BYTES, raising=False)
    monkeypatch.delenv(ENV_MAX_DIMENSION, raising=False)
    assert resolve_cap(None) is None


def test_resolve_cap_malformed_env_is_logged_not_raised(monkeypatch, caplog):
    """A bad env value must never crash the agent loop. The
    malformed key is dropped; other valid keys still surface."""
    import logging

    from ai_dev_browser.core._image_cap import (
        ENV_MAX_BYTES,
        ENV_MAX_DIMENSION,
        resolve_cap,
    )

    monkeypatch.setenv(ENV_MAX_BYTES, "not-a-number")
    monkeypatch.setenv(ENV_MAX_DIMENSION, "2048")
    with caplog.at_level(logging.WARNING, logger="ai_dev_browser.core._image_cap"):
        got = resolve_cap(None)
    assert got == {"max_dimension": 2048}, (
        f"malformed byte cap should be dropped, dimension kept: {got}"
    )
    assert any("malformed" in r.message.lower() for r in caplog.records), (
        f"expected warning about malformed env, got: {[r.message for r in caplog.records]}"
    )


async def test_page_screenshot_uses_env_when_no_per_call_arg(
    tab, tmp_path, monkeypatch
):
    """End-to-end: with env set + no per-call image_cap, page_screenshot
    still respects the cap. This is the auto-inject path — enclosing
    process sets env once, agent code doesn't need to know about
    image_cap at the call site."""
    from ai_dev_browser.core._image_cap import ENV_MAX_BYTES

    monkeypatch.setenv(ENV_MAX_BYTES, "100000")
    out = tmp_path / "shot_env.png"
    result = await page_screenshot(tab, path=str(out), full_page=True)
    # No image_cap arg → env kicks in → JPEG produced, size under cap.
    assert Path(result["path"]).suffix == ".jpg", (
        f"env AI_DEV_BROWSER_IMAGE_CAP_MAX_BYTES should force JPEG: {result}"
    )
    assert result["size"] <= 100_000, f"env cap not honored: {result['size']} > 100000"


async def test_screenshot_by_ref_uses_env_when_no_per_call_arg(
    tab, tmp_path, monkeypatch
):
    """Same env-fallback for the element-level surface. Both entry
    points must resolve consistently."""
    from ai_dev_browser.core._image_cap import ENV_MAX_DIMENSION

    monkeypatch.setenv(ENV_MAX_DIMENSION, "300")
    discover = await page_discover(tab, interactable_only=False)
    nodes = discover
    h1 = next(
        (n for n in nodes if (n.get("name") or "").strip() == "Cap Fixture"),
        None,
    )
    assert h1 is not None
    out = tmp_path / "el_env.png"
    result = await screenshot_by_ref(tab, ref=h1["ref"], path=str(out))
    longest = max(result["width"], result["height"])
    assert longest <= 300, (
        f"env AI_DEV_BROWSER_IMAGE_CAP_MAX_DIMENSION not honored: {result}"
    )


# ---------------------------------------------------------------------------
# Format dispatch — the mouse_click contract
# ---------------------------------------------------------------------------


def test_read_screenshot_metadata_dispatches_by_extension(png_fixture):
    """The public surface in page.py must accept both formats — this is
    what `mouse._scale_coords` calls. Regression-pinning the dispatch."""
    from ai_dev_browser.core._image_cap import write_metadata
    from ai_dev_browser.core.page import read_screenshot_metadata

    write_metadata(str(png_fixture), {"scale_factor": 1.0, "image_width": 1200})
    assert read_screenshot_metadata(str(png_fixture))["image_width"] == 1200

    apply_image_cap(str(png_fixture), {"max_bytes": 50_000})
    jpg = png_fixture.with_suffix(".jpg")
    write_metadata(str(jpg), {"scale_factor": 2.0, "image_width": 600})
    assert read_screenshot_metadata(str(jpg))["image_width"] == 600

"""Apply LLM-cap constraints to a saved screenshot file, in place.

`image_cap` is a per-call override forwarded by consumers (most
commonly sudowork) from the active LLM session's
`_meta.imageCapability`. Shape:

    {"max_bytes": int, "max_dimension": int}    # both optional

When `max_dimension` is set: LANCZOS resize so the longest edge
fits. When `max_bytes` is set: re-encode as JPEG with quality
stepping `85 → 70 → 55 → 40 → 25` (mirrors sudocode-runtime's
`preflight_base64` loop). If even quality=25 misses the byte
target, we halve dimensions once and re-step; if still missing,
return best-effort with `capped=False` so the caller can decide
whether to warn or escalate.

Also owns the screenshot metadata write/read path. PNG → text
chunk via `PIL.PngImagePlugin.PngInfo`; JPEG → EXIF UserComment
(tag 0x9286). Single read entry point so consumers like
`mouse._scale_coords` stay format-agnostic. No sidecar files —
metadata always travels with the image.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Matches sudocode-runtime/src/image_registry.rs preflight_base64.
# Discrete steps (not binary search) for predictable, bounded
# iterations across both systems.
QUALITY_STEPS = (85, 70, 55, 40, 25)

# Don't let the byte-target fallback halving shrink an image below
# a sensible OCR-usable floor. 96px is roughly the lower bound where
# a UI label remains legible to vision-LLMs.
MIN_DIMENSION_AFTER_HALVING = 96

# Standard EXIF UserComment prefix: 8-byte character-code header
# per EXIF 2.32 §4.6.5. "ASCII\0\0\0" indicates the comment payload
# is ASCII/UTF-8 bytes.
_EXIF_USER_COMMENT_TAG = 0x9286
_EXIF_USER_COMMENT_ASCII_PREFIX = b"ASCII\x00\x00\x00"


def _wants_cap(cap: dict[str, Any] | None) -> bool:
    """True iff cap is provided and has at least one active constraint."""
    return bool(cap) and bool(cap.get("max_bytes") or cap.get("max_dimension"))


def apply_image_cap(path: str, cap: dict[str, Any] | None) -> dict[str, Any]:
    """Resize/recompress `path` in place to fit `cap`. May change the
    file extension PNG → JPG when `max_bytes` is set.

    Returns a dict describing the post-cap state — caller uses this
    to embed metadata + return to the user:
      {final_path, final_bytes, final_width, final_height,
       format ('PNG'|'JPEG'), quality (int|None), capped (bool)}

    `capped=True` means we fit the constraint; `False` means
    best-effort (smallest we could produce still missed the target).
    """
    from PIL import Image

    src = Path(path)

    if not _wants_cap(cap):
        with Image.open(src) as img:
            w, h = img.size
        return {
            "final_path": str(src),
            "final_bytes": src.stat().st_size,
            "final_width": w,
            "final_height": h,
            "format": "PNG" if src.suffix.lower() == ".png" else "JPEG",
            "quality": None,
            "capped": False,
        }

    max_bytes = cap.get("max_bytes")
    max_dim = cap.get("max_dimension")

    with Image.open(src) as opened:
        img = opened.copy()  # detach from file so we can rewrite src

    # Step 1: dimension cap (if any). Always-apply, even when max_bytes
    # is also set — pre-shrinking gives the quality search a smaller
    # target and fewer iterations.
    if max_dim:
        long_edge = max(img.size)
        if long_edge > max_dim:
            ratio = max_dim / long_edge
            new_size = (
                max(1, int(img.size[0] * ratio)),
                max(1, int(img.size[1] * ratio)),
            )
            img = img.resize(new_size, Image.Resampling.LANCZOS)

    # Step 2: byte cap (if any) → switch to JPEG + quality search.
    if max_bytes:
        jpg_path = src.with_suffix(".jpg")
        if img.mode != "RGB":
            img = img.convert("RGB")

        chosen_quality, capped = _quality_search(img, jpg_path, max_bytes)

        # If quality alone didn't fit, try a single dimension halving
        # and re-run the search. Bounded fallback so we don't loop
        # forever on impossible caps.
        if not capped:
            halved = (img.size[0] // 2, img.size[1] // 2)
            if (
                halved[0] >= MIN_DIMENSION_AFTER_HALVING
                and halved[1] >= MIN_DIMENSION_AFTER_HALVING
            ):
                img = img.resize(halved, Image.Resampling.LANCZOS)
                chosen_quality, capped = _quality_search(img, jpg_path, max_bytes)

        # Remove the original PNG if we switched extensions.
        if src.suffix.lower() != ".jpg" and src.exists():
            src.unlink()

        return {
            "final_path": str(jpg_path),
            "final_bytes": jpg_path.stat().st_size,
            "final_width": img.size[0],
            "final_height": img.size[1],
            "format": "JPEG",
            "quality": chosen_quality,
            "capped": capped,
        }

    # max_dimension only, no byte cap → stay as the original format
    # (PNG keeps PngInfo metadata working; lossless for vision OCR).
    img.save(src, format="PNG", optimize=True)
    return {
        "final_path": str(src),
        "final_bytes": src.stat().st_size,
        "final_width": img.size[0],
        "final_height": img.size[1],
        "format": "PNG",
        "quality": None,
        "capped": True,
    }


def _quality_search(img, jpg_path: Path, max_bytes: int) -> tuple[int, bool]:
    """Try each step in QUALITY_STEPS in order; return (chosen, fit)
    of the first quality whose encoded size <= max_bytes, else
    (lowest_quality, False) with the lowest-quality file still on disk
    (best-effort)."""
    for q in QUALITY_STEPS:
        img.save(jpg_path, format="JPEG", quality=q, optimize=True)
        if jpg_path.stat().st_size <= max_bytes:
            return q, True
    # Smallest quality file is what's on disk; signal best-effort.
    return QUALITY_STEPS[-1], False


def write_metadata(path: str, metadata: dict[str, Any]) -> None:
    """Embed `metadata` (a JSON-serializable dict) into the image at
    `path`. Format dispatched by extension: PNG → tEXt chunk under
    key 'ai_dev_browser'; JPEG → EXIF UserComment (0x9286).

    Idempotent: re-running with the same metadata is a no-op. Safe
    to call after `apply_image_cap` (which may have changed the
    extension)."""
    from PIL import Image

    src = Path(path)
    payload = json.dumps(metadata)
    suffix = src.suffix.lower()

    # Open + load + save inside the same `with` block. `.copy()` would
    # detach the pixels but also reset `.format` to None, which breaks
    # PIL's `quality="keep"` (needs img.format == "JPEG"). Loading
    # eagerly lets us save back to the same path without holding the
    # file handle.
    with Image.open(src) as img:
        img.load()
        if suffix == ".png":
            from PIL.PngImagePlugin import PngInfo

            meta = PngInfo()
            meta.add_text("ai_dev_browser", payload)
            img.save(src, format="PNG", pnginfo=meta)
        elif suffix in (".jpg", ".jpeg"):
            exif = Image.Exif()
            exif[_EXIF_USER_COMMENT_TAG] = (
                _EXIF_USER_COMMENT_ASCII_PREFIX + payload.encode("utf-8")
            )
            # quality="keep" preserves the JPEG quantization tables from
            # the last encode so this rewrite adds no generation loss.
            img.save(src, format="JPEG", exif=exif.tobytes(), quality="keep")
        # Other formats: silently no-op (no place to embed). Callers
        # only ever produce PNG/JPEG today.


def read_metadata(path: str) -> dict[str, Any]:
    """Read ai_dev_browser metadata back. Dispatched by extension;
    returns {} on any failure (missing file, unsupported format,
    malformed payload) — never raises, so callers like
    `mouse._scale_coords` can treat it as best-effort context."""
    from PIL import Image

    src = Path(path)
    suffix = src.suffix.lower()
    try:
        with Image.open(src) as img:
            if suffix == ".png":
                raw = img.info.get("ai_dev_browser") or img.text.get("ai_dev_browser")  # type: ignore[attr-defined]
                if raw:
                    return json.loads(raw)
            elif suffix in (".jpg", ".jpeg"):
                exif = img.getexif()
                raw_bytes = exif.get(_EXIF_USER_COMMENT_TAG)
                if isinstance(raw_bytes, bytes) and raw_bytes.startswith(
                    _EXIF_USER_COMMENT_ASCII_PREFIX
                ):
                    return json.loads(
                        raw_bytes[len(_EXIF_USER_COMMENT_ASCII_PREFIX) :].decode(
                            "utf-8", errors="replace"
                        )
                    )
    except Exception:
        pass
    return {}

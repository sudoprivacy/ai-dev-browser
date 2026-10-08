"""Viewer-facing path continuity and animated GIF playback contracts."""

import base64
import io
import itertools
import math
import random

from PIL import Image, ImageDraw

from ai_dev_browser.core._recorder import _Gif
from ai_dev_browser.core.human import generate_gaussian_path


def test_curve_settles_at_target_without_endpoint_jumps():
    original = random.getstate()
    try:
        for seed in range(20):
            random.seed(seed)
            path = generate_gaussian_path(100, 100, 400, 100, duration=0.5)
            assert path[0] == (100, 100) and path[-1] == (400, 100)
            assert max(math.dist(a, b) for a, b in itertools.pairwise(path)) < 40
            assert all(85 <= x <= 415 and 70 <= y <= 130 for x, y in path)
    finally:
        random.setstate(original)


def test_moving_pointer_encodes_small_changes_and_erases_old_positions(tmp_path):
    path = tmp_path / "cursor.gif"
    with path.open("wb") as handle:
        gif = _Gif(handle)
        for index in range(60):
            frame = Image.new("RGB", (960, 640), "#eef2f7")
            ImageDraw.Draw(frame).ellipse(
                (index * 8, 100, index * 8 + 12, 112), fill="#2563eb"
            )
            encoded = io.BytesIO()
            frame.save(encoded, format="PNG")
            gif.push(base64.b64encode(encoded.getvalue()).decode(), 100 + index / 10)
        gif.finish(106)
    assert path.stat().st_size < 20_000
    with Image.open(path) as decoded:
        assert decoded.n_frames == 60
        decoded.seek(59)
        frame = decoded.convert("RGB")
        assert frame.getpixel((4, 106)) == (238, 242, 247)
        assert frame.getpixel((59 * 8 + 6, 106)) == (37, 99, 235)

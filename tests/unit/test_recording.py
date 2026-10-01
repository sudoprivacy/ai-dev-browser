"""File-format and CLI failure contracts that don't require a browser."""

import base64
import io

from PIL import Image
import pytest

from ai_dev_browser._cli import wrap_core, wrap_core_sync, _exit_code_for_result
from ai_dev_browser.core._recorder import _Gif
from ai_dev_browser.core.errors import RecordingError


def _png(color, size=(64, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_gif_preserves_palette_resize_and_wall_clock(tmp_path):
    path = tmp_path / "timeline.gif"
    with path.open("wb") as handle:
        gif = _Gif(handle)
        gif.push(_png("red"), 100)
        gif.push(_png("green", (100, 100)), 102.34)
        gif.push(_png("blue"), 102.38)
        gif.finish(107.91)
    with Image.open(path) as decoded:
        assert decoded.n_frames == 3
        assert decoded.info["loop"] == 0
        colors = []
        durations = []
        for index in range(decoded.n_frames):
            decoded.seek(index)
            decoded.load()
            assert decoded.size == (64, 40)
            colors.append(decoded.convert("RGB").getpixel((32, 20)))
            durations.append(decoded.info["duration"])
        assert colors == [(255, 0, 0), (0, 128, 0), (0, 0, 255)]
        assert durations == [2340, 40, 5530]


@pytest.mark.parametrize(
    "code,exit_code", [("validation", 2), ("conflict", 5), ("recording_failed", 1)]
)
async def test_capture_failure_never_suggests_retrying_lost_content(code, exit_code):
    # Even a message containing "WebSocket" must not make stop retryable: the
    # transport heuristic applies to ordinary calls, not a lost recording.
    async def fail():
        """Fail.

        Failure:
            Record the interaction again.
        """
        raise RecordingError("WebSocket lost during recording", code)

    def fail_sync():
        raise RecordingError("WebSocket lost during recording", code)

    for result in (await wrap_core(fail)(), wrap_core_sync(fail_sync)()):
        assert result["error_code"] == code
        assert result["retryable"] is False
        assert _exit_code_for_result(result) == exit_code
    assert (await wrap_core(fail)())["hint"] == "Record the interaction again."

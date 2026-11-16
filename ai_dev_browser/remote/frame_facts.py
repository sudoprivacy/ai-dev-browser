"""Original checked-replay frame facts, shared with guarded diagnostics reads."""

from typing import Any

from .control import ControlError


async def page_frames(page: Any) -> list[dict[str, Any]]:
    tree = await page.call("Page.getFrameTree")
    frames: list[dict[str, Any]] = []

    def visit(node: dict[str, Any], lineage: list[str]) -> None:
        frame = node["frame"]
        origin = frame.get("securityOrigin")
        if not isinstance(origin, str):
            raise ControlError("browser_replay_frame_invalid")
        current = {
            "id": frame["id"],
            "loaderId": frame.get("loaderId"),
            "url": frame["url"],
            "origin": origin,
            "path": lineage,
        }
        frames.append(current)
        if len(frames) > 128 or len(lineage) > 16:
            raise ControlError("browser_replay_frame_invalid")
        for child in node.get("childFrames", []):
            child_origin = child["frame"].get("securityOrigin")
            if not isinstance(child_origin, str):
                raise ControlError("browser_replay_frame_invalid")
            visit(child, [*lineage, child_origin])

    visit(tree["frameTree"], [])
    return frames

"""Scroll the page.

CLI:
    python -m nodriver_kit.tools.scroll --direction down
    python -m nodriver_kit.tools.scroll --to-bottom
    python -m nodriver_kit.tools.scroll --to-top

Python:
    from nodriver_kit.tools import scroll
    result = await scroll(tab, direction="down")
"""

from nodriver_kit.core import scroll as core_scroll
from ._cli import as_cli


@as_cli
async def scroll(
    tab,
    direction: str = "down",
    amount: int = 25,
    to_bottom: bool = False,
    to_top: bool = False,
) -> dict:
    """Scroll the page.

    Args:
        tab: Browser tab
        direction: "up" or "down"
        amount: Scroll amount (percentage)
        to_bottom: Scroll to bottom of page
        to_top: Scroll to top of page

    Returns:
        {"scrolled": True} on success
    """
    try:
        await core_scroll(
            tab,
            direction=direction,
            amount=amount,
            to_bottom=to_bottom,
            to_top=to_top,
        )
        return {"scrolled": True, "direction": direction}
    except Exception as e:
        return {"error": f"Scroll failed: {e}"}


if __name__ == "__main__":
    scroll.cli_main()

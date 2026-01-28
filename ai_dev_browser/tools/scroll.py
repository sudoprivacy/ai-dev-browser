"""Scroll the page."""

from ai_dev_browser.core import scroll as core_scroll
from .._cli import as_cli


@as_cli()
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

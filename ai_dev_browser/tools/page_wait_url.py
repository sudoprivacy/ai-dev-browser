"""Wait for URL to match a pattern."""

from ..core.navigation import wait_for_url as core_wait_for_url
from .._cli import as_cli


@as_cli()
async def page_wait_url(
    tab,
    pattern: str = None,
    exact: str = None,
    timeout: float = 30,
) -> dict:
    """Wait for URL to match pattern.

    Args:
        tab: Browser tab
        pattern: URL pattern (substring or regex)
        exact: Exact URL to match
        timeout: Maximum wait time in seconds
    """
    if not pattern and not exact:
        return {"error": "Must specify --pattern or --exact"}

    result = await core_wait_for_url(tab, pattern=pattern, exact=exact, timeout=timeout)

    # Add timeout message if not matched
    if not result.get("matched"):
        result["message"] = f"Timeout after {timeout}s"

    return result


if __name__ == "__main__":
    page_wait_url.cli_main()

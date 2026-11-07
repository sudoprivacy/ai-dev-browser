"""Read startup state only from the fixture's isolated extension worker."""

from ai_dev_browser.cdp import runtime
from ai_dev_browser.core import connect_browser


async def inspect_extension_worker(chrome_port, bridge_port):
    browser = await connect_browser(port=chrome_port)
    states = []
    try:
        for candidate in browser.targets:
            if candidate.type_ != "service_worker":
                continue
            try:
                value, error = await candidate._connection.send(
                    runtime.evaluate(
                        "typeof BRIDGE === 'string' ? BRIDGE : null",
                        return_by_value=True,
                    )
                )
                if error is not None or value.value != f"ws://127.0.0.1:{bridge_port}":
                    continue
                state, error = await candidate._connection.send(
                    runtime.evaluate(
                        "({"
                        "restored: typeof restored === 'undefined' ? null : restored,"
                        "connecting: typeof connecting === 'undefined' ? null : connecting,"
                        "socketReadyState: typeof ws === 'undefined' || ws === null ? null : ws.readyState,"
                        "hasMainTab: typeof mainTabId !== 'undefined' && mainTabId !== null,"
                        "hasProfileIdentity: typeof profileId !== 'undefined' && profileId !== null,"
                        "hasSessionIdentity: typeof sessionId !== 'undefined' && sessionId !== null,"
                        "ownedTabCount: typeof autoTabs === 'undefined' ? null : autoTabs.size,"
                        "attachedTabCount: typeof attached === 'undefined' ? null : attached.size"
                        "})",
                        return_by_value=True,
                    )
                )
                states.append(
                    {
                        "state": state.value,
                        "evaluationError": str(error) if error else None,
                    }
                )
            finally:
                await candidate._connection.disconnect()
        return states
    finally:
        await browser.close()

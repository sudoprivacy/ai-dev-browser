"""The authoritative mode decision text, shared by Python and CLI help."""

GUIDANCE = """Mode choice:
    Use standalone/CDP for isolated automation. Use extension for the user's
    real Chrome/profile, existing logins, device-bound identity, or sites that
    need the actual browser environment. Exporting cookies or copying a profile
    cannot guarantee the same device identity. Pick the transport explicitly;
    a failed connection never switches transport or profile.

    Choose headless/headful from the task, user request, site compatibility and
    host capabilities. Keep the existing default: explicit headless wins over
    AI_DEV_BROWSER_HEADLESS, otherwise windowed. Background/no-window tasks use
    headless=True; visible local collaboration uses headless=False and the SAME
    browser and page state. On Linux, windowed Chrome requires DISPLAY or
    WAYLAND_DISPLAY. Reading help does not impose a headless policy on hosts.

    Window visibility and remote viewing are separate. A cloud headful Chrome
    does not appear on the user's computer; a headless Chrome can still supply
    page_screenshot/recording. ai_dev_browser.remote provides optional page-view
    and X11 window adapters (see docs/remote-views.md). The host supplies viewer
    authentication, target/control ownership and any tunnel or relay. A local
    visible browser alone does not provide cloud pairing.

    Extension connect requires Chrome running with the bridge installed/enabled
    in the intended profile. Connecting cannot change its headless state. To
    launch that configured profile use browser_start --transport extension with
    --user-data-dir and --profile-directory. Launch does not install extensions
    or add a remote debugging port. Headless extension startup is confirmed by
    an actual handshake; an unsupported combination fails without a CDP fallback.

    Keep session_id from start/connect. Pass --session-id to later page/input
    tools to bind the same browser/profile. browser_reconnect restores control
    of that identity without restarting or replaying input. Inspect page/server
    state after uncertain results before deciding whether another action is safe.
    browser_disconnect releases control; browser_stop closes an owned process;
    browser_restart is an explicit process-wide operation. External browser
    stop/restart requires allow_external=True and known process ownership.

    For human login or verification, explain what is needed through the agent's
    native question/options or normal conversation. When the host provides
    shared browser controls, ask the user to Take control, complete the step in
    that same browser/profile, and Return to AI when ready. A chat reply or
    option alone does not establish ownership. The host must acknowledge its
    tool pause/control barrier; prompts cannot replace it. Wait while human
    control is held and observe the current page before continuing. Never ask
    for passwords, cookies or verification codes in chat or switch browsers to
    bypass a human lease. Without host handoff controls, coordinate explicitly
    with the user and do not claim that tools have been paused automatically.
"""


def mode_guidance(function):
    function.__doc__ = function.__doc__.replace("{mode_guidance}", GUIDANCE)
    return function

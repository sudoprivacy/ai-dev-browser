"""Human-like behavior simulation.

Adds randomness to mouse movements, typing, and delays to mimic human behavior.
Uses Gaussian random walk + Bezier curves for natural mouse trajectories.
"""

import asyncio
import math
import random
from dataclasses import dataclass

from ai_dev_browser import cdp
from ._element import Element
from ._tab import Tab


# Optional: use oxymouse if available
try:
    from oxymouse import OxyMouse

    _HAS_OXYMOUSE = True
except ImportError:
    _HAS_OXYMOUSE = False


@dataclass
class HumanConfig:
    """Configuration for human-like behavior.

    All delays are in milliseconds unless otherwise noted.

    Default philosophy:
    - Features that are FREE (0ms cost) → enabled by default
    - Features that have cost → disabled by default, opt-in
    """

    # Mouse movement (cost: +50ms, default OFF)
    use_gaussian_path: bool = False  # Use nodriver's linear path by default
    mouse_duration: float = 0.05  # Duration in seconds (when gaussian enabled)
    mouse_duration_variance: float = 0.2  # +/- variance ratio
    mouse_smoothness: float = 2.0  # Gaussian smoothing factor
    mouse_randomness: float = 0.5  # Path randomness factor

    # Click offset (cost: FREE, default ON)
    click_offset_enabled: bool = True  # Random offset within element bounds
    click_offset_ratio: float = 0.2  # Max offset as ratio of element size (±20%)

    # Click timing (cost: +45ms, default OFF)
    click_hold_enabled: bool = False  # Use random hold time
    click_hold_min_ms: float = 30  # Min mouse button hold time (pro gamer level)
    click_hold_max_ms: float = 60  # Max mouse button hold time

    # Double-click (cost: +60ms, default OFF)
    double_click_humanize: bool = False  # Use random interval
    double_click_interval_min_ms: float = 40  # Min interval between clicks
    double_click_interval_max_ms: float = 80  # Max interval between clicks

    # Typing (cost: +350ms/10chars, default OFF)
    type_humanize: bool = False  # Add delays between keystrokes
    type_delay_min_ms: float = 25  # Min delay (~400 WPM)
    type_delay_max_ms: float = 45  # Max delay (~270 WPM)
    typo_enabled: bool = False  # Simulate typos + backspace
    typo_probability: float = 0.02  # Probability of typo per character

    # General delays between actions
    action_delay_min_ms: float = 10  # Min delay between actions
    action_delay_max_ms: float = 50  # Max delay between actions

    # Scroll (advanced, default OFF)
    scroll_easing_enabled: bool = False  # Use easing function for scroll
    scroll_overshoot_enabled: bool = False  # Overshoot + bounce back


# Global config
_config = HumanConfig()

# Track last mouse position per tab (keyed by tab's target_id)
_last_mouse_pos: dict[str, tuple[float, float]] = {}


def configure(**kwargs) -> HumanConfig:
    """Configure human-like behavior globally.

    Example:
        human.configure(
            use_gaussian_path=True,
            mouse_duration=0.1,
            click_offset_enabled=False,
        )
    """
    global _config
    for key, value in kwargs.items():
        if hasattr(_config, key):
            setattr(_config, key, value)
    return _config


def get_config() -> HumanConfig:
    """Get current configuration."""
    return _config


def _get_tab_id(tab: Tab) -> str:
    """Get unique identifier for a tab."""
    try:
        return str(tab.target.target_id)
    except AttributeError:
        # Fallback to object id
        return str(id(tab))


def _get_mouse_button(button: str) -> cdp.input_.MouseButton:
    """Convert button string to CDP MouseButton enum."""
    button_map = {
        "left": cdp.input_.MouseButton.LEFT,
        "right": cdp.input_.MouseButton.RIGHT,
        "middle": cdp.input_.MouseButton.MIDDLE,
        "none": cdp.input_.MouseButton.NONE,
    }
    return button_map.get(button.lower(), cdp.input_.MouseButton.LEFT)


def get_last_mouse_pos(tab: Tab) -> tuple[float, float]:
    """Get last known mouse position for a tab."""
    tab_id = _get_tab_id(tab)
    return _last_mouse_pos.get(tab_id, (0, 0))


def set_last_mouse_pos(tab: Tab, x: float, y: float) -> None:
    """Set last known mouse position for a tab."""
    tab_id = _get_tab_id(tab)
    _last_mouse_pos[tab_id] = (x, y)


# =============================================================================
# Built-in Gaussian Mouse Implementation (no external dependencies)
# =============================================================================


def _gaussian_random() -> float:
    """Generate a Gaussian random number using Box-Muller transform."""
    u1 = random.random()
    u2 = random.random()
    return math.sqrt(-2 * math.log(u1 + 1e-10)) * math.cos(2 * math.pi * u2)


def _random_walk(length: int, stddev: float) -> list[float]:
    """Generate a random walk path."""
    walk = []
    cumsum = 0.0
    for _ in range(length):
        cumsum += _gaussian_random() * stddev
        walk.append(cumsum)
    return walk


def _gaussian_smooth(data: list[float], sigma: float) -> list[float]:
    """Simple Gaussian smoothing (1D convolution approximation)."""
    if sigma <= 0 or len(data) < 3:
        return data

    window = max(3, int(sigma * 2) | 1)  # Ensure odd
    half = window // 2
    smoothed = []

    for i in range(len(data)):
        start = max(0, i - half)
        end = min(len(data), i + half + 1)
        smoothed.append(sum(data[start:end]) / (end - start))

    return smoothed


def _morph_distribution(
    data: list[float], target_mean: float, target_std: float
) -> list[float]:
    """Morph data to have target mean and std."""
    if not data:
        return data

    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / len(data)
    std = math.sqrt(variance) if variance > 0 else 1.0

    return [(x - mean) / std * target_std + target_mean for x in data]


def _bezier_quadratic(p0: float, p1: float, p2: float, t: float) -> float:
    """Quadratic Bezier curve point."""
    return (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2


def generate_gaussian_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.05,
    smoothness: float = 2.0,
    randomness: float = 0.5,
) -> list[tuple[int, int]]:
    """Generate human-like mouse path using Gaussian random walk + Bezier.

    This combines:
    1. A Bezier curve as the base trajectory
    2. Gaussian random walk noise for natural deviation
    3. Smoothing to avoid jerky movements

    Args:
        start_x, start_y: Starting position
        end_x, end_y: Target position
        duration: Movement duration in seconds
        smoothness: Higher = smoother path
        randomness: Higher = more deviation from straight line

    Returns:
        List of (x, y) coordinates
    """
    num_points = max(6, int(duration * 60))  # 60 fps, min 6 points

    # Generate Gaussian random walk
    stddev = randomness * 10
    random_x = _random_walk(num_points, stddev)
    random_y = _random_walk(num_points, stddev)

    # Smooth the random walk
    smooth_x = _gaussian_smooth(random_x, sigma=smoothness)
    smooth_y = _gaussian_smooth(random_y, sigma=smoothness)

    # Morph to fit path scale
    dx = end_x - start_x
    dy = end_y - start_y
    human_mean_x, human_std_x = dx / 2, max(abs(dx) / 6, 5)
    human_mean_y, human_std_y = dy / 2, max(abs(dy) / 6, 5)

    morphed_x = _morph_distribution(smooth_x, human_mean_x, human_std_x)
    morphed_y = _morph_distribution(smooth_y, human_mean_y, human_std_y)

    # Generate Bezier base curve with random control point
    control_x = random.uniform(min(start_x, end_x), max(start_x, end_x))
    control_y = random.uniform(min(start_y, end_y), max(start_y, end_y))

    # Combine Bezier + noise
    path = []
    for i in range(num_points):
        t = i / (num_points - 1) if num_points > 1 else 1.0
        bx = _bezier_quadratic(start_x, control_x, end_x, t)
        by = _bezier_quadratic(start_y, control_y, end_y, t)
        path.append((int(bx + morphed_x[i]), int(by + morphed_y[i])))

    # Ensure exact start and end
    path[0] = (start_x, start_y)
    path[-1] = (end_x, end_y)

    return path


# =============================================================================
# Click Offset Helpers
# =============================================================================


def calculate_click_offset(
    width: float, height: float, ratio: float = None
) -> tuple[float, float]:
    """Calculate random offset within element bounds.

    Args:
        width: Element width
        height: Element height
        ratio: Max offset ratio (default from config)

    Returns:
        (offset_x, offset_y) tuple
    """
    if ratio is None:
        ratio = _config.click_offset_ratio

    max_offset_x = width * ratio
    max_offset_y = height * ratio

    offset_x = random.uniform(-max_offset_x, max_offset_x)
    offset_y = random.uniform(-max_offset_y, max_offset_y)

    return (offset_x, offset_y)


# =============================================================================
# Public API
# =============================================================================


async def delay(min_ms: float = None, max_ms: float = None) -> None:
    """Random delay between actions."""
    min_ms = min_ms if min_ms is not None else _config.action_delay_min_ms
    max_ms = max_ms if max_ms is not None else _config.action_delay_max_ms
    if max_ms > 0:
        await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


async def mouse_move(
    tab: Tab,
    x: float,
    y: float,
    from_x: float = None,
    from_y: float = None,
    duration: float = None,
    use_gaussian: bool = None,
) -> None:
    """Move mouse to target position.

    Args:
        tab: Browser tab
        x: Target X coordinate
        y: Target Y coordinate
        from_x: Starting X (default: last known position)
        from_y: Starting Y (default: last known position)
        duration: Movement duration for gaussian (default: from config)
        use_gaussian: Use gaussian path (default: from config)
    """
    # Get starting position from last known or default
    if from_x is None or from_y is None:
        last_pos = get_last_mouse_pos(tab)
        from_x = from_x if from_x is not None else last_pos[0]
        from_y = from_y if from_y is not None else last_pos[1]

    # Determine whether to use gaussian
    if use_gaussian is None:
        use_gaussian = _config.use_gaussian_path

    if use_gaussian:
        # Calculate duration with variance
        if duration is None:
            base = _config.mouse_duration
            variance = _config.mouse_duration_variance
            duration = base * random.uniform(1 - variance, 1 + variance)

        # Generate path
        if _HAS_OXYMOUSE:
            mouse = OxyMouse(algorithm="gaussian")
            path = mouse.generate_coordinates(
                from_x=int(from_x), from_y=int(from_y), to_x=int(x), to_y=int(y)
            )
        else:
            path = generate_gaussian_path(
                int(from_x),
                int(from_y),
                int(x),
                int(y),
                duration=duration,
                smoothness=_config.mouse_smoothness,
                randomness=_config.mouse_randomness,
            )

        # Send mouse events with timing
        delay_per_point = duration / len(path) if path else 0
        for point in path:
            await tab.send(
                cdp.input_.dispatch_mouse_event("mouseMoved", x=point[0], y=point[1])
            )
            if delay_per_point > 0:
                await asyncio.sleep(delay_per_point)
    else:
        # Use nodriver's built-in linear movement
        await tab.mouse_move(x, y, steps=10)

    # Update last position
    set_last_mouse_pos(tab, x, y)


async def mouse_click(
    tab: Tab,
    x: float,
    y: float,
    button: str = "left",
    move_first: bool = True,
    from_x: float = None,
    from_y: float = None,
) -> None:
    """Click with optional human-like timing.

    Args:
        tab: Browser tab
        x: Click X coordinate
        y: Click Y coordinate
        button: Mouse button ("left", "right", "middle")
        move_first: Whether to move mouse before clicking
        from_x: Starting X for movement
        from_y: Starting Y for movement
    """
    if move_first:
        await mouse_move(tab, x, y, from_x=from_x, from_y=from_y)

    btn = _get_mouse_button(button)

    # Press
    await tab.send(
        cdp.input_.dispatch_mouse_event(
            "mousePressed", x=x, y=y, button=btn, click_count=1
        )
    )

    # Optional: random hold time (if enabled)
    if _config.click_hold_enabled:
        hold_ms = random.uniform(_config.click_hold_min_ms, _config.click_hold_max_ms)
        await asyncio.sleep(hold_ms / 1000)

    # Release
    await tab.send(
        cdp.input_.dispatch_mouse_event(
            "mouseReleased", x=x, y=y, button=btn, click_count=1
        )
    )


async def mouse_double_click(
    tab: Tab,
    x: float,
    y: float,
    button: str = "left",
    move_first: bool = True,
    from_x: float = None,
    from_y: float = None,
) -> None:
    """Double-click with optional human-like timing.

    Args:
        tab: Browser tab
        x: Click X coordinate
        y: Click Y coordinate
        button: Mouse button
        move_first: Whether to move mouse before clicking
        from_x: Starting X for movement
        from_y: Starting Y for movement
    """
    if move_first:
        await mouse_move(tab, x, y, from_x=from_x, from_y=from_y)

    btn = _get_mouse_button(button)

    # First click
    await tab.send(
        cdp.input_.dispatch_mouse_event(
            "mousePressed", x=x, y=y, button=btn, click_count=1
        )
    )
    if _config.click_hold_enabled:
        hold_ms = random.uniform(_config.click_hold_min_ms, _config.click_hold_max_ms)
        await asyncio.sleep(hold_ms / 1000)
    await tab.send(
        cdp.input_.dispatch_mouse_event(
            "mouseReleased", x=x, y=y, button=btn, click_count=1
        )
    )

    # Interval between clicks (random if humanized, else minimal)
    if _config.double_click_humanize:
        interval_ms = random.uniform(
            _config.double_click_interval_min_ms,
            _config.double_click_interval_max_ms,
        )
        await asyncio.sleep(interval_ms / 1000)

    # Second click
    await tab.send(
        cdp.input_.dispatch_mouse_event(
            "mousePressed", x=x, y=y, button=btn, click_count=2
        )
    )
    if _config.click_hold_enabled:
        hold_ms = random.uniform(_config.click_hold_min_ms, _config.click_hold_max_ms)
        await asyncio.sleep(hold_ms / 1000)
    await tab.send(
        cdp.input_.dispatch_mouse_event(
            "mouseReleased", x=x, y=y, button=btn, click_count=2
        )
    )


async def type_text(
    tab: Tab,
    text: str,
    element: Element = None,
    humanize: bool = None,
) -> None:
    """Type text with optional human-like timing.

    Args:
        tab: Browser tab
        text: Text to type
        element: Optional element to focus first
        humanize: Add delays between keystrokes (default: from config)
    """
    if element:
        await element.apply("(elem) => elem.focus()")

    # Determine whether to use human-like delays
    use_delays = humanize if humanize is not None else _config.type_humanize

    for char in text:
        # Simulate typo if enabled (only when humanizing)
        if (
            use_delays
            and _config.typo_enabled
            and random.random() < _config.typo_probability
        ):
            # Type wrong char then backspace
            wrong_char = chr(ord(char) + random.choice([-1, 1]))
            await tab.send(cdp.input_.dispatch_key_event("char", text=wrong_char))
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await tab.send(
                cdp.input_.dispatch_key_event(
                    "rawKeyDown", key="Backspace", windows_virtual_key_code=8
                )
            )
            await tab.send(
                cdp.input_.dispatch_key_event(
                    "keyUp", key="Backspace", windows_virtual_key_code=8
                )
            )
            await asyncio.sleep(random.uniform(0.05, 0.15))

        # Random delay between keystrokes (if humanized)
        if use_delays:
            delay_ms = random.uniform(
                _config.type_delay_min_ms,
                _config.type_delay_max_ms,
            )
            await asyncio.sleep(delay_ms / 1000)

        # Type character
        await tab.send(cdp.input_.dispatch_key_event("char", text=char))


async def click_element(
    tab: Tab,
    element: Element,
    from_x: float = None,
    from_y: float = None,
    use_offset: bool = None,
) -> None:
    """Click element with human-like behavior.

    Args:
        tab: Browser tab
        element: Element to click
        from_x: Starting X for mouse movement
        from_y: Starting Y for mouse movement
        use_offset: Apply random offset within element (default: from config)
    """
    try:
        pos = await element.get_position()
        center = pos.center
        width = pos.width
        height = pos.height
    except (AttributeError, Exception):
        # Fallback to regular click
        await element.click()
        return

    # Apply offset if enabled
    if use_offset is None:
        use_offset = _config.click_offset_enabled

    x, y = center[0], center[1]
    if use_offset and width > 0 and height > 0:
        offset_x, offset_y = calculate_click_offset(width, height)
        x += offset_x
        y += offset_y

    await mouse_click(tab, x, y, from_x=from_x, from_y=from_y)


async def double_click_element(
    tab: Tab,
    element: Element,
    from_x: float = None,
    from_y: float = None,
    use_offset: bool = None,
) -> None:
    """Double-click element with human-like behavior.

    Args:
        tab: Browser tab
        element: Element to double-click
        from_x: Starting X for mouse movement
        from_y: Starting Y for mouse movement
        use_offset: Apply random offset within element (default: from config)
    """
    try:
        pos = await element.get_position()
        center = pos.center
        width = pos.width
        height = pos.height
    except (AttributeError, Exception):
        # Fallback to regular click twice
        await element.click()
        await asyncio.sleep(0.1)
        await element.click()
        return

    # Apply offset if enabled
    if use_offset is None:
        use_offset = _config.click_offset_enabled

    x, y = center[0], center[1]
    if use_offset and width > 0 and height > 0:
        offset_x, offset_y = calculate_click_offset(width, height)
        x += offset_x
        y += offset_y

    await mouse_double_click(tab, x, y, from_x=from_x, from_y=from_y)

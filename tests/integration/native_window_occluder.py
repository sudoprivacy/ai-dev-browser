"""Physically cover only a verified test Chrome window; never send OS input."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes


def windows_api():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    return user


def owned_window(pid, title):
    """Find a fixture window by both process and neutral-page title."""
    user = windows_api()
    matches = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback
    def visit(handle, unused):
        process = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(process))
        text = ctypes.create_unicode_buffer(1024)
        user.GetWindowTextW(handle, text, len(text))
        if process.value == pid and title in text.value:
            matches.append(handle)
        return True

    user.EnumWindows(visit, 0)
    assert len(matches) == 1, (pid, title, len(matches))
    return matches[0]


@contextmanager
def visible_owned_window(pid, title):
    """Fixture setup equivalent to showing the neutral window, with no input."""
    user = windows_api()
    handle = owned_window(pid, title)
    topmost = bool(user.GetWindowLongW(handle, -20) & 8)
    assert user.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x53)
    try:
        yield handle
    finally:
        if not topmost:
            user.SetWindowPos(handle, -2, 0, 0, 0, 0, 0x13)


@contextmanager
def cover_with_fixture_window(pid, handle, title):
    """A second real Chrome window physically occludes the neutral form."""
    user = windows_api()
    overlay = owned_window(pid, title)
    rect = wintypes.RECT()
    assert user.GetWindowRect(handle, ctypes.byref(rect))
    original = wintypes.RECT()
    assert user.GetWindowRect(overlay, ctypes.byref(original))
    topmost = bool(user.GetWindowLongW(overlay, -20) & 8)
    # All native changes are confined to this fixture PID. Keeping the cover
    # above a normal Chrome window produces genuine OS occlusion, even when
    # the selected browser window reports focused=true.
    assert user.SetWindowPos(handle, -2, 0, 0, 0, 0, 0x13)
    assert user.SetWindowPos(
        overlay,
        -1,
        rect.left - 16,
        rect.top - 16,
        rect.right - rect.left + 32,
        rect.bottom - rect.top + 32,
        0x50,
    )
    try:
        yield
    finally:
        user.SetWindowPos(
            overlay,
            -1 if topmost else -2,
            original.left,
            original.top,
            original.right - original.left,
            original.bottom - original.top,
            0x10,
        )
        user.SetWindowPos(handle, -1, 0, 0, 0, 0, 0x13)

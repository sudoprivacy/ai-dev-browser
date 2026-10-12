"""Run native UI Automation on its own main thread/COM lifetime."""

import argparse
from pathlib import Path

from .browser_lifecycle_support import owned_folder_picker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--confirm-pid", type=int)
    parser.add_argument("--minimize-pid", type=int)
    args = parser.parse_args()
    if args.confirm_pid or args.minimize_pid:
        from pywinauto import Desktop

        window = Desktop(backend="uia").window(
            process=args.confirm_pid or args.minimize_pid,
            title_re="Browser lifecycle acceptance.*",
        )
        if args.minimize_pid:
            window.wait("exists", timeout=15)
            window.minimize()
            return
        window.wait("visible", timeout=15)
        window.set_focus()
        button = window.child_window(title="Confirm as user", control_type="Button")
        button.wait("visible", timeout=15)
        button.wrapper_object().click_input()
    else:
        assert args.profile and args.extension
        owned_folder_picker(args.profile, args.extension)


if __name__ == "__main__":
    main()

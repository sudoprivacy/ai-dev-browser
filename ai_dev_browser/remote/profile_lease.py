"""Exclusive ownership of a host-managed persistent browser volume."""

import os
import pathlib
from contextlib import ExitStack, contextmanager

from ai_dev_browser.core._session import profile_processes


@contextmanager
def _lock_file(root):
    with pathlib.Path(root).joinpath(".worker.lock").open("a+b") as file:
        yield file


class ProfileLease:
    """Hold a volume lock until Chrome exits, including across containers.

    The host supplies this directory; it never comes from an agent or viewer.
    All workers for the volume must acquire this lease before launching Chrome.
    The lock file stays in place so contenders always lock the same inode.
    """

    def __init__(self, root):
        self._resources = ExitStack()
        self.file = self._resources.enter_context(_lock_file(root))
        try:
            if os.name == "nt":
                import msvcrt

                if self.file.tell() == 0:
                    self.file.write(b"\0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._resources.close()
            raise RuntimeError("managed_browser_profile_already_owned") from None

    def prepare(self, profile):
        """Recover Chrome's stale singleton links under exclusive ownership."""
        profile = pathlib.Path(profile)
        if profile_processes(profile):
            raise RuntimeError("managed_browser_profile_process_still_running")
        if os.name != "nt":
            for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
                link = profile / name
                # Never follow the links or delete any profile data. Chrome's
                # links can name an old container hostname after a hard stop.
                if link.is_symlink():
                    link.unlink()

    def close(self):
        self._resources.close()

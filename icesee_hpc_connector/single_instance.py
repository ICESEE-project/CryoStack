"""Best-effort single-instance guard for the CryoStack Connector.

A second launch should not spawn a second menu-bar app + worker (two connectors
racing the same relay session, confusing status). It acquires an advisory lock
on ``~/.cryostack/connector.lock``; if it cannot, the caller shows a friendly
message and exits. No process is ever killed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_LOCK_PATH = Path.home() / ".cryostack" / "connector.lock"


class SingleInstance:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else _LOCK_PATH
        self.acquired = False
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle = open(self.path, "a+")
                try:
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self._handle.close()
                    self._handle = None
                    return False
            else:
                import fcntl

                self._handle = open(self.path, "a+")
                try:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self._handle.close()
                    self._handle = None
                    return False
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(str(os.getpid()))
            self._handle.flush()
            self.acquired = True
            return True
        except Exception:
            # If locking is unavailable, do not block startup.
            self.acquired = True
            return True

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if sys.platform != "win32":
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._handle.close()
        except Exception:
            pass
        self._handle = None
        self.acquired = False

    def __enter__(self) -> "SingleInstance":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()

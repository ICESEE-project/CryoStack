"""CryoStack-wide workspace quota and host-capacity guard.

The quota database predates this shared module and remains import-compatible
with Frozen Legacies.  Accounting is deliberately performed at the owner
root, so one allowance covers every application directory for that account.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from icesee_jupyter_book.applications.frozen_legacies.radar import quota

QuotaExceeded = quota.QuotaExceeded


_lock = Lock()
_store = None
_accounts = None
_path = None


def policy():
    global _store, _accounts, _path
    path = quota.storage_db_path()
    with _lock:
        if _store is None or _path != path:
            _store = quota.QuotaStore(path)
            _accounts = quota.QuotaAccounts(_store)
            _path = path
    return _store, _accounts


def usage(owner_root: Path, user_id: str, *, refresh: bool = False):
    _store, accounts = policy()
    return accounts.usage(Path(owner_root), str(user_id), refresh=refresh)


@contextmanager
def workspace_write(owner_root: Path, user_id: str, incoming: int = 0,
                    *, what: str = "writing workspace files", replacing: Path | None = None):
    """Serialize a controlled write and reserve its fresh net growth.

    Replacement sizes are measured while the owner lock is held through the
    write. The disk guard includes the complete temporary replacement bytes.
    Only an existing, non-growing file can be replaced while over quota.
    """
    _store, accounts = policy()
    root = Path(owner_root)
    with quota._owner_write_lock(_store, root):
        current = accounts.usage(root, str(user_id))
        incoming = max(0, int(incoming))
        growth, non_growing, disk_bytes = incoming, False, None
        if replacing is not None:
            target = Path(replacing)
            if not target.resolve().is_relative_to(root.resolve()):
                raise ValueError("Replacement escaped its owner's workspace.")
            previous = target.stat().st_size if target.is_file() else 0
            growth = max(0, incoming - previous)
            non_growing = target.is_file() and incoming <= previous
            disk_bytes = incoming
        reserved = accounts.reserve(current, root, growth, what=what,
                                    allow_non_growing=non_growing, disk_bytes=disk_bytes)
        try:
            yield current
        finally:
            accounts.release(root, reserved)


def check_workspace_write(owner_root: Path, user_id: str, incoming: int = 0,
                          *, what: str = "starting this operation"):
    """Check a future/background write without holding an in-process reserve."""
    with workspace_write(owner_root, user_id, incoming, what=what) as current:
        return current

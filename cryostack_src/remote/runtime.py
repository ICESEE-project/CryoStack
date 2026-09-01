from __future__ import annotations


class RemoteConfigError(ValueError):
    """A required remote-execution setting was not configured.

    Raised instead of silently substituting a developer/service default (e.g. a
    hard-coded home or project directory).
    """


def require_remote_base_dir(value: str | None) -> str:
    """Return the stripped remote working directory, or fail closed.

    There is no safe default: it is the user's own directory on the resource.
    An empty value is a configuration error, never an excuse to fall back to
    someone else's path.
    """
    v = (value or "").strip()
    if not v:
        raise RemoteConfigError(
            "Remote working directory is not configured. Enter it in "
            "Remote Connection before running a job."
        )
    return v


def expand_remote_home(path: str | None) -> str:
    if path is None:
        return ""
    path = str(path).strip()
    return path or ""


def normalize_remote_path(path: str | None) -> str:
    path = expand_remote_home(path)
    if not path:
        return ""
    while "//" in path:
        path = path.replace("//", "/")
    return path

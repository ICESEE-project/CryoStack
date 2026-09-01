"""B3: user x resource x HPC-identity SSH credential namespace (server side).

The audit found the server-side SSH Key Manager namespaced only by cluster
name (``~/.ssh/id_ed25519_icesee_<cluster>``). If the Voila process runs under
one shared Unix service account, that is NOT per-user isolation -- two
CryoStack users configuring the same resource would get the same key file.

:func:`credential_namespace` folds every identity dimension that is actually
known (CryoStack user, resource, HPC username) into one collision-resistant,
filesystem-safe key. Raw strings are never used directly in a path.

Migration: :func:`legacy_cluster_key_paths` names the OLD cluster-only key for
display/audit only. It is never read or adopted automatically by this module --
see the callers for the explicit, logged migration behaviour.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_KEY_TYPE = "ed25519"


def _slug(text: str, limit: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:limit] or "resource"


def credential_namespace(
    *,
    cryostack_user_id: str = "",
    resource_id: str = "",
    hpc_username: str = "",
) -> str:
    """A stable, safe key namespace combining whatever identity dimensions are
    available. Different (user, resource, hpc_username) tuples always produce
    different namespaces; the same tuple always produces the same one.
    """
    parts = [p.strip() for p in (cryostack_user_id, resource_id, hpc_username) if p and p.strip()]
    if not parts:
        return "unscoped"
    joined = "|".join(p.lower() for p in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    readable = "-".join(_slug(p, 16) for p in parts[:2])
    return f"{readable}-{digest}"


def cryostack_key_paths(namespace: str, *, ssh_dir: Path | None = None) -> tuple[Path, Path]:
    """The (private, public) paths for a namespaced CryoStack credential."""
    base = ssh_dir or (Path.home() / ".ssh" / "cryostack")
    priv = base / f"id_{_KEY_TYPE}_{namespace}"
    return priv, Path(str(priv) + ".pub")


def legacy_cluster_key_paths(cluster_name: str, *, ssh_dir: Path | None = None) -> tuple[Path, Path]:
    """The OLD cluster-only key location -- for migration/audit display only.
    Never read or copied automatically."""
    base = ssh_dir or (Path.home() / ".ssh")
    safe = re.sub(r"[^a-z0-9._-]+", "_", (cluster_name or "").strip().lower()).strip("_") or "cluster"
    priv = base / f"id_{_KEY_TYPE}_icesee_{safe}"
    return priv, Path(str(priv) + ".pub")

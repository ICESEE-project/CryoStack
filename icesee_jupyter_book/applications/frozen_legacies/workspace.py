"""Per-user Frozen Legacies workspace.

Frozen Legacies keeps its user-owned radar work inside the standard CryoStack
per-user workspace (``cryostack_src.workspace``), in an application-scoped
subtree so it never mixes with CryoLauncher or ICESEE files::

    <owner_root>/frozen_legacies/
        radar/
            <asset_id>/
                asset.json
                source.tiff
                nav.csv
                session.json        (manual picking)
                automatic.json      (automatic picking job)
                products.json       (registered products)
                outputs/

``<owner_root>`` is ``owner_root(user)`` -- the same ``users/<safe_id>``
directory CryoLauncher and ICESEE use for the same CryoStack account.

Rules:

* the owning identity is always the authenticated CryoStack user resolved by
  the gateway (``request["cryostack_user"]``), never a browser-supplied value;
* asset IDs are generated here, never chosen by the browser, and are
  validated before any filesystem access;
* the browser never supplies filesystem paths; every path this module returns
  is resolved and verified to remain inside this user's Frozen Legacies root.

Shared/reference Frozen Legacies data (manifests, catalog, published radar
assets) is not stored here.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from cryostack_src.workspace.identity import (
    WorkspaceIdentityError,
    WorkspaceUser,
)
from cryostack_src.workspace.manager import WorkspacePermissionError
from cryostack_src.workspace.roots import owner_root


#: application-scoped directory under <owner_root>
APPLICATION_DIRNAME = "frozen_legacies"

#: radar assets directory under the application directory
RADAR_DIRNAME = "radar"

#: per-asset layout -- the only names an asset directory may contain
ASSET_MANIFEST = "asset.json"
ASSET_SOURCE_TIFF = "source.tiff"
ASSET_NAV_CSV = "nav.csv"
ASSET_SESSION = "session.json"
ASSET_AUTOMATIC = "automatic.json"
ASSET_PRODUCTS = "products.json"
ASSET_OBSERVATIONS = "observations.json"
ASSET_OUTPUTS = "outputs"

ASSET_FILES = frozenset({
    ASSET_MANIFEST,
    ASSET_SOURCE_TIFF,
    ASSET_NAV_CSV,
    ASSET_SESSION,
    ASSET_AUTOMATIC,
    ASSET_PRODUCTS,
    ASSET_OBSERVATIONS,
})

#: server-generated asset IDs: uuid4().hex
_ASSET_ID = re.compile(r"[0-9a-f]{32}")

#: output filenames: one plain segment, no leading dot
_OUTPUT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")


class AssetNotFoundError(LookupError):
    """No asset with this ID exists in the current user's workspace."""


def new_asset_id() -> str:
    """Return a new server-generated asset ID."""
    return uuid.uuid4().hex


def is_valid_asset_id(value: object) -> bool:
    return isinstance(value, str) and _ASSET_ID.fullmatch(value) is not None


def workspace_user_for(user) -> WorkspaceUser:
    """The ``WorkspaceUser`` for an authenticated ``icesee_auth`` user.

    Produces the same identity (and therefore the same ``safe_id``) that the
    Voila applications derive from the proxy-injected
    ``X-CryoStack-User-Id`` header.
    """
    user_id = str(getattr(user, "id", "") or "").strip()
    if not user_id:
        raise WorkspaceIdentityError(
            "Workspace unavailable: authenticated CryoStack identity was not provided."
        )
    return WorkspaceUser(
        user_id=user_id,
        display_name=str(getattr(user, "display_name", "") or ""),
        source="cryostack-auth",
    )


class FrozenLegaciesWorkspace:
    """One authenticated user's Frozen Legacies workspace."""

    def __init__(
        self,
        user: WorkspaceUser,
        *,
        workspace_root: str | Path | None = None,
    ) -> None:
        if not user.is_authenticated:
            raise WorkspaceIdentityError(
                "Workspace unavailable: authenticated CryoStack identity was not provided."
            )
        self.user = user
        self._owner_root = owner_root(user, workspace_root=workspace_root)
        self.root = (self._owner_root / APPLICATION_DIRNAME).resolve()
        self.radar_root = (self.root / RADAR_DIRNAME).resolve()
        if not self.radar_root.is_relative_to(self._owner_root):
            raise WorkspacePermissionError(
                "Frozen Legacies workspace escaped its user root."
            )

    # -- containment -----------------------------------------------------
    def contain(self, path: str | Path) -> Path:
        """Resolve ``path`` and require it to stay inside this workspace.

        Resolution follows symlinks, so a link pointing outside the
        workspace is rejected as well.
        """
        try:
            resolved = Path(path).resolve()
        except (OSError, RuntimeError):
            raise WorkspacePermissionError(f"Cannot resolve path: {path!r}")
        if not resolved.is_relative_to(self.root):
            raise WorkspacePermissionError(
                "Path is outside your Frozen Legacies workspace."
            )
        return resolved

    def ensure(self) -> Path:
        """Create the workspace directories if they do not exist yet."""
        self.radar_root.mkdir(parents=True, exist_ok=True)
        self.contain(self.radar_root)
        return self.root

    # -- radar assets ----------------------------------------------------
    def _asset_dir(self, asset_id: str) -> Path:
        if not is_valid_asset_id(asset_id):
            raise WorkspacePermissionError(f"Invalid asset ID: {asset_id!r}")
        path = self.contain(self.radar_root / asset_id)
        if path.parent != self.radar_root:
            raise WorkspacePermissionError(f"Invalid asset ID: {asset_id!r}")
        return path

    def create_asset(self) -> tuple[str, Path]:
        """Create a new, empty radar asset directory; return ``(id, path)``."""
        self.ensure()
        asset_id = new_asset_id()
        path = self._asset_dir(asset_id)
        path.mkdir(exist_ok=False)
        (path / ASSET_OUTPUTS).mkdir()
        return asset_id, path

    def asset_dir(self, asset_id: str) -> Path:
        """The directory of an existing asset owned by this user."""
        path = self._asset_dir(asset_id)
        if not path.is_dir():
            raise AssetNotFoundError(asset_id)
        return path

    def asset_file(self, asset_id: str, name: str) -> Path:
        """Path of one fixed-layout file (``asset.json``, ``source.tiff``,
        ``nav.csv``, ``session.json``) of an existing asset."""
        if name not in ASSET_FILES:
            raise WorkspacePermissionError(f"Not an asset file: {name!r}")
        return self.contain(self.asset_dir(asset_id) / name)

    def output_file(self, asset_id: str, filename: str) -> Path:
        """Path of a generated product under an asset's ``outputs/``."""
        if not isinstance(filename, str) or not _OUTPUT_NAME.fullmatch(filename):
            raise WorkspacePermissionError(f"Unsafe output filename: {filename!r}")
        outputs = self.contain(self.asset_dir(asset_id) / ASSET_OUTPUTS)
        path = self.contain(outputs / filename)
        if path.parent != outputs:
            raise WorkspacePermissionError(f"Unsafe output filename: {filename!r}")
        return path

    def list_asset_ids(self) -> list[str]:
        """IDs of this user's radar assets (never another user's)."""
        if not self.radar_root.is_dir():
            return []
        ids = []
        for entry in sorted(self.radar_root.iterdir()):
            if not is_valid_asset_id(entry.name) or entry.is_symlink():
                continue
            if entry.is_dir():
                ids.append(entry.name)
        return ids

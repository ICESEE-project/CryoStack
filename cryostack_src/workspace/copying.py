"""Content copies for service-managed SMB workspaces with forced permissions.

The SMB proxy accepts file bytes but may reject chmod/utime/copystat. Copies
inside the configured, verified workspace mount use file contents; that mount
controls destination permissions. Local destinations retain copy2/copytree.
The explicit content-only flag remains available for other deployments.
"""
import os
from pathlib import Path
import shutil
import stat


def content_only(destination=None) -> bool:
    explicit = os.environ.get("CRYOSTACK_WORKSPACE_CONTENT_ONLY", "").strip()
    if explicit:
        return explicit == "1"
    if destination is None:
        return False
    from .storage_mount import MOUNT_ENV, require_workspace_storage
    configured = os.environ.get(MOUNT_ENV, "").strip()
    if not configured:
        return False
    target = Path(destination).expanduser().absolute()
    mount = Path(configured).expanduser().absolute()
    if not (target.is_relative_to(mount)
            or target.resolve().is_relative_to(mount.resolve())):
        return False
    # Do not turn a failed/missing mount into an ordinary local copy. The
    # same mount/volume identity gate used by WorkspaceManager stays in force.
    require_workspace_storage(target)
    return True


def copy_workspace_file(source, destination):
    if content_only(destination):
        return shutil.copyfile(source, destination)
    return shutil.copy2(source, destination)


def copy_workspace_tree(source, destination):
    if not content_only(destination):
        return shutil.copytree(source, destination)
    source, destination = Path(source), Path(destination)
    # Preflight the complete tree before copying. SMB does not support the
    # source symlink semantics; never silently follow links outside the tree.
    entries=[]
    for directory, dirs, files in os.walk(source, followlinks=False):
        for name in [*dirs, *files]:
            path=Path(directory)/name
            mode=path.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("Workspace content copies require regular files and directories; symbolic links and special files are unsupported.")
            entries.append((path,stat.S_ISDIR(mode)))
    destination.mkdir(parents=True,exist_ok=False)
    for path,is_dir in entries:
        target=destination/path.relative_to(source)
        if is_dir: target.mkdir(parents=True,exist_ok=True)
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            copy_workspace_file(path,target)
    return str(destination)


def workspace_copy_size(source):
    """Bound quota admission by the files copytree would actually transport."""
    source=Path(source)
    if source.is_file():return source.stat().st_size
    total=0;seen=set()
    for directory,dirs,files in os.walk(source,followlinks=True):
        info=Path(directory).stat();identity=(info.st_dev,info.st_ino)
        if identity in seen:raise ValueError("Cyclic or repeated directory links are unsupported in workspace copies")
        seen.add(identity)
        for name in files:
            path=Path(directory)/name
            info=path.stat()
            if not stat.S_ISREG(info.st_mode):raise ValueError("Only regular workspace files can be copied")
            total+=info.st_size
    return total

"""Quota-admitted, atomic result bundles and bounded inline browser delivery."""
from __future__ import annotations

from pathlib import Path
import os
import stat
import tempfile
import zipfile

# A base64 notebook link needs several copies in the kernel/browser. Large-result
# streaming requires a gateway transfer route; never grow an inline link without
# a bound merely because an owner's disk allowance is larger.
INLINE_ARCHIVE_LIMIT = 32 * 1024 * 1024
STREAM_ARCHIVE_LIMIT = 1024 * 1024 * 1024
ARCHIVE_ENTRY_LIMIT = 10000


class UnsafeArchiveError(ValueError):
    pass


class ArchiveLimitError(ValueError):
    pass


def archive_entries(source: Path, *, figures_only=False):
    source=Path(source)
    if source.is_symlink() or not source.is_dir():
        raise UnsafeArchiveError('Result archives require an ordinary output directory.')
    entries=[]
    count=0
    for path in source.rglob('*'):
        count+=1
        if count>ARCHIVE_ENTRY_LIMIT:
            raise ArchiveLimitError('This output has too many entries for a pilot browser archive. Files are retained; ask the organizers for a large-result transfer.')
        mode=path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise UnsafeArchiveError('Result archives require regular files and directories; links and special files are not included.')
        if stat.S_ISREG(mode) and (not figures_only or path.suffix.lower() in ('.png','.jpg','.jpeg')):
            entries.append(path)
    return sorted(entries)


def write_zip(source, destination, *, figures_only=False):
    source=Path(source)
    entries=archive_entries(source,figures_only=figures_only)
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in entries:
            archive.write(path,arcname=path.relative_to(source))


class _BoundedWriter:
    def __init__(self,stream,limit):
        self.stream,self.limit=stream,limit
    def __getattr__(self,name):
        return getattr(self.stream,name)
    def write(self,data):
        if self.stream.tell()+len(data)>self.limit:
            raise ArchiveLimitError('This bundle exceeds its admitted transfer size. Files and the previous bundle are retained; ask the organizers for a large-result transfer.')
        return self.stream.write(data)


def prepare_archive(source, target, *, owner_root, user_id, zip_writer, figures_only=False):
    """Create beside the destination, admit all temporary bytes, then replace.

    The conservative hold is capped at the inline limit and enforced by the
    writer. Even unexpectedly growing/incompressible sources cannot write past
    that hold. A failed rebuild leaves the previous completed bundle intact.
    """
    from .storage_policy import workspace_write
    from .storage_mount import require_workspace_storage
    root=Path(owner_root).resolve()
    source,target=Path(source),Path(target)
    if source.is_symlink() or not source.resolve().is_relative_to(root):
        raise UnsafeArchiveError('Outputs must belong to the current workspace.')
    if target.is_symlink() or not target.resolve().is_relative_to(root):
        raise UnsafeArchiveError('Archive destination must belong to the current workspace.')
    if target.resolve().is_relative_to(source.resolve()):
        raise UnsafeArchiveError('Archive destination must be outside its output tree.')
    require_workspace_storage(root)
    files=archive_entries(source,figures_only=figures_only)
    if not files:
        raise ValueError('No output files to package.')
    # This is an admission estimate, not an assumed compression guarantee. The
    # bounded writer fails closed if ZIP metadata/compressed bytes exceed it.
    estimate=sum(p.stat().st_size+p.stat().st_size//100+len(str(p.relative_to(source)).encode('utf-8'))*2+1024 for p in files)+65536
    from .downloads import download_url
    limit=STREAM_ARCHIVE_LIMIT if download_url(target) else INLINE_ARCHIVE_LIMIT
    allowance=min(limit,estimate)
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with workspace_write(root,user_id,allowance,what='packaging result downloads',replacing=target):
            descriptor,name=tempfile.mkstemp(prefix='._result-archive-',suffix='.zip',dir=target.parent)
            temporary=Path(name)
            with os.fdopen(descriptor,'w+b') as stream:
                zip_writer(source,_BoundedWriter(stream,allowance),figures_only=figures_only)
                stream.flush()
                os.fsync(stream.fileno())
            if not zipfile.is_zipfile(temporary):
                raise ValueError('Created result bundle is not a valid ZIP archive.')
            from cryostack_src.storage_layout import durable_replace
            durable_replace(temporary,target)
            temporary=None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def inline_bytes(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise UnsafeArchiveError('Only ordinary result archives can be downloaded.')
    if path.stat().st_size>INLINE_ARCHIVE_LIMIT:
        raise ArchiveLimitError('This archive exceeds the 32 MiB pilot browser limit. Files are retained; ask the organizers for a large-result transfer.')
    # A bounded read also protects against growth between stat and read.
    with path.open('rb') as stream:
        data=stream.read(INLINE_ARCHIVE_LIMIT+1)
    if len(data)>INLINE_ARCHIVE_LIMIT:
        raise ArchiveLimitError('The archive grew beyond the pilot browser download limit. Files are retained.')
    return data

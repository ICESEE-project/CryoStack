"""Authenticated streaming of completed owner-scoped result archives.

Disabled by default. No public file paths, credentials, archive generation or
writes on GET. Directory descriptors and O_NOFOLLOW pin each owner/run boundary.
Only prebuilt ZIPs in a run's cache may be read; control state is never routed.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import re
import stat
from urllib.parse import quote

from aiohttp import web

STREAM_DOWNLOAD_ENV='CRYOSTACK_STREAM_DOWNLOADS'
CHUNK_BYTES=128*1024
IO_TIMEOUT_SECONDS=30
MAX_TRANSFERS=4
_ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z')
_NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.zip\Z',re.IGNORECASE)


def enabled():
    return os.environ.get(STREAM_DOWNLOAD_ENV,'').strip()=='1'


def download_url(path):
    """URL carries only run/file names; the HTTP session supplies the owner."""
    if not enabled():return None
    parts=Path(path).parts
    if len(parts)<5 or parts[-5]!='.cryostack' or parts[-4]!='runs' or parts[-2]!='cache':return None
    run,name=parts[-3],parts[-1]
    if not _ID.fullmatch(run) or not _NAME.fullmatch(name):return None
    return '/api/workspace/download/'+quote(run,safe='')+'/'+quote(name,safe='')


def _open_archive(workspace_root,user_id,run,name):
    from .identity import WorkspaceUser
    from .storage_mount import require_workspace_storage
    if not _ID.fullmatch(run) or not _NAME.fullmatch(name):raise FileNotFoundError()
    root=Path(workspace_root).resolve()
    require_workspace_storage(root/'users')
    owner=WorkspaceUser(user_id=user_id,source='cryostack-auth').safe_id
    directories=['users',owner,'.cryostack','runs',run,'cache']
    descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for namepart in directories:
            child=os.open(namepart,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
            os.close(descriptor);descriptor=child
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
    finally:
        os.close(descriptor)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or os.pread(fd,4,0) not in (b'PK\x03\x04',b'PK\x05\x06'):
            raise FileNotFoundError()
        return os.fdopen(fd,'rb'),info.st_size
    except BaseException:
        os.close(fd)
        raise


def _range(value,size):
    if value is None:return 0,size,200
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
    if match is None or not any(match.groups()):raise ValueError()
    first,last=match.groups()
    if first:
        start=int(first);stop=min(size,int(last)+1) if last else size
    else:
        suffix=int(last)
        if suffix<=0:raise ValueError()
        start=max(0,size-suffix);stop=size
    if start>=size or start>=stop:raise ValueError()
    return start,stop,206


def install_workspace_downloads(app, *, auth, workspace_root=None, streaming_enabled=None):
    """Install before a catch-all proxy. Activate only in a reviewed release."""
    active=enabled() if streaming_enabled is None else streaming_enabled
    if type(active) is not bool:raise ValueError('streaming_enabled must be boolean.')

    transfers=asyncio.Semaphore(MAX_TRANSFERS)

    async def download(request):
        if not active:raise web.HTTPNotFound()
        user=auth.current_user(request)
        if user is None:raise web.HTTPForbidden(text='Approved sign-in is required.')
        run,name=request.match_info['run'],request.match_info['name']
        from .roots import resolve_workspace_root
        try:
            await asyncio.wait_for(transfers.acquire(),timeout=1)
        except asyncio.TimeoutError:
            raise web.HTTPServiceUnavailable(text='Download capacity is busy; retry shortly.',headers={'Retry-After':'5'}) from None
        stream=None
        pending=None
        loop=asyncio.get_running_loop()

        async def io_call(function,*args):
            nonlocal pending
            pending=loop.run_in_executor(None,function,*args)
            return await asyncio.wait_for(asyncio.shield(pending),timeout=IO_TIMEOUT_SECONDS)

        def open_for_request():
            # All potentially blocking mount/path work stays off the event loop.
            root=resolve_workspace_root(workspace_root)
            return _open_archive(root,user.id,run,name)

        def finish_io(future):
            # A timed-out/cancelled SMB operation may still be running in its
            # worker. Keep its concurrency slot until it completes and closes.
            # Never close a Python buffered stream on the event loop while a
            # worker may hold its I/O lock.
            current=stream
            try:
                value=future.result() if future is not None else None
                if current is None and isinstance(value,tuple):current=value[0]
            except BaseException:
                pass
            if current is None:
                transfers.release()
                return
            closing=loop.run_in_executor(None,current.close)
            def closed(done):
                try:done.result()
                except BaseException:pass
                transfers.release()
            closing.add_done_callback(closed)

        try:
            try:
                stream,size=await io_call(open_for_request)
            except asyncio.TimeoutError:
                raise web.HTTPServiceUnavailable(text='Workspace storage is slow; retry shortly.',headers={'Retry-After':'5'}) from None
            except RuntimeError:
                raise web.HTTPServiceUnavailable(text='Workspace storage is temporarily unavailable.') from None
            except (OSError,ValueError):
                raise web.HTTPNotFound(text='Result archive is not available.') from None
            try:
                # No validator is emitted; If-Range therefore requests the full
                # current representation rather than an unverified partial one.
                requested=request.headers.get('Range') if not request.headers.get('If-Range') else None
                start,stop,status=_range(requested,size)
            except ValueError:
                raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range':f'bytes */{size}'}) from None
            headers={'Content-Type':'application/zip','Content-Length':str(stop-start),
                     'Content-Disposition':f'attachment; filename="{name}"',
                     'Cache-Control':'no-store, private','Accept-Ranges':'bytes',
                     'X-Content-Type-Options':'nosniff'}
            if status==206:headers['Content-Range']=f'bytes {start}-{stop-1}/{size}'
            try:
                await io_call(stream.seek,start)
            except asyncio.TimeoutError:
                raise web.HTTPServiceUnavailable(text='Workspace storage is slow; retry shortly.') from None
            response=web.StreamResponse(status=status,headers=headers)
            await response.prepare(request)
            if request.method!='HEAD':
                remaining=stop-start
                while remaining:
                    current=auth.current_user(request,refresh_session=True)
                    if current is None or current.id!=user.id:
                        response.force_close()
                        if request.transport is not None:request.transport.close()
                        raise ConnectionResetError('Account access changed during download.')
                    try:
                        block=await io_call(stream.read,min(CHUNK_BYTES,remaining))
                    except asyncio.TimeoutError:
                        response.force_close()
                        raise ConnectionError('Workspace read timed out; retry the download.') from None
                    if not block:
                        response.force_close()
                        raise ConnectionError('Archive changed during transfer; retry the download.')
                    await response.write(block);remaining-=len(block)
            await response.write_eof()
            return response
        finally:
            if pending is not None:
                pending.add_done_callback(finish_io)
            else:
                finish_io(None)

    app.router.add_get('/api/workspace/download/{run}/{name}',download)

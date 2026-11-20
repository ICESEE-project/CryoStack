"""Default-disabled HTTP adapter for gateway-owned pilot transfer leases.

No participant session route issues a capability. Nothing installs these routes
in the production gateway. A reviewed broker must first supply durable leases,
frozen owner input reads, and an atomic quota-admitted output writer.
"""
from __future__ import annotations
import asyncio
import time
import zipfile
from aiohttp import web
from control_center.services.project_transfer import MAX_BYTES

CHUNK=128*1024
IO_SECONDS=30
REQUEST_SECONDS=120
MAX_TRANSFERS=4


def install_pilot_transfers(app,*,leases,read_input,admit_output,enabled=False,
                            license_runtime=None,release_license=None):
    if type(enabled) is not bool:raise ValueError('Explicit boolean enablement required')
    if not callable(read_input) or not callable(admit_output):
        raise ValueError('Reviewed owner-scoped input and quota-admitted output callbacks required')
    capacity=asyncio.Semaphore(MAX_TRANSFERS)

    async def handle(request):
        if not enabled:raise web.HTTPNotFound()
        auth=request.headers.get('Authorization','')
        if not auth.startswith('Bearer ') or len(auth)>140:
            raise web.HTTPForbidden(text='Transfer authorization required.')
        token=auth[7:];reservation=request.match_info['reservation'];operation=request.match_info['operation']
        if operation=='output':
            size=request.content_length
            if size is None:raise web.HTTPLengthRequired()
            if not 1<=size<=MAX_BYTES:raise web.HTTPRequestEntityTooLarge(max_size=MAX_BYTES,actual_size=size)
        try:await asyncio.wait_for(capacity.acquire(),timeout=1)
        except asyncio.TimeoutError:
            raise web.HTTPServiceUnavailable(text='Transfer capacity is busy.',headers={'Retry-After':'5'}) from None
        pending=None;response=None;deadline=time.monotonic()+REQUEST_SECONDS

        def remaining():
            seconds=min(IO_SECONDS,deadline-time.monotonic())
            if seconds<=0:raise asyncio.TimeoutError()
            return seconds

        async def io_call(function,*args,**kwargs):
            nonlocal pending
            timeout=remaining()
            loop=asyncio.get_running_loop()
            pending=loop.run_in_executor(None,lambda:function(*args,**kwargs))
            return await asyncio.wait_for(asyncio.shield(pending),timeout=timeout)

        async def authorize():
            return await io_call(leases.authorize,reservation,token,operation=("input" if operation in ("license","license-release") else operation))

        try:
            await authorize()
            if operation in ('license','license-release'):
                callback=license_runtime if operation=='license' else release_license
                if callback is None:raise PermissionError('License tunnel is not activated')
                data=await io_call(callback,reservation,token)
                if not isinstance(data,bytes) or len(data)>4*1024**2:
                    raise ValueError('Invalid bounded license response')
                await authorize()
                return web.Response(body=data,content_type='application/json',headers={'Cache-Control':'no-store, private'})
            if operation=='output':
                content=bytearray()
                while True:
                    block=await asyncio.wait_for(request.content.read(CHUNK),timeout=remaining())
                    if not block:break
                    content.extend(block)
                    if len(content)>size or len(content)>MAX_BYTES:
                        raise ValueError('Transfer size changed')
                    await authorize()
                if len(content)!=size:raise ValueError('Incomplete result upload')
                await io_call(leases.accept_output,reservation,token,bytes(content),admit_output=admit_output)
                return web.json_response({'accepted':True},headers={'Cache-Control':'no-store, private'})
            data=await io_call(leases.read,reservation,token,operation=operation,read_input=read_input)
            response=web.StreamResponse(headers={
                'Content-Type':'application/octet-stream' if operation=='worker' else 'application/zip',
                'Content-Length':str(len(data)),'Cache-Control':'no-store, private',
                'X-Content-Type-Options':'nosniff'})
            await response.prepare(request)
            for offset in range(0,len(data),CHUNK):
                await authorize()
                await asyncio.wait_for(response.write(data[offset:offset+CHUNK]),timeout=remaining())
            await response.write_eof();return response
        except (PermissionError,ValueError,zipfile.BadZipFile,asyncio.TimeoutError) as error:
            if response is not None and response.prepared:
                response.force_close()
                if request.transport is not None:request.transport.close()
                raise ConnectionResetError('Transfer authorization or availability changed.') from None
            if isinstance(error,PermissionError):raise web.HTTPForbidden(text='Transfer authorization refused.') from None
            if isinstance(error,asyncio.TimeoutError):raise web.HTTPServiceUnavailable(text='Transfer unavailable; reconciliation may be required.') from None
            raise web.HTTPBadRequest(text='Transfer validation refused.') from None
        except Exception:
            if response is not None and response.prepared:
                response.force_close()
                if request.transport is not None:request.transport.close()
                raise ConnectionResetError('Transfer unavailable.') from None
            raise web.HTTPServiceUnavailable(text='Transfer unavailable; reconciliation may be required.') from None
        finally:
            def completed(future):
                try:future.result()
                except BaseException:pass
                capacity.release()
            # SMB writes may continue after an HTTP timeout. Keep the capacity
            # slot and durable output claim until that same operation finishes.
            if pending is None:capacity.release()
            else:pending.add_done_callback(completed)

    path='/api/pilot-transfer/{reservation:[a-f0-9]{32}}/'
    app.router.add_get(path+'{operation:worker|input}',handle,allow_head=False)
    app.router.add_post(path+'{operation:output}',handle)
    app.router.add_get(path+'{operation:license}',handle,allow_head=False)
    app.router.add_post(path+'{operation:license-release}',handle)

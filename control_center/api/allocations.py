"""Authenticated, same-origin resource allocation routes. No AWS calls."""
import json
import csv
import io
from html import escape
from urllib.parse import urlsplit

from aiohttp import web

from ..services.allocations import AllocationService
from ..templates import control_layout
from .compute import _blocking


async def overview(request):
    try:
        data = await _blocking(request.app['allocation_service'].overview,
                               request['cryostack_user'].id,
                               admin=request.path.startswith('/api/control/'))
        return web.json_response(data,headers={'Cache-Control':'no-store'})
    except PermissionError as e:
        return web.json_response({'error': str(e)}, status=403)


async def mutate(request):
    # Browser writes require an explicit, exact origin; no form POSTs or missing origins.
    origin = request.headers.get('Origin', '')
    parsed = urlsplit(origin)
    if parsed.scheme not in {'http','https'} or parsed.netloc != request.host or parsed.path or parsed.query or parsed.fragment:
        return web.json_response({'error': 'Same-origin request required.'}, status=403)
    if request.content_type != 'application/json':
        return web.json_response({'error': 'JSON required.'}, status=415)
    service = request.app['allocation_service']
    actor = request['cryostack_user'].id
    action = request.match_info['action']
    try:
        body = await request.json()
        if not isinstance(body,dict):
            raise ValueError('JSON object required.')
        if action == 'pool':
            result = await _blocking(service.configure_pool,actor,**body)
        elif action == 'budget':
            result = await _blocking(service.configure_budget,actor,**body)
        elif action == 'policy':
            result = await _blocking(service.configure_policy,actor,**body)
        elif action == 'adjust':
            result = await _blocking(service.adjust,actor,**body)
        elif action == 'reserve':
            result = await _blocking(service.reserve,actor,**body)
        elif action == 'finish':
            result = await _blocking(service.finish,actor,**body)
        else:
            raise ValueError('Unknown action.')
        return web.json_response({'result':result})
    except PermissionError as e:
        # Only action name is audited: never persist untrusted request bodies or credential fields.
        with service._transaction() as c:
            service._audit(c,actor,'request_denied',action_name=action)
        return web.json_response({'error':str(e)},status=403)
    except (ValueError,TypeError,json.JSONDecodeError):
        return web.json_response({'error':'Invalid request or allocation limit. Check the fields and available funds.'},status=400)


async def users(request):
    try:
        rows = await _blocking(request.app['allocation_service'].search_users,
                               request['cryostack_user'].id, query=request.query.get('q',''))
        return web.json_response({'users':rows})
    except PermissionError:
        return web.json_response({'error':'Administrator or owner required.'},status=403)


async def policy_preview(request):
    try:
        result=await _blocking(request.app['allocation_service'].policy_preview,
                               request['cryostack_user'].id,pool_id=request.query.get('pool_id',''))
        return web.json_response(result)
    except PermissionError:
        return web.json_response({'error':'Administrator or owner required.'},status=403)
    except ValueError:
        return web.json_response({'error':'Choose an existing pool.'},status=400)


async def export_balances(request):
    data=await _blocking(request.app['allocation_service'].overview,
                         request['cryostack_user'].id,admin=True)
    output=io.StringIO(newline='')
    writer=csv.writer(output)
    writer.writerow(['User','Email','Pool','Allocated USD','Reserved USD','Simulated charges USD','Available USD'])
    def safe(value):
        value=str(value or '')
        return "'"+value if value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')) else value
    for row in data['accounts']:
        writer.writerow([safe(row['display_name']),safe(row['email']),safe(row['name']),
                         *[f"{row[k]/100:.2f}" for k in ('credit','reserved','charged','available')]])
    return web.Response(text=output.getvalue(),content_type='text/csv',
                        headers={'Content-Disposition':'attachment; filename="cryostack-allocation-balances.csv"',
                                 'Cache-Control':'no-store'})


async def page(request):
    from ..templates_allocations import allocations_page
    admin=request.path.startswith('/control/')
    try:
        await _blocking(request.app['allocation_service'].overview,
                        request['cryostack_user'].id,admin=admin)
    except PermissionError as e:
        raise web.HTTPForbidden(text=str(e))
    return web.Response(text=allocations_page(admin=admin),content_type='text/html')


def install_allocation_routes(app, *, auth, storage):
    app['allocation_service'] = AllocationService(storage)
    admin = auth.require_roles('admin','owner')
    app.router.add_get('/control/allocations',admin(page))
    app.router.add_get('/compute/allocations',auth.require_login(page))
    app.router.add_get('/api/control/allocations',admin(overview))
    app.router.add_get('/api/control/allocations/users',admin(users))
    app.router.add_get('/api/control/allocations/policy-preview',admin(policy_preview))
    app.router.add_get('/api/control/allocations/export',admin(export_balances))
    app.router.add_get('/api/allocations',auth.require_login(overview))
    app.router.add_post('/api/control/allocations/{action:pool|budget|policy|adjust}',admin(mutate))
    app.router.add_post('/api/allocations/{action:reserve|finish}',auth.require_login(mutate))

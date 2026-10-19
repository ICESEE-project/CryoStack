import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

from control_center.api.allocations import install_allocation_routes
from control_center.storage import ControlStorage
from icesee_auth import AuthManager


def test_authenticated_routes_csrf_and_cross_user_limits(tmp_path):
    auth=AuthManager(database_path=tmp_path/'auth.db',secure_cookies=False)
    app=web.Application()
    auth.install(app)
    install_allocation_routes(app,auth=auth,storage=ControlStorage(tmp_path/'auth.db'))
    def identity(email,role=None):
        u=auth.storage.create_user(email=email,display_name=email,institution=None,password_hash='x')
        if role:auth.storage.grant_role(user_id=u.id,role=role)
        session=auth.storage.create_session(ttl_seconds=3600,user_id=u.id)
        return u.id,{'icesee_session':session.id}
    owner,oc=identity('owner@example.test','owner')
    user,uc=identity('user@example.test')
    other,vc=identity('other@example.test')
    s=app['allocation_service']
    p=s.configure_pool(owner,name='Demo',budget=10000)
    s.adjust(owner,pool_id=p,user_id=user,delta=1000,reason='demo test')

    async def run():
        async with TestClient(TestServer(app)) as client:
            origin={'Origin':str(client.make_url('/')).rstrip('/')}
            assert (await client.get('/control/allocations',cookies=oc)).status==200
            assert (await client.get('/compute/allocations',cookies=uc)).status==200
            assert (await client.get('/api/control/allocations',cookies=uc)).status==403
            r=await client.get('/api/allocations',cookies=vc)
            assert (await r.json())['accounts']==[]
            body=dict(pool_id=p,request_key='web-test',application='icesee',preset='small',minutes=15)
            assert (await client.post('/api/allocations/reserve',cookies=uc,json=body)).status==403
            assert (await client.post('/api/allocations/reserve',cookies=uc,json=body,
                                     headers={'Origin':'https://foreign.example'})).status==403
            assert (await client.post('/api/control/allocations/adjust',cookies=uc,json={},headers=origin)).status==403
            r=await client.post('/api/allocations/reserve',cookies=uc,json=body,headers=origin)
            assert r.status==200
            job=(await r.json())['result']['id']
            r=await client.post('/api/allocations/finish',cookies=vc,json={'job_id':job},headers=origin)
            assert r.status==403
            r=await client.post('/api/allocations/finish',cookies=uc,json={'job_id':job},headers=origin)
            assert r.status==200
            r=await client.post('/api/allocations/reserve',cookies=uc,json={**body,'mode':'managed'},headers=origin)
            assert r.status==403
            r=await client.get('/api/allocations',cookies=uc)
            assert (await r.json())['accounts'][0]['charged']==150
            r=await client.get('/api/control/allocations',cookies=oc)
            assert any(a['action']=='request_denied' for a in (await r.json())['audit'])
    asyncio.run(run())


def test_normal_control_install_needs_no_demo_flag(tmp_path,monkeypatch):
    from control_center import install_control_center
    from control_center.services import AccessService
    monkeypatch.delenv('CRYOSTACK_ALLOCATION_DEMO',raising=False)
    monkeypatch.setenv('CRYOSTACK_AUTH_DATABASE',str(tmp_path/'auth.db'))
    auth=AuthManager(database_path=tmp_path/'auth.db',secure_cookies=False)
    app=web.Application()
    auth.install(app)
    app['access_service']=AccessService(auth.storage)
    install_control_center(app,auth=auth,database_path=tmp_path/'auth.db')
    u=auth.storage.create_user(email='owner@example.test',display_name='Owner',institution=None,password_hash='x')
    auth.storage.grant_role(user_id=u.id,role='owner')
    cookie={'icesee_session':auth.storage.create_session(ttl_seconds=3600,user_id=u.id).id}
    async def run():
        async with TestClient(TestServer(app)) as client:
            r=await client.get('/control/allocations',cookies=cookie)
            text=await r.text()
            assert r.status==200
            for title in ('Resource Allocations','Funding Pools','User Allocations','Automatic Credits'):
                assert title in text
            assert 'eligible_domain' in text
            assert (await client.get('/api/control/allocations',allow_redirects=False)).status in (302,303,401,403)
    asyncio.run(run())

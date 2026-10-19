import asyncio
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from control_center.api.allocations import install_allocation_routes
from control_center.storage import ControlStorage
from icesee_auth import AuthManager

def test_policy_budget_search_and_rbac(tmp_path):
 auth=AuthManager(database_path=tmp_path/'auth.db',secure_cookies=False)
 app=web.Application();auth.install(app);install_allocation_routes(app,auth=auth,storage=ControlStorage(tmp_path/'auth.db'))
 def user(email,role=None):
  u=auth.storage.create_user(email=email,display_name=email.split('@')[0],institution=None,password_hash='x')
  if role:auth.storage.grant_role(user_id=u.id,role=role)
  return u,{'icesee_session':auth.storage.create_session(ttl_seconds=3600,user_id=u.id).id}
 owner,oc=user('owner@example.test','owner');alice,ac=user('alice@example.test');s=app['allocation_service']
 async def run():
  async with TestClient(TestServer(app)) as client:
   origin={'Origin':str(client.make_url('/')).rstrip('/')}
   async def post(action,body,cookie=oc):return await client.post('/api/control/allocations/'+action,json=body,cookies=cookie,headers=origin)
   r=await post('budget',dict(name='Research',budget=10000));assert r.status==200;p=(await r.json())['result']
   assert (await post('policy',dict(pool_id=p,intro_enabled=True,default_credit=500,eligible_domain='example.test'))).status==200
   assert (await post('budget',dict(pool_id=p,name='Updated',budget=12000))).status==200
   policy=s.overview(owner.id,admin=True)['pools'][0];assert policy['intro_enabled']==1 and policy['default_credit']==500
   assert (await post('budget',dict(pool_id=p,name='Too low',budget=100))).status==400
   assert (await post('policy',dict(pool_id=p,intro_enabled=False,default_credit=0),ac)).status==403
   r=await client.get('/api/control/allocations/users?q=alice',cookies=oc);assert r.status==200;assert (await r.json())['users'][0]['id']==alice.id
   assert (await client.get('/api/control/allocations/users?q=alice',cookies=ac)).status==403
   assert s.search_users(owner.id,query='%')==[]
   assert (await post('adjust',dict(pool_id=p,user_id=alice.id,delta=1000,reason='Research grant'))).status==200
   account=s.overview(alice.id)['accounts'][0];assert account['email']=='alice@example.test' and account['display_name']=='alice'
   r=await client.get('/control/allocations',cookies=oc);text=await r.text();assert r.status==200
   assert 'integer cents' not in text and 'Simulation demo' not in text
   assert all(label in text for label in ['Total pool budget','Find a CryoStack user','Onboarding policy'])
 asyncio.run(run())


def test_overview_preview_export_and_permissions(tmp_path):
 import csv,io
 auth=AuthManager(database_path=tmp_path/'auth.db',secure_cookies=False)
 app=web.Application();auth.install(app);install_allocation_routes(app,auth=auth,storage=ControlStorage(tmp_path/'auth.db'))
 def user(email,name,role=None):
  u=auth.storage.create_user(email=email,display_name=name,institution='GT',password_hash='x')
  if role:auth.storage.grant_role(user_id=u.id,role=role)
  return u,{'icesee_session':auth.storage.create_session(ttl_seconds=3600,user_id=u.id).id}
 owner,oc=user('owner@gatech.edu','Owner','owner');alice,ac=user('alice@gatech.edu','=HYPERLINK("bad")')
 s=app['allocation_service'];p=s.configure_pool(owner.id,name='+Unsafe pool',budget=10000,intro_enabled=True,default_credit=500,eligible_domain='gatech.edu')
 s.adjust(owner.id,pool_id=p,user_id=alice.id,delta=1000,reason='Research grant')
 job=s.reserve(alice.id,pool_id=p,request_key='first',application='icesee',preset='small',minutes=15)
 async def run():
  async with TestClient(TestServer(app)) as client:
   r=await client.get('/api/control/allocations',cookies=oc);assert r.status==200;pool=(await r.json())['pools'][0]
   assert pool['unallocated']+pool['available_user_credit']+pool['reserved']+pool['simulated_charges']==pool['budget']
   assert pool['new_user_grant_capacity']==18
   before=s.overview(owner.id,admin=True)
   r=await client.get('/api/control/allocations/policy-preview?pool_id='+p,cookies=oc);d=await r.json()
   assert r.status==200 and d['matching_existing_users']==2 and d['retroactive_grants'] is False
   assert s.overview(owner.id,admin=True)==before
   assert (await client.get('/api/control/allocations/policy-preview?pool_id=missing',cookies=oc)).status==400
   for path in ['/api/control/allocations/policy-preview?pool_id='+p,'/api/control/allocations/export']:
    assert (await client.get(path,cookies=ac)).status==403
    assert (await client.get(path,allow_redirects=False)).status in (302,303,401,403)
   r=await client.get('/api/control/allocations/export',cookies=oc);assert r.status==200 and r.headers['Cache-Control']=='no-store'
   rows=list(csv.reader(io.StringIO(await r.text())));assert rows[1][0].startswith("'=") and rows[1][2].startswith("'+")
   assert rows[1][3:] == ['10.00','1.50','0.00','8.50']
   text=await (await client.get('/control/allocations',cookies=oc)).text()
   assert all(t in text for t in ['Budget composition','Funding readiness','Preview saved policy','Export CSV'])
 asyncio.run(run())

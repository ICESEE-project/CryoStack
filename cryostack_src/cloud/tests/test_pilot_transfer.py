"""Real private HTTP acceptance for an uninstalled, disabled-by-default adapter."""
import asyncio
import threading
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
import pytest
from control_center.tests.test_project_transfer import service,env,output
from cryostack_src.cloud import pilot_transfer as route


def client(service,*,enabled=True,read=None,write=None):
    leases,row,token,data,_=service
    app=web.Application()
    route.install_pilot_transfers(app,leases=leases,read_input=read or (lambda *a:data),
        admit_output=write or (lambda *a:None),enabled=enabled)
    return TestClient(TestServer(app))


def test_disabled_and_method_boundaries(service):
    async def check():
        row=service[1];base='/api/pilot-transfer/'+row['id']+'/'
        async with client(service,enabled=False) as c:
            assert (await c.get(base+'input')).status==404
        async with client(service) as c:
            for method,name in [('get','output'),('post','input'),('head','worker')]:
                assert (await getattr(c,method)(base+name)).status==405
            assert (await c.get(base+'input')).status==403
            assert (await c.get(base+'input?token='+service[2])).status==403
    asyncio.run(check())


def test_exact_worker_input_and_result_crc_round_trip(service):
    async def check():
        leases,row,token,data,_=service;base='/api/pilot-transfer/'+row['id']+'/'
        headers={'Authorization':'Bearer '+token};writes=[];result_bytes=output()
        async with client(service,write=lambda *a:writes.append(a)) as c:
            for name,expected in [('worker',leases.worker_source),('input',data)]:
                response=await c.get(base+name,headers=headers)
                assert response.status==200 and await response.read()==expected
                assert response.headers['Cache-Control']=='no-store, private'
            response=await c.post(base+'output',headers=headers,data=result_bytes)
            assert response.status==200 and await response.json()=={'accepted':True}
            assert len(writes)==1 and writes[0][:2]==(row['user_id'],row['id'])
            assert (await c.post(base+'output',headers=headers,data=result_bytes)).status==200
            assert len(writes)==1
            assert (await c.get(base+'input',headers=headers)).status==403
    asyncio.run(check())


def test_revocation_after_storage_read_prevents_disclosure(service):
    async def check():
        leases,row,token,data,_=service
        def read(*args):leases.revoke(row['id']);return data
        async with client(service,read=read) as c:
            response=await c.get('/api/pilot-transfer/'+row['id']+'/input',headers={'Authorization':'Bearer '+token})
            assert response.status==403 and data not in await response.read()
    asyncio.run(check())


def test_invalid_result_and_missing_or_oversized_lengths_do_not_write(service,monkeypatch):
    async def check():
        row=service[1];token=service[2];writes=[]
        async with client(service,write=lambda *a:writes.append(a)) as c:
            url='/api/pilot-transfer/'+row['id']+'/output';headers={'Authorization':'Bearer '+token}
            assert (await c.post(url,headers=headers,data=output(model_uid=0))).status==400
            async def chunked():yield b'not a complete zip'
            assert (await c.post(url,headers=headers,data=chunked())).status==411
            monkeypatch.setattr(route,'MAX_BYTES',16)
            assert (await c.post(url,headers=headers,data=b'x'*17)).status==413
            assert not writes
    asyncio.run(check())


def test_uncertain_write_timeout_retains_bounded_io_slot_and_claim(service,monkeypatch):
    started=threading.Event();release=threading.Event();writes=[]
    def blocked(*args):writes.append(args);started.set();release.wait(3)
    async def check():
        monkeypatch.setattr(route,'IO_SECONDS',.05);monkeypatch.setattr(route,'MAX_TRANSFERS',1)
        leases,row,token,_,_=service;url='/api/pilot-transfer/'+row['id']+'/output';result_bytes=output()
        async with client(service,write=blocked) as c:
            headers={'Authorization':'Bearer '+token}
            response=await c.post(url,headers=headers,data=result_bytes)
            assert response.status==503 and started.is_set()
            assert (await c.post(url,headers=headers,data=result_bytes)).status==503
            assert len(writes)==1
            release.set();await asyncio.sleep(.05)
            with leases._transaction() as db:
                # Background completion is durable; a subsequent exact retry
                # returns its receipt without repeating quota admission.
                assert db.execute('SELECT state FROM pilot_transfer_leases').fetchone()[0]=='complete'
            assert (await c.post(url,headers=headers,data=result_bytes)).status==200
            assert len(writes)==1
    try:asyncio.run(check())
    finally:release.set()

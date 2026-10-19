from concurrent.futures import ThreadPoolExecutor

import pytest

from control_center.services.allocations import AllocationService
from control_center.storage import ControlStorage
from icesee_auth.storage import AuthStorage


@pytest.fixture
def env(tmp_path):
    auth = AuthStorage(tmp_path/'auth.db')
    service = AllocationService(ControlStorage(tmp_path/'auth.db'))
    def user(email,role=None):
        u = auth.create_user(email=email,display_name=email,institution=None,password_hash='x')
        if role:
            auth.grant_role(user_id=u.id,role=role)
        return u.id
    owner=user('owner@example.test','owner')
    researcher=user('researcher@example.test')
    pool=service.configure_pool(owner,name='Demo pool',budget=10000)
    return auth,service,user,owner,researcher,pool


def reserve(s,u,p,key='first',**kwargs):
    return s.reserve(u,pool_id=p,request_key=key,application='icesee',preset='small',minutes=15,**kwargs)


def test_admin_roles_and_bounds(env):
    _,s,user,owner,u,p=env
    for role in (None,'developer','maintainer'):
        actor=user(str(role)+'@example.test',role)
        with pytest.raises(PermissionError):
            s.configure_pool(actor,name='x',budget=100)
        with pytest.raises(PermissionError):
            s.adjust(actor,pool_id=p,user_id=u,delta=100,reason='demo test')
    admin=user('admin@example.test','admin')
    s.adjust(admin,pool_id=p,user_id=u,delta=500,reason='demo test')
    for bad in (True,1.5,-1,'100',float('inf')):
        with pytest.raises(ValueError):
            s.configure_pool(owner,name='x',budget=bad)


def test_intro_at_creation_once_and_no_retroactive_grants(env):
    auth,s,user,owner,u,p=env
    s.configure_pool(owner,pool_id=p,name='Demo',budget=10000,intro_enabled=True,default_credit=300)
    assert not s.overview(u)['accounts']
    new=user('new@example.test')
    assert s.overview(new)['accounts'][0]['available']==300
    s.configure_pool(owner,pool_id=p,name='Demo',budget=10000,intro_enabled=False,default_credit=300)
    disabled=user('disabled@example.test')
    s.configure_pool(owner,pool_id=p,name='Demo',budget=10000,intro_enabled=True,default_credit=500)
    assert not s.overview(disabled)['accounts']
    assert s.overview(new)['accounts'][0]['credit']==300
    assert len([a for a in s.overview(owner,admin=True)['audit'] if a['action']=='intro_granted'])==1


def test_exhausted_intro_pool_is_not_overallocated(env):
    _,s,user,owner,u,p=env
    s.configure_pool(owner,pool_id=p,name='Demo',budget=500,intro_enabled=True,default_credit=300)
    ids=list(ThreadPoolExecutor(4).map(lambda n:user(f'new{n}@example.test'),range(8)))
    assert sum(len(s.overview(i)['accounts']) for i in ids)==1
    assert s.overview(owner,admin=True)['pools'][0]['allocated']==300


def test_reserve_ownership_finalize_and_idempotency(env):
    _,s,user,owner,u,p=env
    with pytest.raises(PermissionError):reserve(s,u,p)
    s.adjust(owner,pool_id=p,user_id=u,delta=500,reason='demo test')
    j=reserve(s,u,p)
    assert j['ceiling']==150
    assert reserve(s,u,p)['id']==j['id']
    with pytest.raises(ValueError):
        s.reserve(u,pool_id=p,request_key='first',application='livist',preset='small',minutes=15)
    with pytest.raises(PermissionError):s.finish(owner,job_id=j['id'])
    with pytest.raises(ValueError):s.adjust(owner,pool_id=p,user_id=u,delta=-400,reason='demo test')
    s.finish(u,job_id=j['id'])
    s.finish(u,job_id=j['id'])
    assert s.overview(u)['accounts'][0]['charged']==150
    with pytest.raises(ValueError):s.finish(u,job_id=j['id'],cancel=True)
    j2=reserve(s,u,p,'second');s.finish(u,job_id=j2['id'],cancel=True)
    assert s.overview(u)['accounts'][0]['available']==350
    assert s.overview(u)['accounts'][0]['reserved']==0


def test_concurrent_reservations_cannot_overspend(env):
    _,s,user,owner,u,p=env
    s.adjust(owner,pool_id=p,user_id=u,delta=200,reason='demo test')
    def attempt(n):
        try:return reserve(s,u,p,str(n))['id']
        except PermissionError:return None
    ids=list(ThreadPoolExecutor(8).map(attempt,range(20)))
    assert sum(i is not None for i in ids)==1
    assert s.overview(u)['accounts'][0]['reserved']==150


def test_live_denied_and_resource_limits(env):
    _,s,user,owner,u,p=env
    s.adjust(owner,pool_id=p,user_id=u,delta=1000,reason='demo test')
    with pytest.raises(PermissionError):reserve(s,u,p,mode='managed')
    for minutes in (0,-1,61,True,1.1):
        with pytest.raises(ValueError):s.reserve(u,pool_id=p,request_key='bad',application='icesee',preset='small',minutes=minutes)
    reserve(s,u,p,'a');reserve(s,u,p,'b')
    with pytest.raises(PermissionError):reserve(s,u,p,'c')
    assert s.overview(u)['live_project_aws_enabled'] is False


def test_pool_budget_and_user_separation(env):
    _,s,user,owner,u,p=env
    s.adjust(owner,pool_id=p,user_id=u,delta=9000,reason='demo test')
    v=user('other@example.test')
    with pytest.raises(ValueError):s.adjust(owner,pool_id=p,user_id=v,delta=1001,reason='demo test')
    with pytest.raises(ValueError):s.configure_pool(owner,pool_id=p,name='Demo',budget=8999)
    assert not s.overview(v)['accounts']
    assert not s.overview(v)['jobs']
    with pytest.raises(PermissionError):s.overview(u,admin=True)


def test_cohort_filters_and_policy_upgrade(env):
    auth,s,user,owner,u,p=env
    s.configure_pool(owner,pool_id=p,name='Demo',budget=10000,intro_enabled=True,
                     default_credit=500,eligible_domain='GATECH.EDU',eligible_institution='Georgia Tech')
    def create(email,institution):
        return auth.create_user(email=email,display_name=email,institution=institution,password_hash='x').id
    eligible=create('eligible@gatech.edu','Georgia Tech')
    assert s.overview(eligible)['accounts'][0]['credit']==500
    for email,institution in [('no@evilgatech.edu','Georgia Tech'),('no@gatech.edu',None),('no@other.edu','Georgia Tech')]:
        assert s.overview(create(email,institution))['accounts']==[]
    upgraded=AllocationService(ControlStorage(auth.database_path)) if hasattr(auth,'database_path') else AllocationService(s.storage)
    assert upgraded.overview(eligible)['accounts'][0]['credit']==500
    assert len([a for a in upgraded.overview(owner,admin=True)['audit'] if a['action']=='intro_granted'])==1


def test_existing_schema_migrates_without_losing_balances(env):
    _,s,_,owner,u,p=env
    s.adjust(owner,pool_id=p,user_id=u,delta=1000,reason='migration test')
    with s._transaction() as c:
        c.execute('DROP TRIGGER allocation_new_user')
        c.execute('ALTER TABLE allocation_pools DROP COLUMN eligible_domain')
        c.execute('ALTER TABLE allocation_pools DROP COLUMN eligible_institution')
    upgraded=AllocationService(s.storage)
    assert upgraded.overview(u)['accounts'][0]['credit']==1000
    pool=upgraded.overview(owner,admin=True)['pools'][0]
    assert pool['eligible_domain']==pool['eligible_institution']==''

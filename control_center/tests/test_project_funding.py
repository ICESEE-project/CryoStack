"""Offline admission/settlement tests; no AWS identity, client or submission."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import uuid

import pytest

from control_center.services.allocations import AllocationService
from control_center.services.project_funding import FundingPolicy, FundedRun, ProjectFundingLedger
from control_center.storage import ControlStorage
from icesee_auth import AuthManager
from icesee_auth.mailer import MailConfig


@pytest.fixture
def env(tmp_path):
    auth=AuthManager(database_path=tmp_path/'auth.db',approval_required=True,
                     mail_config=MailConfig(),background_interval_s=0)
    storage=ControlStorage(tmp_path/'auth.db')
    allocation=AllocationService(storage)
    def user(name,status='approved',role=None):
        u=auth.storage.create_user(email=name+'@example.invalid',display_name=name,institution=None,password_hash='unusable')
        with auth.storage._connect() as c:
            c.execute("INSERT INTO account_status(user_id,status,registration_method,requested_at,updated_at) VALUES (?,?,'test',1,1)",(u.id,status))
        if role:auth.storage.grant_role(user_id=u.id,role=role)
        return u.id
    admin=user('admin',role='admin');a=user('a');b=user('b')
    pool=allocation.configure_pool(admin,name='Synthetic pool',budget=2000)
    for u in (a,b):allocation.adjust(admin,pool_id=pool,user_id=u,delta=500,reason='Offline test grant')
    policy=FundingPolicy('pilot-v1',pool,'private-gateway-binding','sha256:'+'a'*64,100,500)
    ledger=ProjectFundingLedger(storage,policy,admission_enabled=True)
    run=FundedRun('icepack',60,'b'*64,'c'*64)
    return auth,storage,allocation,user,admin,a,b,policy,ledger,run


def reserve(env,user=None,key='request',ledger=None,run=None):
    _,_,_,_,_,a,_,_,l,r=env
    return (ledger or l).reserve(user or a,request_key=key,run=run or r)


def balance(env,user=None):
    _,_,allocation,_,_,a,_,_,_,_=env
    return allocation.overview(user or a)['accounts'][0]


def start(env,user=None,key='request'):
    l=env[8];u=user or env[5];r=reserve(env,user=u,key=key)
    claim=l.claim_submission(u,r['id']);assert claim
    job=str(uuid.uuid4());l.record_submission(r['id'],submission_token=claim['submission_token'],external_job_id=job)
    return r,claim,job


def test_disabled_and_no_real_driver_or_activation(env):
    *_,policy,ledger,run=env
    disabled=ProjectFundingLedger(env[1],policy)
    with pytest.raises(PermissionError):reserve(env,ledger=disabled)
    with pytest.raises(PermissionError):env[2].reserve(env[5],pool_id=policy.pool_id,request_key='x',application='cryolauncher',preset='small',minutes=1,mode='managed')
    assert env[2].overview(env[5])['live_project_aws_enabled'] is False
    assert balance(env)['reserved']==0


@pytest.mark.parametrize('status',['pending','rejected','suspended'])
def test_nonapproved_denied_before_hold(env,status):
    u=env[3]('denied',status)
    env[2].adjust(env[4],pool_id=env[7].pool_id,user_id=u,delta=100,reason='Offline test grant')
    with pytest.raises(PermissionError):reserve(env,user=u)
    assert balance(env,u)['reserved']==0


def test_missing_approval_record_denied(env):
    u=env[0].storage.create_user(email='legacy@example.invalid',display_name='Legacy',institution=None,password_hash='unusable')
    with pytest.raises(PermissionError):reserve(env,user=u.id)


def test_idempotency_and_changed_inputs_policy_refused(env):
    r=reserve(env);assert reserve(env)['id']==r['id'];assert balance(env)['reserved']==100
    assert 'claim_hash' not in r and 'submission_token' not in r
    for modified in (replace(env[9],seconds=61),replace(env[9],input_sha256='d'*64),replace(env[9],script_sha256='d'*64),replace(env[9],model='issm')):
        with pytest.raises(ValueError):reserve(env,run=modified)
    changed=ProjectFundingLedger(env[1],replace(env[7],execution_profile='different'),admission_enabled=True)
    with pytest.raises(ValueError):reserve(env,ledger=changed)


@pytest.mark.parametrize('seconds',[True,0,901,1.5,'60'])
def test_runtime_bounds_before_reservation(env,seconds):
    with pytest.raises(ValueError):reserve(env,run=replace(env[9],seconds=seconds))
    assert balance(env)['reserved']==0


def test_invalid_digest_model_key_and_policy(env):
    for run in (replace(env[9],model='other'),replace(env[9],input_sha256='missing'),replace(env[9],script_sha256='D'*64)):
        with pytest.raises(ValueError):reserve(env,run=run)
    with pytest.raises(ValueError):reserve(env,key='../other')
    for field,value in [('image_digest','latest'),('ceiling_cents',True),('campaign_cap_cents',99),('max_platform_jobs',0)]:
        with pytest.raises(ValueError):replace(env[7],**{field:value})


def test_one_job_per_participant_and_cross_owner_denial(env):
    r=reserve(env)
    with pytest.raises(PermissionError):reserve(env,key='second')
    with pytest.raises(PermissionError):env[8].owned(env[6],r['id'])
    with pytest.raises(PermissionError):env[8].claim_submission(env[6],r['id'])
    with pytest.raises(PermissionError):env[8].release_unsubmitted(env[6],r['id'])
    assert balance(env)['reserved']==100 and balance(env,env[6])['reserved']==0


def test_concurrent_retries_share_one_reservation_and_claim(env):
    rows=list(ThreadPoolExecutor(6).map(lambda _:reserve(env),range(20)))
    assert len({r['id'] for r in rows})==1
    claims=list(ThreadPoolExecutor(6).map(lambda _:env[8].claim_submission(env[5],rows[0]['id']),range(20)))
    assert sum(c is not None for c in claims)==1
    assert balance(env)['reserved']==100


def test_crash_or_timeout_holds_funds_across_restart(env):
    r=reserve(env);claim=env[8].claim_submission(env[5],r['id'])
    restored=ProjectFundingLedger(env[1],env[7],admission_enabled=True)
    assert restored.claim_submission(env[5],r['id']) is None
    assert restored.owned(env[5],r['id'])['state']=='submitting'
    with pytest.raises(ValueError):restored.release_unsubmitted(env[5],r['id'])
    assert balance(env)['reserved']==100 and balance(env)['charged']==0
    with env[1]._connect() as c:
        row=dict(c.execute('SELECT * FROM project_funding_jobs').fetchone())
        assert claim['submission_token'] not in json.dumps(row)
        assert claim['submission_token'] not in json.dumps([dict(x) for x in c.execute('SELECT * FROM allocation_audit')])


def test_suspended_after_reserve_cannot_submit_but_can_release(env):
    r=reserve(env)
    with env[1]._connect() as c:c.execute("UPDATE account_status SET status='suspended' WHERE user_id=?",(env[5],))
    with pytest.raises(PermissionError):env[8].claim_submission(env[5],r['id'])
    env[8].release_unsubmitted(env[5],r['id']);env[8].release_unsubmitted(env[5],r['id'])
    assert balance(env)['reserved']==0


def test_inactive_pool_or_changed_policy_cannot_submit(env):
    r=reserve(env)
    changed=ProjectFundingLedger(env[1],replace(env[7],image_digest='sha256:'+'d'*64),admission_enabled=True)
    with pytest.raises(PermissionError):changed.claim_submission(env[5],r['id'])
    with env[1]._connect() as c:c.execute('UPDATE allocation_pools SET active=0 WHERE id=?',(env[7].pool_id,))
    with pytest.raises(PermissionError):env[8].claim_submission(env[5],r['id'])
    with pytest.raises(PermissionError):reserve(env,user=env[6])


def test_claim_token_and_external_job_binding(env):
    r=reserve(env);claim=env[8].claim_submission(env[5],r['id']);job=str(uuid.uuid4())
    with pytest.raises(PermissionError):env[8].record_submission(r['id'],submission_token='wrong',external_job_id=job)
    with pytest.raises(ValueError):env[8].record_submission(r['id'],submission_token=claim['submission_token'],external_job_id='other')
    first=env[8].record_submission(r['id'],submission_token=claim['submission_token'],external_job_id=job)
    assert env[8].record_submission(r['id'],submission_token=claim['submission_token'],external_job_id=job)==first
    with pytest.raises(ValueError):env[8].record_submission(r['id'],submission_token=claim['submission_token'],external_job_id=str(uuid.uuid4()))


def test_exact_once_settlement_matches_job_and_terminal_evidence(env):
    r,_,job=start(env)
    for outcome in ('RUNNING','SUBMITTED','CANCEL_REQUESTED'):
        with pytest.raises(ValueError):env[8].settle_terminal(r['id'],external_job_id=job,outcome=outcome,charge_cents=1)
    with pytest.raises(PermissionError):env[8].settle_terminal(r['id'],external_job_id=str(uuid.uuid4()),outcome='SUCCEEDED',charge_cents=1)
    with pytest.raises(ValueError):env[8].settle_terminal(r['id'],external_job_id=job,outcome='SUCCEEDED',charge_cents=101)
    assert balance(env)['reserved']==100
    settle=lambda _:env[8].settle_terminal(r['id'],external_job_id=job,outcome='SUCCEEDED',charge_cents=12)
    list(ThreadPoolExecutor(5).map(settle,range(10)))
    assert balance(env)['reserved']==0 and balance(env)['charged']==12
    with pytest.raises(ValueError):env[8].settle_terminal(r['id'],external_job_id=job,outcome='FAILED',charge_cents=12)
    with pytest.raises(ValueError):env[8].settle_terminal(r['id'],external_job_id=job,outcome='SUCCEEDED',charge_cents=11)


def test_cancellation_does_not_erase_execution_charge(env):
    r,_,job=start(env)
    with pytest.raises(ValueError):env[8].release_unsubmitted(env[5],r['id'])
    with env[1]._connect() as c:c.execute("UPDATE account_status SET status='suspended' WHERE user_id=?",(env[5],))
    paused=ProjectFundingLedger(env[1],replace(env[7],ceiling_cents=1))
    paused.settle_terminal(r['id'],external_job_id=job,outcome='FAILED',charge_cents=25)
    assert balance(env)['reserved']==0 and balance(env)['charged']==25


def test_shared_campaign_cap_includes_uncertain_holds_and_terminal_charges(env):
    limited=ProjectFundingLedger(env[1],replace(env[7],campaign_cap_cents=100),admission_enabled=True)
    r=reserve(env,ledger=limited)
    with pytest.raises(PermissionError):reserve(env,user=env[6],ledger=limited)
    limited.release_unsubmitted(env[5],r['id'])
    assert reserve(env,user=env[6],ledger=limited)['state']=='reserved'


def test_platform_cap_and_demo_holds_share_user_balance(env):
    strict=ProjectFundingLedger(env[1],replace(env[7],max_platform_jobs=1),admission_enabled=True)
    reserve(env,ledger=strict)
    with pytest.raises(PermissionError):reserve(env,user=env[6],ledger=strict)
    env[2].reserve(env[6],pool_id=env[7].pool_id,request_key='demo',application='cryolauncher',preset='small',minutes=60)
    # The 300-cent demo hold leaves 200; increasing the funded ceiling is refused.
    large=ProjectFundingLedger(env[1],replace(env[7],ceiling_cents=300,max_platform_jobs=2),admission_enabled=True)
    with pytest.raises(PermissionError):reserve(env,user=env[6],ledger=large)


def test_uncertain_submission_can_reconcile_after_lost_token_with_admin_evidence(env):
    r=reserve(env);env[8].claim_submission(env[5],r['id'])
    restored=ProjectFundingLedger(env[1],replace(env[7],ceiling_cents=1))
    fields=dict(external_job_id=str(uuid.uuid4()),policy_sha256=env[7].fingerprint,run=env[9],evidence_sha256='e'*64,reason='Verified synthetic receipt')
    with pytest.raises(PermissionError):restored.reconcile_by_operator(env[5],r['id'],**fields)
    with pytest.raises(ValueError):restored.reconcile_by_operator(env[4],r['id'],**{**fields,'run':replace(env[9],script_sha256='d'*64)})
    with pytest.raises(ValueError):restored.reconcile_by_operator(env[4],r['id'],**{**fields,'policy_sha256':'f'*64})
    bound=restored.reconcile_by_operator(env[4],r['id'],**fields)
    assert bound['state']=='running' and balance(env)['reserved']==100
    assert restored.reconcile_by_operator(env[4],r['id'],**fields)==bound
    with pytest.raises(ValueError):restored.reconcile_by_operator(env[4],r['id'],**{**fields,'external_job_id':str(uuid.uuid4())})
    restored.settle_terminal(r['id'],external_job_id=fields['external_job_id'],outcome='SUCCEEDED',charge_cents=12)
    assert balance(env)['charged']==12 and balance(env)['reserved']==0

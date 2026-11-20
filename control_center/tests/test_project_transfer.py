"""Owner-scoped capabilities and uncertain-result retries; no live routes/AWS."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
import zipfile
import pytest
from control_center.services.project_funding import ProjectFundingLedger
from control_center.services.project_transfer import PilotTransferLeases, validate_result
from control_center.tests.test_project_funding import env
from control_center.tests.test_project_execution import profile


def archive(entries):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        for name,data in entries:z.writestr(name,data)
    return raw.getvalue()


def output(**changes):
    receipt=dict(exit_code=0,timed_out=False,runtime_seconds=1.0,model_processes_stopped=True,
                 model_uid=65534,log_bytes_forwarded=10,log_truncated=False)
    receipt.update(changes)
    return archive([('nested/result.json','{}'),('.cryostack-worker.json',json.dumps(receipt))])


@pytest.fixture
def service(env):
    worker=b'# synthetic worker for offline lease tests\n'
    p=profile(worker_sha256=hashlib.sha256(worker).hexdigest())
    policy=replace(env[7],execution_profile=p.profile_id,image_digest=p.image_digest)
    ledger=ProjectFundingLedger(env[1],policy,admission_enabled=True)
    data=b'synthetic frozen input bytes'
    run=replace(env[9],input_sha256=hashlib.sha256(data).hexdigest())
    row=ledger.reserve(env[5],request_key='lease',run=run)
    ledger.claim_submission(env[5],row['id'])
    now=[1000.0]
    leases=PilotTransferLeases(ledger,p,key=b'k'*32,worker_source=worker,enabled=True,clock=lambda:now[0])
    token=leases.issue(env[5],row['id'])
    return leases,row,token,data,now


def test_default_disabled_has_no_creation_or_authorization(service):
    s,row,token,_,_=service
    disabled=PilotTransferLeases(s.ledger,s.profile,key=b'k'*32,worker_source=s.worker_source)
    with pytest.raises(PermissionError):disabled.issue(row['user_id'],row['id'])
    with pytest.raises(PermissionError):disabled.authorize(row['id'],token,operation='worker')


def test_worker_digest_and_key_are_reviewed(service):
    s,*_=service
    with pytest.raises(PermissionError):PilotTransferLeases(s.ledger,s.profile,key=b'k'*32,worker_source=b'changed')
    with pytest.raises(ValueError):PilotTransferLeases(s.ledger,s.profile,key=b'weak',worker_source=s.worker_source)


def test_read_only_returns_reviewed_worker_and_immutable_owner_input(service):
    s,row,token,data,_=service;seen=[]
    assert s.read(row['id'],token,operation='worker',read_input=lambda *a:None)==s.worker_source
    def read(owner,reservation):seen.append((owner,reservation));return data
    assert s.read(row['id'],token,operation='input',read_input=read)==data
    assert seen==[(row['user_id'],row['id'])]
    with pytest.raises(PermissionError):s.read(row['id'],token,operation='input',read_input=lambda *a:b'changed')
    with pytest.raises(ValueError):s.read(row['id'],token,operation='output',read_input=read)


def test_capability_not_stored_and_retries_do_not_extend_expiry(service):
    s,row,token,_,now=service
    now[0]+=10
    assert s.issue(row['user_id'],row['id'])==token
    with s._transaction() as c:
        lease=dict(c.execute('SELECT * FROM pilot_transfer_leases').fetchone())
    assert token not in str(lease) and lease['expires']==2440.0
    now[0]=lease['expires']
    with pytest.raises(PermissionError):s.authorize(row['id'],token,operation='worker')
    with pytest.raises(PermissionError):s.issue(row['user_id'],row['id'])


@pytest.mark.parametrize('operation',['worker','input','output'])
def test_wrong_capability_and_other_reservation_refused(service,operation):
    s,row,token,_,_=service
    with pytest.raises(PermissionError):s.authorize(row['id'],'x'*43,operation=operation)
    with pytest.raises(PermissionError):s.authorize('f'*32,token,operation=operation)
    with pytest.raises(PermissionError):s.issue('different-owner',row['id'])


@pytest.mark.parametrize('condition',['suspended','pool-disabled','terminal','revoked','policy-changed'])
def test_every_operation_rechecks_approval_pool_reservation_and_revocation(service,condition):
    s,row,token,_,_=service
    if condition=='revoked':s.revoke(row['id'])
    else:
        with s._transaction() as c:
            if condition=='suspended':c.execute("UPDATE account_status SET status='suspended' WHERE user_id=?",(row['user_id'],))
            elif condition=='pool-disabled':c.execute('UPDATE allocation_pools SET active=0')
            elif condition=='terminal':c.execute("UPDATE project_funding_jobs SET state='released' WHERE id=?",(row['id'],))
            elif condition=='policy-changed':c.execute("UPDATE project_funding_jobs SET policy_sha256=?",('f'*64,))
    for op in ('worker','input','output'):
        with pytest.raises(PermissionError):s.authorize(row['id'],token,operation=op)


def test_successful_output_retry_is_idempotent_and_never_overwrites(service):
    s,row,token,_,_=service;writes=[];data=output()
    writer=lambda *args:writes.append(args)
    receipt=s.accept_output(row['id'],token,data,admit_output=writer)
    assert s.accept_output(row['id'],token,data,admit_output=writer)==receipt
    assert len(writes)==1 and writes[0][:2]==(row['user_id'],row['id'])
    assert writes[0][3]==hashlib.sha256(data).hexdigest()
    with pytest.raises(PermissionError):s.accept_output(row['id'],token,output(exit_code=1),admit_output=writer)
    for op in ('worker','input'):
        with pytest.raises(PermissionError):s.authorize(row['id'],token,operation=op)


def test_uncertain_output_callback_stays_claimed_without_retry_side_effect(service):
    s,row,token,_,_=service;writes=[]
    def uncertain(*args):writes.append(args);raise TimeoutError('synthetic write uncertainty')
    with pytest.raises(TimeoutError):s.accept_output(row['id'],token,output(),admit_output=uncertain)
    with pytest.raises(PermissionError):s.accept_output(row['id'],token,output(),admit_output=uncertain)
    assert len(writes)==1
    with s._transaction() as c:assert c.execute('SELECT state FROM pilot_transfer_leases').fetchone()[0]=='uploading'
    assert s.ledger.owned(row['user_id'],row['id'])['state']=='submitting'


def test_concurrent_output_has_only_one_durable_admission(service):
    s,row,token,_,_=service;writes=[];data=output()
    def send(_):
        try:return s.accept_output(row['id'],token,data,admit_output=lambda *a:writes.append(a))
        except PermissionError:return None
    with ThreadPoolExecutor(max_workers=4) as pool:answers=list(pool.map(send,range(4)))
    assert len(writes)==1 and any(answers)


def test_runtime_overrun_refused_before_any_workspace_write(service):
    s,row,token,_,_=service;writes=[]
    with pytest.raises(PermissionError):s.accept_output(row['id'],token,output(runtime_seconds=66),admit_output=lambda *a:writes.append(a))
    assert not writes


@pytest.mark.parametrize('changes',[{'model_processes_stopped':False},{'model_uid':0},{'runtime_seconds':float('nan')},
    {'runtime_seconds':611},{'exit_code':'0'},{'timed_out':1},{'log_bytes_forwarded':2*1024**2+1}])
def test_invalid_supervisor_receipts_refused(changes):
    with pytest.raises(ValueError):validate_result(output(**changes))


@pytest.mark.parametrize('entries',[[('../escape','x')],[('a','x'),('a','y')],[('no-receipt','{}')]])
def test_malformed_result_archive_is_refused(entries):
    with pytest.raises(ValueError):validate_result(archive(entries))

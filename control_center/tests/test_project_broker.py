"""Injected fake SDK acceptance: never contacts AWS, discovers credentials or pays."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace
import uuid
import pytest
from control_center.services.project_broker import PilotSubmissionBroker,validate_frozen_input
from control_center.services.project_funding import FundedRun,ProjectFundingLedger
from control_center.services.project_transfer import PilotTransferLeases
from control_center.tests.test_project_funding import env
from control_center.tests.test_project_transfer import archive
from control_center.tests.test_project_execution import profile
from control_center.services.project_results import PilotResultArchives,ResultArchiveBinding
from control_center.tests.test_project_results import FakeS3


class FakeBatch:
    def __init__(self,fail=None):
        self.meta=SimpleNamespace(region_name='us-east-2',config=SimpleNamespace(retries={'total_max_attempts':1}))
        self.fail,self.calls,self.definition=fail,[],None;self.on_describe=None;self.on_submit=None;self.job=None
    def register_job_definition(self,**kwargs):
        self.calls.append(('register',deepcopy(kwargs)))
        if self.fail=='register':raise PermissionError('synthetic secret must never be echoed')
        self.definition=deepcopy(kwargs)
        arn='arn:aws:batch:us-east-2:123456789012:job-definition/'+kwargs['jobDefinitionName']+':1'
        self.definition.update(jobDefinitionArn=arn,revision=1,status='ACTIVE')
        return {'jobDefinitionArn':arn,'revision':1}
    def describe_job_definitions(self,**kwargs):
        self.calls.append(('describe',kwargs))
        if self.on_describe:self.on_describe(self.definition)
        if self.fail=='describe':raise TimeoutError('synthetic secret must never be echoed')
        return {'jobDefinitions':[deepcopy(self.definition)]}
    def submit_job(self,**kwargs):
        self.calls.append(('submit',kwargs))
        if self.on_submit:self.on_submit()
        if self.fail=='submit':raise TimeoutError('AWS may already have accepted this synthetic request')
        return {'jobId':str(uuid.uuid4())}

    def describe_jobs(self,**kwargs):
        self.calls.append(('describe_job',kwargs));return {'jobs':[deepcopy(self.job)] if self.job else []}
    def terminate_job(self,**kwargs):
        self.calls.append(('terminate',kwargs))
        if self.fail=='terminate':raise TimeoutError('synthetic uncertain termination')
        return {}


class FakeSsm:
    def __init__(self,fail=False):self.meta=SimpleNamespace(region_name='us-east-2');self.fail=fail;self.calls=[]
    def put_parameter(self,**kwargs):
        self.calls.append(kwargs)
        if self.fail:raise PermissionError('synthetic private value must not leak')
        return {'Version':1,'Tier':'Standard'}


@pytest.fixture
def broker(env):
    source=b'# synthetic reviewed worker\n';binding=ResultArchiveBinding('123456789012','us-east-2','synthetic-pilot-results','broker/pilot-results/')
    p=profile(worker_sha256=hashlib.sha256(source).hexdigest(),result_archive_review_sha256=binding.fingerprint)
    policy=replace(env[7],execution_profile=p.profile_id,image_digest=p.image_digest)
    ledger=ProjectFundingLedger(env[1],policy,admission_enabled=True)
    entries=[(name,'print("synthetic model")\n') for name in ('run.py','cryostack_icepack_runner.py','cryostack_icepack_export.py','cryostack_icepack_postprocess.py')]
    data=archive(entries);run=FundedRun('icepack',60,hashlib.sha256(data).hexdigest(),hashlib.sha256(entries[0][1].encode()).hexdigest())
    row=ledger.reserve(env[5],request_key='broker',run=run)
    leases=PilotTransferLeases(ledger,p,key=b'k'*32,worker_source=source,enabled=True)
    batch=FakeBatch();ssm=FakeSsm()
    retained=PilotResultArchives(ledger,p,binding,s3=FakeS3(),enabled=True)
    b=PilotSubmissionBroker(ledger,p,leases,batch=batch,ssm=ssm,read_input=lambda *a:data,enabled=True,result_archives=retained)
    return b,row,data,run,env


def submit(broker):b,row,*_=broker;return b.submit(row['user_id'],row['id'])


def test_default_disabled_has_no_aws_calls(broker):
    b,row,*_=broker
    disabled=PilotSubmissionBroker(b.ledger,b.profile,b.leases,batch=b.batch,ssm=b.ssm,read_input=b.read_input)
    with pytest.raises(PermissionError):disabled.submit(row['user_id'],row['id'])
    assert not b.batch.calls and not b.ssm.calls


def test_single_exact_no_override_submission_and_private_parameter(broker):
    b,row,*_=broker;phases=[]
    def at_submit():
        phases.append(b.attempt_for_owner(row['user_id'],row['id'])['phase'])
    b.batch.on_submit=at_submit
    result=submit(broker)
    assert result['state']=='running' and result['external_job_id']
    assert phases==['submit_attempted']
    parameter=b.ssm.calls[0]
    assert parameter['Type']=='SecureString' and parameter['Tier']=='Standard' and parameter['Overwrite'] is False
    assert parameter['Name']=='/cryostack/pilot-transfer/'+row['id']
    assert len(parameter['Value'])==43
    definition=b.batch.calls[0][1]
    assert parameter['Value'] not in str(definition)
    assert 'jobRoleArn' not in definition['containerProperties']
    paid=b.batch.calls[-1][1]
    assert set(paid)=={'jobName','jobQueue','jobDefinition','tags'}
    assert paid['jobDefinition'].endswith(':1') and paid['jobQueue']==b.profile.queue_arn
    assert paid['tags']['cryostack:reservation']==row['id']
    before=len(b.batch.calls);assert submit(broker)==result
    assert len(b.batch.calls)==before and len(b.ssm.calls)==1


@pytest.mark.parametrize('retry',[{}, {'max_attempts':1},{'total_max_attempts':2,'max_attempts':0},{'total_max_attempts':True}])
def test_sdk_automatic_paid_retries_refused_before_submission(broker,retry):
    b,*_=broker;b.batch.meta.config.retries=retry
    with pytest.raises(PermissionError):submit(broker)
    assert not b.batch.calls and not b.ssm.calls


def test_region_and_transfer_binding_mismatch_refused(broker):
    b,*_=broker;b.ssm.meta.region_name='us-west-2'
    with pytest.raises(PermissionError):submit(broker)
    assert not b.batch.calls


@pytest.mark.parametrize('failure',['parameter','register','describe','submit'])
def test_any_uncertain_cloud_step_retains_hold_and_never_retries_paid_api(broker,failure):
    b,row,*_=broker;b.ssm.fail=failure=='parameter';b.batch.fail=failure
    with pytest.raises(RuntimeError) as error:submit(broker)
    assert 'synthetic secret' not in str(error.value) and 'synthetic private' not in str(error.value)
    state=b.ledger.owned(row['user_id'],row['id']);assert state['state']=='submitting'
    n=len(b.batch.calls);m=len(b.ssm.calls)
    assert submit(broker)['state']=='submitting'
    assert len(b.batch.calls)==n and len(b.ssm.calls)==m
    with b.ledger._transaction() as db:
        assert db.execute('SELECT reserved FROM allocation_accounts WHERE user_id=?',(row['user_id'],)).fetchone()[0]==row['ceiling']
    if failure=='submit':assert b.attempt_for_owner(row['user_id'],row['id'])['phase']=='submit_attempted'
    else:assert not any(call[0]=='submit' for call in b.batch.calls)


@pytest.mark.parametrize('mutation',[
    lambda definition:definition['containerProperties'].update(jobRoleArn='broad-owner-role'),
    lambda definition:definition.update(retryStrategy={'attempts':2}),
    lambda definition:definition.update(jobDefinitionArn='arn:aws:batch:us-west-2:999999999999:job-definition/foreign:1'),
    lambda definition:definition['containerProperties'].update(command=['arbitrary','command']),
])
def test_cloud_definition_drift_refused_before_any_paid_request(broker,mutation):
    b,*_=broker;b.batch.on_describe=mutation
    with pytest.raises(RuntimeError):submit(broker)
    assert not any(call[0]=='submit' for call in b.batch.calls)


@pytest.mark.parametrize('change',['approval','pool','admission'])
def test_current_approval_pool_and_admission_rechecked_immediately_before_paid_request(broker,change):
    b,row,_,_,env=broker
    def pause(definition):
        if change=='admission':b.ledger.enabled=False;return
        with b.ledger._transaction() as c:
            if change=='approval':c.execute("UPDATE account_status SET status='suspended' WHERE user_id=?",(row['user_id'],))
            else:c.execute('UPDATE allocation_pools SET active=0')
    b.batch.on_describe=pause
    with pytest.raises(RuntimeError):submit(broker)
    assert not any(call[0]=='submit' for call in b.batch.calls)


def test_other_owner_and_changed_frozen_bytes_refused_before_any_cloud_call(broker):
    b,row,*_=broker
    with pytest.raises(PermissionError):b.submit('other-owner',row['id'])
    b.read_input=lambda *args:b'changed staging'
    with pytest.raises(PermissionError):submit(broker)
    assert not b.batch.calls and not b.ssm.calls
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='reserved'


@pytest.mark.parametrize('name',['../escape','outputs/old','tmp/old','home/private','/absolute','a\\b'])
def test_bad_input_paths_refused_before_claim_or_cloud(broker,name):
    b,row,data,run,_=broker
    malformed=archive([('run.py','print(1)'),(name,'x')])
    changed=replace(run,input_sha256=hashlib.sha256(malformed).hexdigest())
    with pytest.raises(ValueError):validate_frozen_input(malformed,changed)


def test_script_digest_syntax_and_missing_helpers_refused_before_claim(broker):
    b,row,data,run,_=broker
    with pytest.raises(PermissionError):validate_frozen_input(data,replace(run,script_sha256='f'*64))
    incomplete=archive([('run.py','this is not valid Python !')])
    with pytest.raises(ValueError):validate_frozen_input(incomplete,replace(run,input_sha256=hashlib.sha256(incomplete).hexdigest()))
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='reserved'


def known_job(broker,*,status='RUNNING',created=1800000,started=1900000,stopped=0):
    b,row,*_=broker;result=submit(broker);b.supervision_enabled=True
    attempt=b.attempt_for_owner(row['user_id'],row['id'])
    b.batch.job=dict(jobId=result['external_job_id'],jobArn=f'arn:aws:batch:us-east-2:123456789012:job/{result["external_job_id"]}',jobName='cryostack-pilot-'+row['id'],jobQueue=b.profile.queue_arn,jobDefinition=attempt['definition_arn'],tags=b.batch.definition['tags'],status=status,createdAt=created,startedAt=started,stoppedAt=stopped)
    return b,row


def test_supervision_requires_explicit_separate_activation(broker):
    b,row,*_=broker;submit(broker);before=len(b.batch.calls)
    with pytest.raises(PermissionError):b.watch_reservation(row['id'],now=2000)
    assert len(b.batch.calls)==before


def test_running_observation_and_terminal_receipt_never_release_or_charge_allowance(broker):
    b,row=known_job(broker)
    assert not b.watch_reservation(row['id'],now=2000)['terminal_confirmed']
    b.batch.job.update(status='SUCCEEDED',stoppedAt=1999000)
    result=b.watch_reservation(row['id'],now=2000)
    assert result['terminal_confirmed'] and len(result['terminal_evidence_sha256'])==64
    assert result['allowance_settled'] is False
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='running'
    assert not any(name=='terminate' for name,_ in b.batch.calls)


@pytest.mark.parametrize('status',['SUBMITTED','PENDING','RUNNABLE','STARTING'])
def test_startup_watchdog_requests_stop_with_backoff_but_retains_hold(broker,status):
    b,row=known_job(broker,status=status,created=1000000,started=0)
    assert b.watch_reservation(row['id'],now=2000)['termination_requested']
    assert not b.watch_reservation(row['id'],now=2005)['termination_requested']
    assert b.watch_reservation(row['id'],now=2030)['termination_requested']
    assert len([c for c in b.batch.calls if c[0]=='terminate'])==2
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='running'


def test_runtime_watchdog_and_admission_pause_are_distinct(broker):
    b,row=known_job(broker,created=1000000,started=1500000)
    b.enabled=False;b.ledger.enabled=False
    result=b.watch_reservation(row['id'],now=2000)
    assert result['termination_requested'] and not result['terminal_confirmed']
    assert 'task allowance' in b.batch.calls[-1][1]['reason']


@pytest.mark.parametrize('change',['approval','pool'])
def test_suspended_or_disabled_allocation_requests_known_job_stop(broker,change):
    b,row=known_job(broker)
    with b.ledger._transaction() as c:
        if change=='approval':c.execute("UPDATE account_status SET status='suspended' WHERE user_id=?",(row['user_id'],))
        else:c.execute('UPDATE allocation_pools SET active=0')
    assert b.watch_reservation(row['id'],now=2000)['termination_requested']


@pytest.mark.parametrize('key,value',[('jobQueue','foreign-queue'),('jobId','foreign-id'),('jobArn','foreign-arn'),('jobDefinition','foreign-definition'),('jobName','foreign-name'),('tags',{})])
def test_unowned_or_drifted_job_never_terminated_and_hold_retained(broker,key,value):
    b,row=known_job(broker);b.batch.job[key]=value
    with pytest.raises(PermissionError):b.watch_reservation(row['id'],now=2000)
    assert not any(c[0]=='terminate' for c in b.batch.calls)
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='running'


def test_unknown_job_or_inconsistent_terminal_timestamps_do_not_settle(broker):
    b,row=known_job(broker,status='FAILED',stopped=0)
    with pytest.raises(ValueError):b.watch_reservation(row['id'],now=2000)
    b.batch.job=None
    with pytest.raises(RuntimeError):b.watch_reservation(row['id'],now=2000)
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='running'


def test_uncertain_termination_is_not_completion_or_released_funds(broker):
    b,row=known_job(broker,created=1000000,started=0,status='STARTING');b.batch.fail='terminate'
    with pytest.raises(RuntimeError):b.watch_reservation(row['id'],now=2000)
    assert not b.watch_reservation(row['id'],now=2001)['termination_requested']
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='running'


def test_all_helpers_present_but_invalid_python_is_refused_before_claim(broker):
    b,row,data,run,_=broker
    names=('run.py','cryostack_icepack_runner.py','cryostack_icepack_export.py','cryostack_icepack_postprocess.py')
    script='invalid syntax !'
    malformed=archive([(name,script if name=='run.py' else 'pass') for name in names])
    changed=replace(run,input_sha256=hashlib.sha256(malformed).hexdigest(),script_sha256=hashlib.sha256(script.encode()).hexdigest())
    with pytest.raises(SyntaxError):validate_frozen_input(malformed,changed)
    assert not b.batch.calls and not b.ssm.calls


def test_input_expansion_and_duplicate_paths_are_refused_before_claim(broker,monkeypatch):
    b,row,data,run,_=broker
    from control_center.services import project_broker as module
    malformed=archive([('run.py','x'*2048)])
    monkeypatch.setattr(module,'MAX_BYTES',1024)
    with pytest.raises(ValueError):validate_frozen_input(malformed,replace(run,input_sha256=hashlib.sha256(malformed).hexdigest()))
    duplicate=archive([('run.py','pass'),('run.py','pass')])
    with pytest.raises(ValueError):validate_frozen_input(duplicate,replace(run,input_sha256=hashlib.sha256(duplicate).hexdigest()))


@pytest.mark.parametrize('source',[b'',b'   \n',b'#'+b'x'*(1024**2)])
def test_empty_or_oversized_script_refused_without_a_cloud_call(broker,source):
    b,row,data,run,_=broker
    names=('run.py','cryostack_icepack_runner.py','cryostack_icepack_export.py','cryostack_icepack_postprocess.py')
    malformed=archive([(name,source if name=='run.py' else b'pass') for name in names])
    changed=replace(run,input_sha256=hashlib.sha256(malformed).hexdigest(),script_sha256=hashlib.sha256(source).hexdigest())
    with pytest.raises(ValueError):validate_frozen_input(malformed,changed)
    assert not b.batch.calls and not b.ssm.calls


@pytest.mark.parametrize('extra',[[('data','x'),('data/grid.json','{}')],[('run.py/','')]])
def test_file_directory_conflicts_are_refused_before_cloud(broker,extra):
    b,row,data,run,_=broker
    names=('run.py','cryostack_icepack_runner.py','cryostack_icepack_export.py','cryostack_icepack_postprocess.py')
    entries=[(name,b'pass') for name in names]
    if extra[0][0]=='run.py/':entries=entries[1:]
    malformed=archive(entries+extra)
    changed=replace(run,input_sha256=hashlib.sha256(malformed).hexdigest(),script_sha256=hashlib.sha256(b'pass').hexdigest())
    with pytest.raises(ValueError):validate_frozen_input(malformed,changed)
    assert not b.batch.calls and not b.ssm.calls



def test_paid_submission_requires_matching_enabled_durable_results(broker):
    b,row,*_=broker;b.result_archives.enabled=False
    with pytest.raises(PermissionError):submit(broker)
    assert not b.batch.calls and not b.ssm.calls
    assert b.ledger.owned(row['user_id'],row['id'])['state']=='reserved'


def test_result_binding_rechecked_after_cloud_preparation_before_paid_call(broker):
    b,row,*_=broker
    b.batch.on_describe=lambda definition:setattr(b.result_archives,'enabled',False)
    with pytest.raises(RuntimeError):submit(broker)
    assert not any(c[0]=='submit' for c in b.batch.calls)

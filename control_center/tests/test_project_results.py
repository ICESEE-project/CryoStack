"""Durable result semantics with injected in-memory S3; zero AWS calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import hashlib,io,uuid
from types import SimpleNamespace
import pytest
from control_center.services.project_funding import ProjectFundingLedger
from control_center.services.project_results import PilotResultArchives,ResultArchiveBinding
from control_center.tests.test_project_funding import env
from control_center.tests.test_project_execution import profile
from control_center.tests.test_project_transfer import output


class FakeS3:
    def __init__(self):
        self.meta=SimpleNamespace(region_name='us-east-2',config=SimpleNamespace(retries={'total_max_attempts':1}))
        self.objects={};self.calls=[];self.lose_response=False;self.last_body=None
    def put_object(self,**kw):
        self.calls.append(('put',kw));key=(kw['Bucket'],kw['Key'])
        if key in self.objects:raise RuntimeError('synthetic condition conflict')
        assert kw['IfNoneMatch']=='*' and kw['ExpectedBucketOwner']=='123456789012'
        self.objects[key]=deepcopy(kw)
        if self.lose_response:raise TimeoutError('synthetic response lost after durable upload')
        return {'ChecksumSHA256':kw['ChecksumSHA256']}
    def head_object(self,**kw):
        self.calls.append(('head',kw));record=self.objects.get((kw['Bucket'],kw['Key']))
        if record is None:raise FileNotFoundError('synthetic missing object')
        return {'ContentLength':len(record['Body']),'ContentType':record['ContentType'],
                'Metadata':deepcopy(record['Metadata']),'ChecksumSHA256':record['ChecksumSHA256']}
    def get_object(self,**kw):
        self.calls.append(('get',kw));record=self.objects[(kw['Bucket'],kw['Key'])]
        self.last_body=io.BytesIO(record['Body'])
        return {'ContentLength':len(record['Body']),'Body':self.last_body}


@pytest.fixture
def results(env):
    b=ResultArchiveBinding('123456789012','us-east-2','synthetic-pilot-results','cryostack/pilot-results/')
    p=profile(result_archive_review_sha256=b.fingerprint)
    policy=replace(env[7],execution_profile=p.profile_id,image_digest=p.image_digest)
    ledger=ProjectFundingLedger(env[1],policy,admission_enabled=True)
    run=env[9];row=ledger.reserve(env[5],request_key='result',run=run)
    claim=ledger.claim_submission(env[5],row['id']);ledger.record_submission(row['id'],submission_token=claim['submission_token'],external_job_id=str(uuid.uuid4()))
    client=FakeS3();store=PilotResultArchives(ledger,p,b,s3=client,enabled=True)
    data=output();digest=hashlib.sha256(data).hexdigest()
    return store,row,client,data,digest,env


def stage(results):s,row,_,data,digest,_=results;return s.stage(row['user_id'],row['id'],data,digest)


def test_default_disabled_and_result_binding_frozen_into_policy(results):
    s,row,client,data,digest,_=results
    disabled=PilotResultArchives(s.ledger,s.profile,s.binding,s3=client)
    with pytest.raises(PermissionError):disabled.stage(row['user_id'],row['id'],data,digest)
    with pytest.raises(PermissionError):PilotResultArchives(s.ledger,s.profile,replace(s.binding,bucket='different-bucket'),s3=client,enabled=True)
    assert not client.calls
    assert replace(s.profile,result_archive_review_sha256='f'*64).profile_id!=s.profile.profile_id


def test_stages_once_with_exact_owner_prefix_checksum_and_no_credentials_in_result(results):
    s,row,client,data,digest,_=results
    result=stage(results);assert result=={'retained':True,'workspace_admitted':False}
    call=client.calls[0][1]
    assert call['Key']==s.binding.prefix+hashlib.sha256(row['user_id'].encode()).hexdigest()+'/'+row['id']+'/results.zip'
    assert call['Metadata']['sha256']==digest and call['ExpectedBucketOwner']==s.binding.account_id
    assert call['Body']==data and call['IfNoneMatch']=='*'
    assert s.binding.bucket not in str(result) and s.binding.account_id not in str(result)
    assert stage(results)==result
    assert len([c for c in client.calls if c[0]=='put'])==1
    assert s.read(row['user_id'],row['id'])==data and client.last_body.closed


def test_wrong_owner_and_changed_bytes_refused_before_cloud(results):
    s,row,client,data,digest,env=results
    with pytest.raises(PermissionError):s.stage(env[6],row['id'],data,digest)
    with pytest.raises(ValueError):s.stage(row['user_id'],row['id'],data,'f'*64)
    assert not client.calls
    stage(results)
    with pytest.raises(PermissionError):s.read(env[6],row['id'])
    changed=output(exit_code=1)
    with pytest.raises(PermissionError):s.stage(row['user_id'],row['id'],changed,hashlib.sha256(changed).hexdigest())
    assert len([c for c in client.calls if c[0]=='put'])==1


def test_lost_upload_response_is_recovered_by_checksum_read_without_another_put(results):
    s,row,client,data,_,_=results;client.lose_response=True
    with pytest.raises(RuntimeError):stage(results)
    assert s._record(row['user_id'],row['id'])['state']=='uploading'
    assert s.read(row['user_id'],row['id'])==data
    assert s._record(row['user_id'],row['id'])['state']=='staged'
    assert len([c for c in client.calls if c[0]=='put'])==1
    assert s.ledger.owned(row['user_id'],row['id'])['state']=='running'


def test_full_workspace_retains_cloud_results_and_can_import_after_capacity_is_restored(results):
    from cryostack_src.workspace.storage_policy import QuotaExceeded
    s,row,client,data,_,_=results;stage(results);writes=[]
    def full(*args):raise QuotaExceeded('Synthetic workspace full',None)
    result=s.import_to_workspace(row['user_id'],row['id'],admit_output=full)
    assert result=={'retained':True,'workspace_admitted':False,'reason':'workspace_capacity'}
    assert s.read(row['user_id'],row['id'])==data
    assert s.import_to_workspace(row['user_id'],row['id'],admit_output=lambda *args:writes.append(args))=={'retained':True,'workspace_admitted':True}
    assert writes[0][:2]==(row['user_id'],row['id']) and writes[0][2]==data
    assert s.import_to_workspace(row['user_id'],row['id'],admit_output=lambda *args:writes.append(args))['workspace_admitted']
    assert len(writes)==1 and len([c for c in client.calls if c[0]=='put'])==1


def test_uncertain_workspace_write_never_repeats_admission_and_keeps_download(results):
    s,row,client,data,_,_=results;stage(results);writes=[]
    def uncertain(*args):writes.append(args);raise TimeoutError('Synthetic interrupted commit')
    with pytest.raises(TimeoutError):s.import_to_workspace(row['user_id'],row['id'],admit_output=uncertain)
    assert s._record(row['user_id'],row['id'])['state']=='importing'
    with pytest.raises(PermissionError):s.import_to_workspace(row['user_id'],row['id'],admit_output=uncertain)
    assert len(writes)==1 and s.read(row['user_id'],row['id'])==data


@pytest.mark.parametrize('damage',['metadata','checksum','body'])
def test_foreign_or_corrupt_cloud_object_is_refused_and_stream_closed(results,damage):
    s,row,client,data,_,_=results;stage(results);record=next(iter(client.objects.values()))
    if damage=='metadata':record['Metadata']['owner']='foreign-owner'
    elif damage=='checksum':record['ChecksumSHA256']='foreign-checksum'
    else:record['Body']=b'x'+record['Body'][1:]
    with pytest.raises(PermissionError):s.read(row['user_id'],row['id'])
    if damage=='body':assert client.last_body.closed


def test_concurrent_workspace_import_has_one_admission(results):
    s,row,_,_,_,_=results;stage(results);writes=[]
    def attempt(_):
        try:return s.import_to_workspace(row['user_id'],row['id'],admit_output=lambda *a:writes.append(a))
        except PermissionError:return None
    with ThreadPoolExecutor(max_workers=4) as threads:answers=list(threads.map(attempt,range(4)))
    assert len(writes)==1 and any(a and a['workspace_admitted'] for a in answers)


def test_suspension_blocks_result_reads_without_deleting_retained_data(results):
    s,row,client,_,_,_=results;stage(results);before=len(client.calls)
    with s.ledger._transaction() as c:c.execute("UPDATE account_status SET status='suspended' WHERE user_id=?",(row['user_id'],))
    with pytest.raises(PermissionError):s.read(row['user_id'],row['id'])
    assert len(client.calls)==before and len(client.objects)==1


@pytest.mark.parametrize('changes',[{'bucket':'1.2.3.4'},{'bucket':'bad_bucket'},{'prefix':'../pilot-results/'},
    {'prefix':'unscoped/'},{'account_id':'wrong'},{'region':'wrong'}])
def test_unreviewed_namespace_refused(changes):
    values=dict(account_id='123456789012',region='us-east-2',bucket='synthetic-results',prefix='pilot-results/');values.update(changes)
    with pytest.raises(ValueError):ResultArchiveBinding(**values)


def test_requests_validate_against_installed_s3_sdk_shapes(results):
    session_module=pytest.importorskip('botocore.session')
    from botocore.validate import validate_parameters
    s,_,client,_,_,_=results;stage(results);s.read(results[1]['user_id'],results[1]['id'])
    model=session_module.get_session().get_service_model('s3')
    operations={'put':'PutObject','head':'HeadObject','get':'GetObject'}
    for name,parameters in client.calls:validate_parameters(parameters,model.operation_model(operations[name]).input_shape)



def test_result_runtime_overrun_is_refused_before_cloud(results):
    s,row,client,_,_,_=results;data=output(runtime_seconds=66)
    with pytest.raises(PermissionError):s.stage(row['user_id'],row['id'],data,hashlib.sha256(data).hexdigest())
    assert not client.calls


def test_bad_importer_is_refused_without_cloud_lookup(results):
    s,row,client,_,_,_=results
    with pytest.raises(ValueError):s.import_to_workspace(row['user_id'],row['id'],admit_output=None)
    assert not client.calls

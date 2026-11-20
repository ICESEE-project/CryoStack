"""Immutable execution/least-privilege contract. No AWS calls or activation."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import pytest
from control_center.services.project_execution import PilotExecutionProfile, BOOTSTRAP
from control_center.services.project_funding import FundingPolicy, FundedRun

ACCOUNT='123456789012'
REGION='us-east-2'
RESERVATION='a'*32


def profile(**changes):
    values=dict(account_id=ACCOUNT,region=REGION,
        queue_arn=f'arn:aws:batch:{REGION}:{ACCOUNT}:job-queue/cryostack-queue',
        execution_role_arn=f'arn:aws:iam::{ACCOUNT}:role/cryostack-pilot-execution',
        image=f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/cryostack-icepack@sha256:'+('b'*64),
        worker_sha256='c'*64,transfer_origin='https://synthetic.example',network_review_id='offline-review')
    values.update(changes)
    return PilotExecutionProfile(**values)


def binding(p=None):
    p=p or profile()
    policy=FundingPolicy('pilot','pool',p.profile_id,p.image_digest,10,500,max_seconds=600)
    args=dict(reservation=RESERVATION,user_id='synthetic-owner',
        run=FundedRun('icepack',60,'d'*64,'e'*64),
        transfer_parameter_arn=f'arn:aws:ssm:{REGION}:{ACCOUNT}:parameter/cryostack/pilot-transfer/{RESERVATION}')
    return p,policy,args


def test_profile_binds_all_resource_code_role_network_and_price_review():
    p=profile()
    assert p.profile_id=='pilot_'+p.fingerprint
    assert p.minimum_hold_cents==7
    for key,value in dict(worker_sha256='f'*64,network_review_id='another-review',
            task_timeout_seconds=600,price_review_id='revised-pricing',
            ancillary_allowance_cents=3,transfer_origin='https://other.example').items():
        assert replace(p,**{key:value}).profile_id!=p.profile_id


@pytest.mark.parametrize('change',[
    {'account_id':'bad'}, {'region':'us-east-2/evil'},
    {'queue_arn':'arn:aws:batch:us-east-2:999999999999:job-queue/cryostack-queue'},
    {'execution_role_arn':f'arn:aws:iam::{ACCOUNT}:role/existing-broad-owner-role'},
    {'image':f'{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/cryostack-icepack:latest'},
    {'worker_sha256':'missing'}, {'network_review_id':''},
    {'max_model_seconds':True}, {'max_model_seconds':601},
    {'task_timeout_seconds':360}, {'task_timeout_seconds':901},
    {'startup_timeout_seconds':901}, {'ancillary_allowance_cents':0},
    {'compute_rate_usd_per_hour':'NaN'}, {'compute_rate_usd_per_hour':'0'},
    {'compute_rate_usd_per_hour':'11'}, {'transfer_origin':'http://synthetic.example'},
    {'transfer_origin':'https://token@synthetic.example'},
    {'transfer_origin':'https://synthetic.example/path'},
])
def test_unreviewed_profile_forms_are_refused(change):
    with pytest.raises(ValueError):profile(**change)


def test_policy_reuse_after_profile_or_image_change_is_refused():
    p,policy,args=binding()
    for changed in (replace(policy,execution_profile='old-review'),replace(policy,image_digest='sha256:'+'f'*64),replace(policy,ceiling_cents=1)):
        with pytest.raises(PermissionError):p.definition(changed,**args)


def test_bounded_no_task_role_definition_contains_only_secret_reference():
    p,policy,args=binding();result=p.definition(policy,**args);c=result['containerProperties']
    assert 'jobRoleArn' not in c
    assert c['executionRoleArn']==p.execution_role_arn
    assert c['secrets']==[{'name':'CRYOSTACK_TRANSFER_TOKEN','valueFrom':args['transfer_parameter_arn']}]
    assert all(v['name']!='CRYOSTACK_TRANSFER_TOKEN' for v in c['environment'])
    assert result['retryStrategy']=={'attempts':1}
    assert result['timeout']=={'attemptDurationSeconds':480}
    assert c['user']=='0' and not c['privileged']
    assert 'synthetic-owner' not in str(result)
    assert c['command']==['python3','-c',BOOTSTRAP]
    compile(BOOTSTRAP,'bootstrap','exec')
    assert len(BOOTSTRAP.encode())<4096


@pytest.mark.parametrize('suffix',['/other','',':version:1'])
def test_transfer_parameter_is_exactly_reservation_and_account_scoped(suffix):
    p,policy,args=binding();args['transfer_parameter_arn']+=suffix
    if not suffix:args['transfer_parameter_arn']=args['transfer_parameter_arn'].replace(ACCOUNT,'999999999999')
    with pytest.raises(ValueError):p.definition(policy,**args)


@pytest.mark.parametrize('run',[FundedRun('issm',60,'d'*64,'e'*64),FundedRun('icepack',361,'d'*64,'e'*64)])
def test_other_scientific_model_and_unqualified_runtime_refused(run):
    p,policy,args=binding();args['run']=run
    with pytest.raises((ValueError,PermissionError)):p.definition(policy,**args)


def test_aws_response_normalization_preserves_strict_review():
    p,policy,args=binding();actual=p.definition(policy,**args)
    actual.update(jobDefinitionArn='arn:aws:batch:us-east-2:123456789012:job-definition/cryostack-pilot-'+RESERVATION+':1',revision=1,status='ACTIVE',parameters={})
    c=actual['containerProperties'];c.update(volumes=[],mountPoints=[],ulimits=[])
    for name in ('environment','resourceRequirements'):c[name].reverse()
    assert p.verify_definition(actual,policy,**args)


@pytest.mark.parametrize('mutation',[
    lambda d:d['containerProperties'].update(jobRoleArn='arn:aws:iam::123456789012:role/owner'),
    lambda d:d['containerProperties'].update(image='mutable:latest'),
    lambda d:d['containerProperties'].update(privileged=True),
    lambda d:d['containerProperties'].update(user='65534'),
    lambda d:d['containerProperties']['environment'].append({'name':'AWS_ACCESS_KEY_ID','value':'synthetic'}),
    lambda d:d['containerProperties']['environment'].append(deepcopy(d['containerProperties']['environment'][0])),
    lambda d:d['containerProperties']['secrets'][0].update(valueFrom='other-secret'),
    lambda d:d.update(retryStrategy={'attempts':2}),
    lambda d:d.update(nodeProperties={}),
    lambda d:d.update(status='INACTIVE'),
    lambda d:d.update(parameters={'unreviewed':'value'}),
])
def test_aws_definition_drift_is_refused_before_submission(mutation):
    p,policy,args=binding();actual=p.definition(policy,**args);mutation(actual)
    with pytest.raises(PermissionError):p.verify_definition(actual,policy,**args)


def test_submit_binding_requires_authoritative_exact_immutable_revision():
    p,policy,args=binding();actual=p.definition(policy,**args)
    with pytest.raises(PermissionError):p.verified_definition_arn(actual,policy,**args)
    name=actual['jobDefinitionName']
    actual.update(jobDefinitionArn=f'arn:aws:batch:{REGION}:{ACCOUNT}:job-definition/{name}:2',revision=2,status='ACTIVE')
    assert p.verified_definition_arn(actual,policy,**args)==actual['jobDefinitionArn']
    for changed in (dict(actual,revision=True),dict(actual,revision=3),dict(actual,jobDefinitionArn=actual['jobDefinitionArn'].replace(ACCOUNT,'999999999999'))):
        with pytest.raises(PermissionError):p.verify_definition(changed,policy,**args)


def test_generated_requests_match_installed_aws_sdk_shapes_without_network():
    session_module=pytest.importorskip('botocore.session')
    from botocore.validate import validate_parameters
    session=session_module.get_session()
    p,policy,args=binding();definition=p.definition(policy,**args)
    arn=f'arn:aws:batch:{REGION}:{ACCOUNT}:job-definition/'+definition['jobDefinitionName']+':1'
    requests=[('batch','RegisterJobDefinition',definition),
        ('batch','DescribeJobDefinitions',{'jobDefinitions':[arn]}),
        ('batch','SubmitJob',{'jobName':'cryostack-pilot-'+RESERVATION,'jobQueue':p.queue_arn,'jobDefinition':arn,'tags':definition['tags']}),
        ('batch','DescribeJobs',{'jobs':['12345678-1234-1234-1234-123456789012']}),
        ('batch','TerminateJob',{'jobId':'12345678-1234-1234-1234-123456789012','reason':'Synthetic offline supervision'}),
        ('ssm','PutParameter',{'Name':'/cryostack/pilot-transfer/'+RESERVATION,'Value':'x'*43,'Type':'SecureString','Tier':'Standard','Overwrite':False})]
    for service,name,parameters in requests:
        model=session.get_service_model(service).operation_model(name)
        validate_parameters(parameters,model.input_shape)

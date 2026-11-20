"""Immutable pilot execution review. Pure builders; no AWS client or activation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import re
from urllib.parse import urlsplit

from .project_funding import FundingPolicy, FundedRun

# Small enough for Batch's command limit. Fetch trusted worker source separately
# from model inputs, verify its reviewed digest, then execute in the root supervisor.
BOOTSTRAP = '''import hashlib,json,os,re,ssl,urllib.request
from urllib.parse import urlsplit
s=json.loads(os.environ['CRYOSTACK_PILOT_SPEC']);o=s['origin'];r=s['reservation'];p=urlsplit(o)
if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/') or not re.fullmatch('[a-f0-9]{32}',r):raise SystemExit('Invalid reviewed transfer origin')
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):raise PermissionError('Worker redirects refused')
u=urllib.request.Request(o.rstrip('/')+'/api/pilot-transfer/'+r+'/worker',headers={'Authorization':'Bearer '+os.environ['CRYOSTACK_TRANSFER_TOKEN']})
a=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
with a.open(u,timeout=30) as response:b=response.read(65537)
if len(b)>65536 or hashlib.sha256(b).hexdigest()!=os.environ['CRYOSTACK_WORKER_SHA256']:raise SystemExit('Worker digest differs from review')
exec(compile(b,'reviewed-pilot-worker','exec'),{'__name__':'__main__'})
'''


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Expected a SHA-256 digest')
    return value


def _int(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('Reviewed execution bound is invalid')


@dataclass(frozen=True)
class PilotExecutionProfile:
    """Trusted operator review; never constructed from a participant request.

    The profile identifier hashes every setting and the bootstrap. FundingPolicy
    binds this identifier, so changing an account, role, worker or bound forces a
    new funding review. A network_review_id is an operator attestation, not an
    automated network/egress audit. No live resources are created by this class.
    """
    account_id: str
    region: str
    queue_arn: str
    execution_role_arn: str
    image: str
    worker_sha256: str
    transfer_origin: str
    network_review_id: str
    max_model_seconds: int = 360
    task_timeout_seconds: int = 480
    startup_timeout_seconds: int = 900
    ancillary_allowance_cents: int = 2
    compute_rate_usd_per_hour: str = '0.11985'
    price_review_id: str = 'aws-ohio-fargate-20261019'
    result_archive_review_sha256: str | None = None

    def __post_init__(self):
        if not re.fullmatch(r'[0-9]{12}', self.account_id or ''):
            raise ValueError('Reviewed AWS account is required')
        if not re.fullmatch(r'[a-z]{2}-[a-z]+-[1-9]', self.region or ''):
            raise ValueError('Reviewed AWS region is required')
        if self.queue_arn != f'arn:aws:batch:{self.region}:{self.account_id}:job-queue/cryostack-queue':
            raise ValueError('Only the reviewed account queue is supported')
        if not re.fullmatch(r'arn:aws:iam::'+self.account_id+r':role/cryostack-pilot-execution(?:-[A-Za-z0-9_-]+)?', self.execution_role_arn):
            raise ValueError('A separately reviewed pilot execution role is required')
        expected = re.escape(f'{self.account_id}.dkr.ecr.{self.region}.amazonaws.com/cryostack-icepack@sha256:')
        if not re.fullmatch(expected+r'[a-f0-9]{64}', self.image):
            raise ValueError('A pinned Icepack image in the reviewed account is required')
        _digest(self.worker_sha256)
        if self.result_archive_review_sha256 is not None:
            _digest(self.result_archive_review_sha256)
        origin = urlsplit(self.transfer_origin)
        if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
                or origin.path not in ('','/') or origin.query or origin.fragment):
            raise ValueError('A reviewed HTTPS gateway origin is required')
        for identifier in (self.network_review_id, self.price_review_id):
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identifier or ''):
                raise ValueError('Network and pricing review identifiers are required')
        _int(self.max_model_seconds, 1, 600)
        _int(self.task_timeout_seconds, max(60,self.max_model_seconds+30), 900)
        _int(self.startup_timeout_seconds, 60, 900)
        _int(self.ancillary_allowance_cents, 2, 100)
        if not isinstance(self.compute_rate_usd_per_hour,str):
            raise ValueError('Reviewed compute rate must be a decimal string')
        try:rate=Decimal(self.compute_rate_usd_per_hour)
        except Exception as error:raise ValueError('Invalid reviewed compute rate') from error
        if not rate.is_finite() or not Decimal('0') < rate <= Decimal('10'):
            raise ValueError('Invalid reviewed compute rate')

    @property
    def fingerprint(self):
        fields=asdict(self)
        fields['bootstrap_sha256']=hashlib.sha256(BOOTSTRAP.encode()).hexdigest()
        return hashlib.sha256(_canonical(fields).encode()).hexdigest()

    @property
    def profile_id(self):
        return 'pilot_'+self.fingerprint

    @property
    def image_digest(self):
        return 'sha256:'+self.image.rsplit('sha256:',1)[1]

    @property
    def minimum_hold_cents(self):
        duration=self.startup_timeout_seconds+self.task_timeout_seconds
        compute=Decimal(self.compute_rate_usd_per_hour)*Decimal(duration)/Decimal(3600)*100
        return int(compute.to_integral_value(rounding=ROUND_CEILING))+self.ancillary_allowance_cents

    def validate_funding(self, policy):
        if not isinstance(policy, FundingPolicy) or policy.execution_profile != self.profile_id:
            raise PermissionError('Funding policy does not bind this immutable execution review')
        if policy.image_digest != self.image_digest or policy.ceiling_cents < self.minimum_hold_cents:
            raise PermissionError('Reviewed image or funding hold is insufficient')

    def _spec(self, reservation, run):
        if not re.fullmatch(r'[a-f0-9]{32}', reservation or ''):
            raise ValueError('Canonical reservation identifier required')
        if not isinstance(run, FundedRun) or run.model != 'icepack':
            raise PermissionError('This worker qualifies Icepack only; ISSM licensing remains separate')
        _int(run.seconds,1,self.max_model_seconds)
        _digest(run.input_sha256);_digest(run.script_sha256)
        return dict(origin=self.transfer_origin,reservation=reservation,
                    input_sha256=run.input_sha256,script_sha256=run.script_sha256,
                    seconds=run.seconds,model=run.model)

    def definition(self, policy, *, reservation, user_id, run, transfer_parameter_arn):
        self.validate_funding(policy);run.validate(policy)
        spec=self._spec(reservation,run)
        parameter=f'arn:aws:ssm:{self.region}:{self.account_id}:parameter/cryostack/pilot-transfer/{reservation}'
        if transfer_parameter_arn != parameter:
            raise ValueError('Transfer parameter must belong to exactly this reviewed reservation')
        if not isinstance(user_id,str) or not user_id or len(user_id)>200:
            raise ValueError('Authenticated owner identity required')
        return {
            'jobDefinitionName':'cryostack-pilot-'+reservation,'type':'container',
            'platformCapabilities':['FARGATE'],'retryStrategy':{'attempts':1},
            'timeout':{'attemptDurationSeconds':self.task_timeout_seconds},
            'propagateTags':True,
            'tags':{'cryostack:pilot':'1','cryostack:reservation':reservation,
                    'cryostack:profile':self.profile_id,
                    'cryostack:owner':hashlib.sha256(user_id.encode()).hexdigest()},
            'containerProperties':{
                'image':self.image,'executionRoleArn':self.execution_role_arn,
                # jobRoleArn is deliberately absent. A model must never obtain
                # the owner's broad task-role credentials from ECS metadata.
                'command':['python3','-c',BOOTSTRAP],'user':'0','privileged':False,
                'readonlyRootFilesystem':False,
                'resourceRequirements':[{'type':'VCPU','value':'2'},{'type':'MEMORY','value':'8192'}],
                'ephemeralStorage':{'sizeInGiB':50},
                'fargatePlatformConfiguration':{'platformVersion':'1.4.0'},
                'runtimePlatform':{'operatingSystemFamily':'LINUX','cpuArchitecture':'X86_64'},
                'linuxParameters':{'initProcessEnabled':True},
                'networkConfiguration':{'assignPublicIp':'ENABLED'},
                'environment':[{'name':'CRYOSTACK_PILOT_SPEC','value':_canonical(spec)},
                               {'name':'CRYOSTACK_WORKER_SHA256','value':self.worker_sha256}],
                'secrets':[{'name':'CRYOSTACK_TRANSFER_TOKEN','valueFrom':transfer_parameter_arn}],
                'logConfiguration':{'logDriver':'awslogs','options':{
                    'awslogs-group':'/cryostack/pilot','awslogs-region':self.region,
                    'awslogs-stream-prefix':'pilot'}},
            },
        }

    def verify_definition(self, actual, policy, **binding):
        expected=self.definition(policy,**binding)
        allowed_top=set(expected)|{'jobDefinitionArn','revision','status','parameters','containerOrchestrationType'}
        if (set(actual)-allowed_top or actual.get('status','ACTIVE') != 'ACTIVE'
                or actual.get('parameters',{}) or actual.get('containerOrchestrationType','ECS')!='ECS'):
            raise PermissionError('Unreviewed job-definition properties')
        arn=actual.get('jobDefinitionArn');revision=actual.get('revision')
        if arn is not None or revision is not None:
            if type(revision) is not int or revision<1:
                raise PermissionError('Canonical immutable definition revision required')
            reviewed_arn=(f'arn:aws:batch:{self.region}:{self.account_id}:job-definition/'
                          +expected['jobDefinitionName']+':'+str(revision))
            if arn!=reviewed_arn:
                raise PermissionError('Definition ARN differs from the reviewed account/name/revision')
        # DescribeJobDefinitions includes explicit empty lists for omitted
        # retry rules and Linux settings. Only those exact defaults are inert.
        retry=actual.get('retryStrategy')
        if isinstance(retry,dict) and retry.get('evaluateOnExit')==[]:
            actual=dict(actual,retryStrategy={key:value for key,value in retry.items()
                                              if key!='evaluateOnExit'})
        for key,value in expected.items():
            if key=='containerProperties':continue
            if actual.get(key)!=value:raise PermissionError('Job definition differs from execution review')
        container=dict(actual.get('containerProperties') or {})
        for name,empty in (('volumes',[]),('mountPoints',[]),('ulimits',[])):
            if container.get(name)==empty:container.pop(name,None)
        linux=container.get('linuxParameters')
        if isinstance(linux,dict):
            container['linuxParameters']={key:value for key,value in linux.items()
                                          if key not in ('devices','tmpfs') or value!=[]}
        logging=container.get('logConfiguration')
        if isinstance(logging,dict) and logging.get('secretOptions')==[]:
            container['logConfiguration']={key:value for key,value in logging.items()
                                           if key!='secretOptions'}
        reviewed=dict(expected['containerProperties'])
        for name,key in (('environment','name'),('secrets','name'),('resourceRequirements','type')):
            values=container.get(name)
            if (not isinstance(values,list) or any(not isinstance(v,dict) or key not in v for v in values)
                    or len({v[key] for v in values})!=len(values)):
                raise PermissionError('Missing or duplicate reviewed container settings')
            container[name]=sorted(values,key=lambda v:v[key])
            reviewed[name]=sorted(reviewed[name],key=lambda v:v[key])
        if _canonical(container)!=_canonical(reviewed):
            raise PermissionError('Container image, role, command, secret or bounds differ from review')
        return True

    def verified_definition_arn(self,actual,policy,**binding):
        """Future broker submits this exact revision, never a mutable name/latest."""
        self.verify_definition(actual,policy,**binding)
        if actual.get('jobDefinitionArn') is None or actual.get('status')!='ACTIVE':
            raise PermissionError('Authoritative active immutable definition revision required')
        return actual['jobDefinitionArn']

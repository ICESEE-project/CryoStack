"""Disabled gateway-only pilot submission adapter with injected reviewed clients.

No credential discovery, public route or production wiring. Constructing it
performs no AWS call. An operator must review permissions/network, explicitly
provide no-retry Batch + regional SSM clients and owner-frozen input storage.
A submit timeout retains its hold; there is no automatic paid retry or settlement.
"""
from __future__ import annotations

import hashlib
import math
import io
import json
import re
import stat
import time
import zipfile

from .project_funding import FundedRun
from .project_transfer import MAX_BYTES,MAX_FILES
from .project_results import PilotResultArchives


def validate_frozen_input(data,run):
    """Refuse malformed/changed staging before even claiming a submission."""
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:
        raise ValueError('Input archive exceeds its allowance')
    if hashlib.sha256(data).hexdigest()!=run.input_sha256:
        raise PermissionError('Input bytes differ from the reviewed reservation')
    required={'run.py','cryostack_icepack_runner.py','cryostack_icepack_export.py','cryostack_icepack_postprocess.py'}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries=archive.infolist();names=set();size=0
        if not 1<=len(entries)<=MAX_FILES:raise ValueError('Invalid pilot input entry count')
        for entry in entries:
            name=entry.filename.rstrip('/');parts=name.split('/');mode=entry.external_attr>>16
            if (not name or '\\' in name or any(p in ('','.','..') for p in parts)
                    or parts[0] in ('outputs','home','tmp') or name in names
                    or stat.S_IFMT(mode) not in (0,stat.S_IFDIR,stat.S_IFREG) or entry.flag_bits&1):
                raise ValueError('Unsafe or reserved pilot input entry')
            names.add(name);size+=entry.file_size
            if size>MAX_BYTES:raise ValueError('Expanded pilot input exceeds allowance')
            with archive.open(entry) as stream:
                count=0
                while block:=stream.read(65536):
                    count+=len(block)
                    if count>entry.file_size:raise ValueError('Input expansion changed')
        if not required<=names:raise ValueError('Reviewed model script/export helpers required')
        kinds={entry.filename.rstrip('/'):entry.is_dir() for entry in entries}
        for name in names:
            parts=name.split('/')
            if any('/'.join(parts[:i]) in kinds and not kinds['/'.join(parts[:i])] for i in range(1,len(parts))):
                raise ValueError('Input file/directory prefixes conflict')
        if any(kinds[name] or archive.getinfo(name).file_size>1024**2 for name in required):
            raise ValueError('Pilot source must be regular files no larger than 1 MiB')
        source=archive.read('run.py')
        if hashlib.sha256(source).hexdigest()!=run.script_sha256:
            raise PermissionError('Model script differs from its review')
        # Compilation checks syntax/declared source encoding, never imports or
        # executes participant code in the gateway.
        for name in required:
            if archive.getinfo(name).file_size>1024**2:
                raise ValueError('Pilot source files must not exceed 1 MiB')
            body=archive.read(name)
            if not body.strip():raise ValueError('Pilot source files must not be empty')
            compile(body,'<reviewed-pilot-input>','exec')


class PilotSubmissionBroker:
    def __init__(self,ledger,profile,leases,*,batch,ssm,read_input,enabled=False,supervision_enabled=False,result_archives=None):
        if type(enabled) is not bool or type(supervision_enabled) is not bool:
            raise ValueError('Explicit boolean admission/supervision enablement required')
        profile.validate_funding(ledger.policy)
        if leases.ledger is not ledger or leases.profile!=profile:
            raise PermissionError('Transfer/allowance/execution review must be the same binding')
        if not callable(read_input):raise ValueError('Frozen owner input reader required')
        self.ledger,self.profile,self.leases=ledger,profile,leases
        self.batch,self.ssm,self.read_input,self.enabled=batch,ssm,read_input,enabled
        self.supervision_enabled=supervision_enabled
        self.result_archives=result_archives
        if enabled:self._results_review()
        self._client_review()
        with ledger._transaction() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS pilot_submission_attempts(
                reservation TEXT PRIMARY KEY REFERENCES project_funding_jobs(id),
                profile TEXT NOT NULL,phase TEXT NOT NULL,
                definition_arn TEXT,external_job_id TEXT,updated_at REAL NOT NULL)''')
            c.execute('''CREATE TABLE IF NOT EXISTS pilot_job_observations(
                reservation TEXT PRIMARY KEY REFERENCES project_funding_jobs(id),
                status TEXT NOT NULL,observed_at REAL NOT NULL,
                termination_requested_at REAL,terminal_evidence_sha256 TEXT)''')

    def _results_review(self):
        result=self.result_archives
        if (not isinstance(result,PilotResultArchives) or not result.enabled
                or result.ledger is not self.ledger or result.profile!=self.profile):
            raise PermissionError('Reviewed durable result retention is required before paid submission')
        result._client_review()

    def _client_review(self):
        for client in (self.batch,self.ssm):
            if getattr(getattr(client,'meta',None),'region_name',None)!=self.profile.region:
                raise PermissionError('Client region differs from execution review')
        retries=getattr(getattr(self.batch.meta,'config',None),'retries',{}) or {}
        # total_max_attempts takes precedence in botocore. One SubmitJob network
        # attempt only: its request has no idempotency token.
        total=retries.get('total_max_attempts')
        if total is not None:
            valid=type(total) is int and total==1
        else:valid=type(retries.get('max_attempts')) is int and retries['max_attempts']==0
        if not valid:raise PermissionError('Batch automatic retries must be disabled before review')

    def _phase(self,reservation,phase,*,definition=None,job=None):
        transitions={'parameter_ready':('claimed','submitting'),
                     'definition_ready':('parameter_ready','submitting'),
                     'submit_attempted':('definition_ready','submitting'),
                     'running':('submit_attempted','running')}
        if phase not in transitions:
            raise ValueError('Unknown durable submission transition.')
        previous,state=transitions[phase]
        if (phase=='running') != (job is not None):
            raise ValueError('Only a running transition may bind an AWS job.')
        with self.ledger._transaction() as c:
            c.execute('''UPDATE pilot_submission_attempts SET phase=?,definition_arn=COALESCE(?,definition_arn),
                external_job_id=COALESCE(?,external_job_id),updated_at=?
                WHERE reservation=? AND profile=? AND phase=? AND external_job_id IS NULL
                AND EXISTS(SELECT 1 FROM project_funding_jobs j WHERE j.id=reservation
                  AND j.policy_sha256=? AND j.state=? AND
                  ((? IS NULL AND j.external_job_id IS NULL) OR j.external_job_id=?))''',
                (phase,definition,job,time.time(),reservation,self.profile.fingerprint,previous,
                 self.ledger.policy.fingerprint,state,job,job))
            if c.execute('SELECT changes()').fetchone()[0]!=1:
                raise PermissionError('Submission journal changed; reconcile before continuing')

    def submit(self,user_id,reservation):
        if not self.enabled:raise PermissionError('Project-funded broker is not activated')
        self._results_review()
        self._client_review()
        self.profile.validate_funding(self.ledger.policy)
        row=self.ledger.owned(user_id,reservation)
        if row['state']!='reserved':return row  # never retry a claimed paid request
        run=FundedRun(**json.loads(row['spec_json']))
        self.profile._spec(reservation,run);run.validate(self.ledger.policy)
        data=self.read_input(user_id,reservation)
        # A reviewed profile for another model supplies its own bounded validator.
        getattr(self.profile,'validate_input',validate_frozen_input)(data,run)
        claim=self.ledger.claim_submission(user_id,reservation)
        if claim is None:return self.ledger.owned(user_id,reservation)
        with self.ledger._transaction() as c:
            c.execute('INSERT INTO pilot_submission_attempts VALUES(?,?,\'claimed\',NULL,NULL,?)',
                      (reservation,self.profile.fingerprint,time.time()))
        try:
            token=self.leases.issue(user_id,reservation)
            parameter='/cryostack/pilot-transfer/'+reservation
            parameter_arn=f'arn:aws:ssm:{self.profile.region}:{self.profile.account_id}:parameter'+parameter
            self.ssm.put_parameter(Name=parameter,Value=token,Type='SecureString',Tier='Standard',Overwrite=False)
            self._phase(reservation,'parameter_ready')
            definition=self.profile.definition(self.ledger.policy,reservation=reservation,user_id=user_id,
                run=run,transfer_parameter_arn=parameter_arn)
            registered=self.batch.register_job_definition(**definition)
            arn=registered.get('jobDefinitionArn');revision=registered.get('revision')
            # Reject wrong registration metadata before reading/submitting an ARN.
            if (type(revision) is not int or revision<1 or
                    arn!=f'arn:aws:batch:{self.profile.region}:{self.profile.account_id}:job-definition/'
                        +definition['jobDefinitionName']+':'+str(revision)):
                raise PermissionError('Registration result differs from the reviewed immutable revision')
            descriptions=self.batch.describe_job_definitions(jobDefinitions=[arn]).get('jobDefinitions',[])
            if len(descriptions)!=1:raise PermissionError('One authoritative definition revision required')
            verified=self.profile.verified_definition_arn(descriptions[0],self.ledger.policy,
                reservation=reservation,user_id=user_id,run=run,transfer_parameter_arn=parameter_arn)
            self._phase(reservation,'definition_ready',definition=verified)
            if not self.enabled or not self.ledger.enabled:
                raise PermissionError('Project-funded admission was paused')
            self._results_review()
            self.leases.authorize(reservation,token,operation='worker')
            # A durable phase precedes the single non-idempotent SDK operation.
            # Any timeout/crash from here retains its hold for authoritative
            # reservation-tag discovery; it must never cause another SubmitJob.
            self._phase(reservation,'submit_attempted')
            submitted=self.batch.submit_job(jobName='cryostack-pilot-'+reservation,
                jobQueue=self.profile.queue_arn,jobDefinition=verified,tags=definition['tags'])
            job=submitted.get('jobId')
            result=self.ledger.record_submission(reservation,
                submission_token=claim['submission_token'],external_job_id=job)
            self._phase(reservation,'running',job=job)
            return result
        except Exception:
            # No automatic release, resubmit, role mutation, credential fallback,
            # parameter overwrite/deletion or hidden terminal settlement. Detailed
            # SDK exception strings can contain signed request data; do not echo.
            raise RuntimeError('Pilot submission incomplete; retain the hold and reconcile the journal.') from None

    def attempt_for_owner(self,user_id,reservation):
        row=self.ledger.owned(user_id,reservation)
        with self.ledger._transaction() as c:
            attempt=c.execute('SELECT * FROM pilot_submission_attempts WHERE reservation=?',(reservation,)).fetchone()
            return dict(attempt) if attempt else None

    def watch_reservation(self,reservation,*,now=None):
        """Trusted bounded supervisor tick; no route, scheduler or settlement.

        Continues to inspect known jobs if new admission is paused. Suspended
        accounts/disabled pools and startup/runtime overruns request termination.
        A request is not proof of termination; holds remain until authoritative
        terminal reconciliation. Unknown submissions need operator discovery.
        """
        if not self.supervision_enabled:raise PermissionError('Pilot job supervision is not activated')
        self._client_review()
        now=time.time() if now is None else now
        if type(now) not in (int,float) or not math.isfinite(now) or now<0:
            raise ValueError('Canonical observation time required')
        with self.ledger._transaction() as c:
            row=c.execute("SELECT j.*,s.status AS approval,p.active FROM project_funding_jobs j JOIN account_status s ON s.user_id=j.user_id JOIN allocation_pools p ON p.id=j.pool_id WHERE j.id=?",(reservation,)).fetchone()
            attempt=c.execute('SELECT * FROM pilot_submission_attempts WHERE reservation=?',(reservation,)).fetchone()
            previous=c.execute('SELECT * FROM pilot_job_observations WHERE reservation=?',(reservation,)).fetchone()
        if row is None or attempt is None or not row['external_job_id']:
            raise PermissionError('No known submitted job; reconcile uncertain submission first')
        if (row['policy_sha256']!=self.ledger.policy.fingerprint or attempt['profile']!=self.profile.fingerprint
                or attempt['external_job_id']!=row['external_job_id']):
            raise PermissionError('Observation does not match the original execution review')
        descriptions=self.batch.describe_jobs(jobs=[row['external_job_id']]).get('jobs',[])
        if len(descriptions)!=1:raise RuntimeError('Authoritative job evidence unavailable; retain hold')
        job=descriptions[0]
        expected_tags={'cryostack:pilot':'1','cryostack:reservation':reservation,
            'cryostack:profile':self.profile.profile_id,
            'cryostack:owner':hashlib.sha256(row['user_id'].encode()).hexdigest()}
        job_id=row['external_job_id']
        if (job.get('jobId')!=job_id or job.get('jobArn')!=f'arn:aws:batch:{self.profile.region}:{self.profile.account_id}:job/{job_id}'
                or job.get('jobName')!='cryostack-pilot-'+reservation or job.get('jobQueue')!=self.profile.queue_arn
                or job.get('jobDefinition')!=attempt['definition_arn']
                or any(job.get('tags',{}).get(k)!=v for k,v in expected_tags.items())):
            raise PermissionError('Job identity/owner/queue/definition differs from the reserved submission')
        status=job.get('status')
        if status not in ('SUBMITTED','PENDING','RUNNABLE','STARTING','RUNNING','SUCCEEDED','FAILED'):
            raise ValueError('Unknown authoritative job status')
        created=job.get('createdAt');started=job.get('startedAt',0);stopped=job.get('stoppedAt',0)
        if (type(created) is not int or created<=0 or created/1000>now+30
                or type(started) is not int or type(stopped) is not int
                or started<0 or stopped<0 or (started and started<created)
                or (stopped and stopped<(started or created)) or max(started,stopped)/1000>now+30):
            raise ValueError('Invalid authoritative job timestamps')
        terminal=status in ('SUCCEEDED','FAILED')
        if terminal and not stopped:raise ValueError('Terminal job lacks a stop timestamp')
        if status=='RUNNING' and not started:raise ValueError('Running job lacks a start timestamp')
        reason=None
        if not terminal:
            if row['approval']!='approved' or not row['active']:
                reason='CryoStack pilot account or allocation is no longer active.'
            elif not started and now-created/1000>=self.profile.startup_timeout_seconds:
                reason='CryoStack pilot startup allowance reached.'
            elif started and now-started/1000>=self.profile.task_timeout_seconds:
                reason='CryoStack pilot task allowance reached.'
        last_request=previous['termination_requested_at'] if previous else None
        request_stop=bool(reason and (last_request is None or now-last_request>=30))
        evidence=dict(job_id=job_id,status=status,created_at_ms=created,started_at_ms=started,
                      stopped_at_ms=stopped,profile=self.profile.fingerprint)
        evidence_hash=hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest() if terminal else None
        with self.ledger._transaction() as c:
            c.execute("INSERT INTO pilot_job_observations VALUES(?,?,?,?,?) ON CONFLICT(reservation) DO UPDATE SET status=excluded.status,observed_at=excluded.observed_at,termination_requested_at=COALESCE(excluded.termination_requested_at,pilot_job_observations.termination_requested_at),terminal_evidence_sha256=excluded.terminal_evidence_sha256",(reservation,status,now,now if request_stop else None,evidence_hash))
        termination_sent=False
        if request_stop:
            # Durable request timestamp precedes the call. A timeout is retried
            # only by a future tick after backoff; it never releases the hold.
            try:
                self.batch.terminate_job(jobId=job_id,reason=reason)
                termination_sent=True
            except Exception:
                raise RuntimeError('Termination request uncertain; retain the hold and observe again.') from None
        return dict(evidence,terminal_evidence_sha256=evidence_hash,
                    termination_requested=termination_sent,
                    terminal_confirmed=terminal,allowance_settled=False)

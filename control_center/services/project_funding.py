"""Admission/settlement foundation for project-funded jobs; no AWS calls or routes.

Not an activation switch: production's demo-only guard remains intact. Only a
reviewed gateway execution adapter may call claim/record/settle. A participant
must never receive that adapter, a funding identity, or a submission token.
Prices/credentials are not accepted from browser input. The reviewed ceiling is
an allowance hold, not proof of final AWS billing or an AWS account spending cap.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import re
import secrets
import time
import uuid


_ACTIVE = ('reserved', 'submitting', 'running')


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'Integer required between {low} and {high}.')
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Expected a SHA-256 digest.')
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class FundingPolicy:
    """Trusted reviewed configuration, never built from participant form fields.

    execution_profile is an opaque gateway-side binding. It contains no role
    credentials and grants no AWS permissions. Binding/image/resource/watchdog
    review and actual funding acceptance are prerequisites to a real adapter.
    """
    policy_id: str
    pool_id: str
    execution_profile: str
    image_digest: str
    ceiling_cents: int
    campaign_cap_cents: int
    max_seconds: int = 900
    max_platform_jobs: int = 2

    def __post_init__(self):
        for value in (self.policy_id, self.pool_id, self.execution_profile):
            if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', value):
                raise ValueError('Invalid reviewed funding identifier.')
        if not isinstance(self.image_digest, str) or not self.image_digest.startswith('sha256:'):
            raise ValueError('A pinned image digest is required.')
        _digest(self.image_digest[7:])
        _integer(self.ceiling_cents, 1, 500)
        _integer(self.campaign_cap_cents, self.ceiling_cents, 1000000)
        _integer(self.max_seconds, 1, 3600)
        _integer(self.max_platform_jobs, 1, 10)

    @property
    def fingerprint(self):
        return hashlib.sha256(_canonical(asdict(self)).encode()).hexdigest()


@dataclass(frozen=True)
class FundedRun:
    model: str
    seconds: int
    input_sha256: str
    script_sha256: str

    def validate(self, policy):
        if self.model not in ('issm', 'icepack'):
            raise ValueError('Unsupported pilot model.')
        _integer(self.seconds, 1, policy.max_seconds)
        _digest(self.input_sha256)
        _digest(self.script_sha256)


class ProjectFundingLedger:
    """Transactional, owner-scoped holds shared with Control Center balances.

    This class has no public HTTP endpoint and never submits an AWS job. The
    disabled-by-default admission setting is for a reviewed future adapter;
    turning it on alone does not enable the existing live execution flow.
    """
    def __init__(self, storage, policy: FundingPolicy, *, admission_enabled=False, clock=time.time,
                 pilot_participant_cap_cents=None, admission_check=None):
        if type(admission_enabled) is not bool:
            raise ValueError('admission_enabled must be boolean.')
        if admission_check is not None and not callable(admission_check):
            raise ValueError('admission_check must be callable.')
        if pilot_participant_cap_cents is not None:
            _integer(pilot_participant_cap_cents, policy.ceiling_cents, 1000000)
        self.storage, self.policy = storage, policy
        self.enabled, self.clock = admission_enabled, clock
        self._admission_check = admission_check
        self.pilot_participant_cap_cents = pilot_participant_cap_cents
        with self._transaction() as c:
            # Existing AllocationService owns the pool/account/audit schema.
            for table in ('allocation_pools', 'allocation_accounts', 'allocation_audit', 'account_status'):
                if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    raise RuntimeError('Initialize the reviewed allocation and approval schema first.')
            if 'expires_at' not in {r['name'] for r in c.execute('PRAGMA table_info(allocation_pools)')}:
                raise RuntimeError('Initialize the reviewed allocation and approval schema first.')
            c.execute('''CREATE TABLE IF NOT EXISTS project_funding_jobs (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                pool_id TEXT NOT NULL, request_key TEXT NOT NULL,
                policy_id TEXT NOT NULL, policy_sha256 TEXT NOT NULL,
                spec_json TEXT NOT NULL, ceiling INTEGER NOT NULL CHECK(ceiling>0),
                state TEXT NOT NULL CHECK(state IN ('reserved','submitting','running','settled','released')),
                claim_hash TEXT, external_job_id TEXT UNIQUE,
                charged INTEGER CHECK(charged>=0), outcome TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(user_id,request_key),
                FOREIGN KEY(pool_id,user_id) REFERENCES allocation_accounts(pool_id,user_id))''')

    @contextmanager
    def _transaction(self):
        c = self.storage._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _approved(c, user):
        if not c.execute("SELECT 1 FROM account_status JOIN users ON users.id=account_status.user_id WHERE user_id=? AND status='approved'", (user,)).fetchone():
            raise PermissionError('An approved account is required.')

    def assert_admission_identity(self, c, user):
        self._approved(c, user)
        if self.pilot_participant_cap_cents is not None and not c.execute('''
            SELECT 1 FROM users u JOIN account_status s ON s.user_id=u.id
            JOIN allocation_invites i ON i.email=lower(trim(u.email)) AND i.pool_id=?
            WHERE u.id=? AND s.email_verified_at IS NOT NULL
        ''', (self.policy.pool_id, user)).fetchone():
            raise PermissionError('A verified pilot invitation is required.')

    def admitted_credit(self, credit):
        cap = self.pilot_participant_cap_cents
        return credit if cap is None else min(credit, cap)

    @staticmethod
    def _audit(c, actor, action, **details):
        c.execute('INSERT INTO allocation_audit VALUES(?,?,?,?,?)',
                  (uuid.uuid4().hex, actor, action, _canonical(details), time.time()))

    @staticmethod
    def _public(row):
        result = dict(row)
        result.pop('claim_hash', None)
        return result

    def _ended(self, expires_at):
        # The pool end date stops new admission only. Settlement, release and
        # reconciliation of existing reservations never consult it.
        return bool(expires_at) and expires_at <= self.clock()

    def _owned(self, c, user_id, reservation_id):
        row = c.execute('SELECT * FROM project_funding_jobs WHERE id=? AND user_id=?', (reservation_id,user_id)).fetchone()
        if row is None:
            raise PermissionError('Reservation is not owned by the signed-in user.')
        return row

    @property
    def admission_enabled(self):
        if not self.enabled:
            return False
        if self._admission_check is None:
            return True
        try:
            return self._admission_check() is True
        except Exception:
            return False

    def reserve(self, user_id, *, request_key, run: FundedRun):
        if not self.admission_enabled:
            raise PermissionError('Project-funded admission is not activated.')
        if not isinstance(request_key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', request_key):
            raise ValueError('Invalid submission request key.')
        if not isinstance(run, FundedRun):
            raise ValueError('A reviewed run specification is required.')
        run.validate(self.policy)
        spec = _canonical(asdict(run))
        with self._transaction() as c:
            if not self.admission_enabled:
                raise PermissionError('Project-funded admission is not activated.')
            self.assert_admission_identity(c,user_id)
            previous = c.execute('SELECT * FROM project_funding_jobs WHERE user_id=? AND request_key=?', (user_id,request_key)).fetchone()
            if previous:
                if previous['policy_sha256'] != self.policy.fingerprint or previous['spec_json'] != spec:
                    raise ValueError('Request key already binds different reviewed parameters.')
                return self._public(previous)
            account = c.execute('''SELECT a.*,p.active,p.expires_at FROM allocation_accounts a JOIN allocation_pools p ON p.id=a.pool_id
                WHERE a.user_id=? AND a.pool_id=?''', (user_id,self.policy.pool_id)).fetchone()
            ceiling = self.policy.ceiling_cents
            if account and self._ended(account['expires_at']):
                raise PermissionError('The pilot has ended.')
            if not account or not account['active']:
                raise PermissionError('No active allocation or insufficient available funds.')
            available = self.admitted_credit(account['credit']) - account['reserved'] - account['charged']
            if available < ceiling:
                raise PermissionError('No active allocation or insufficient available funds.')
            if self.pilot_participant_cap_cents is not None and not account['expires_at']:
                raise PermissionError('The pilot end date is unavailable.')
            if c.execute("SELECT 1 FROM project_funding_jobs WHERE user_id=? AND state IN ('reserved','submitting','running')", (user_id,)).fetchone():
                raise PermissionError('Finish or reconcile the existing pilot job first.')
            if c.execute("SELECT COUNT(*) FROM project_funding_jobs WHERE state IN ('reserved','submitting','running')").fetchone()[0] >= self.policy.max_platform_jobs:
                raise PermissionError('Project pilot concurrency limit reached.')
            # Applies to all earlier policies and restarts in this pool. Released
            # holds count zero; terminal charges replace their original ceiling.
            spent = c.execute('''SELECT COALESCE(SUM(CASE WHEN state='settled' THEN charged
                WHEN state='released' THEN 0 ELSE ceiling END),0)
                FROM project_funding_jobs WHERE pool_id=?''', (self.policy.pool_id,)).fetchone()[0]
            if spent+ceiling > self.policy.campaign_cap_cents:
                raise PermissionError('Project campaign allowance is exhausted.')
            key = uuid.uuid4().hex
            now = self.clock()
            c.execute('UPDATE allocation_accounts SET reserved=reserved+? WHERE user_id=? AND pool_id=?', (ceiling,user_id,self.policy.pool_id))
            c.execute('''INSERT INTO project_funding_jobs (id,user_id,pool_id,request_key,policy_id,policy_sha256,
                spec_json,ceiling,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (key,user_id,self.policy.pool_id,request_key,self.policy.policy_id,self.policy.fingerprint,spec,ceiling,'reserved',now,now))
            self._audit(c,user_id,'project_job_reserved',reservation_id=key,policy_sha256=self.policy.fingerprint,ceiling=ceiling)
            return self._public(c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(key,)).fetchone())

    def owned(self, user_id, reservation_id):
        with self._transaction() as c:
            self._approved(c,user_id)
            return self._public(self._owned(c,user_id,reservation_id))

    def job(self, reservation_id):
        """Trusted adapter lookup by reservation id; not owner-checked, never a participant route."""
        with self._transaction() as c:
            row=c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone()
            return self._public(row) if row else None

    def jobs(self, user_id, *, limit=50):
        """One user's funded jobs, newest first. Read-only; needs no approval so history stays visible."""
        _integer(limit,1,500)
        with self._transaction() as c:
            return [self._public(r) for r in c.execute(
                'SELECT * FROM project_funding_jobs WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?',(user_id,limit))]

    def claim_submission(self, user_id, reservation_id):
        """Trusted adapter only. A second claim never authorizes another submit.

        A crashed/uncertain submission retains its hold and cannot be claimed
        again. Reconciliation, not a browser retry, must locate its AWS job.
        """
        if not self.admission_enabled:
            raise PermissionError('Project-funded admission is not activated.')
        with self._transaction() as c:
            if not self.admission_enabled:
                raise PermissionError('Project-funded admission is not activated.')
            self.assert_admission_identity(c,user_id)
            row=self._owned(c,user_id,reservation_id)
            if row['policy_sha256'] != self.policy.fingerprint:
                raise PermissionError('The reviewed execution policy changed.')
            account=c.execute('''SELECT a.*,p.active,p.expires_at FROM allocation_accounts a JOIN allocation_pools p ON p.id=a.pool_id
                WHERE a.user_id=? AND a.pool_id=?''',(user_id,row['pool_id'])).fetchone()
            if not account or not account['active']:
                raise PermissionError('The allocation is no longer active.')
            if row['state'] != 'reserved':
                return None
            # A hold that was never submitted cannot start a new AWS job after the end date; it can be released.
            if self._ended(account['expires_at']):
                raise PermissionError('The pilot has ended.')
            if self.pilot_participant_cap_cents is not None and not account['expires_at']:
                raise PermissionError('The pilot end date is unavailable.')
            if account['reserved'] + account['charged'] > self.admitted_credit(account['credit']):
                raise PermissionError('The pilot allowance is exhausted.')
            token=secrets.token_urlsafe(32)
            c.execute("UPDATE project_funding_jobs SET state='submitting',claim_hash=?,updated_at=? WHERE id=?",
                      (hashlib.sha256(token.encode()).hexdigest(),self.clock(),row['id']))
            self._audit(c,user_id,'project_submission_claimed',reservation_id=row['id'])
            result=self._public(row);result.update(state='submitting',submission_token=token)
            return result

    def record_submission(self, reservation_id, *, submission_token, external_job_id):
        """Trusted adapter result; no participant-facing route may expose this."""
        try:
            if str(uuid.UUID(external_job_id)) != external_job_id:raise ValueError()
        except (ValueError,AttributeError,TypeError):
            raise ValueError('Expected the canonical AWS Batch job UUID.') from None
        with self._transaction() as c:
            row=c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone()
            supplied=hashlib.sha256(str(submission_token).encode()).hexdigest()
            if row is None or not secrets.compare_digest(supplied,row['claim_hash'] or ''):
                raise PermissionError('Submission result does not match its claim.')
            if row['external_job_id']:
                if row['external_job_id']!=external_job_id:raise ValueError('Reservation already binds another job.')
                return self._public(row)
            if row['state'] != 'submitting':raise ValueError('Reservation is not awaiting submission evidence.')
            c.execute("UPDATE project_funding_jobs SET state='running',external_job_id=?,updated_at=? WHERE id=?",
                      (external_job_id,self.clock(),reservation_id))
            self._audit(c,row['user_id'],'project_submission_recorded',reservation_id=reservation_id,external_job_id=external_job_id)
            return self._public(c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone())

    def reconcile_by_operator(self, actor, reservation_id, *, external_job_id, policy_sha256,
                              run: FundedRun, evidence_sha256, reason):
        """Explicit recovery when a crash lost the original submission token.

        Approved admin/owner must first verify authoritative AWS account/queue,
        reservation tags and frozen run metadata. This records their attestation;
        it is NOT an AWS verification implementation and has no HTTP route.
        Absence of a job in a listing never releases an uncertain hold here.
        """
        _digest(policy_sha256)
        _digest(evidence_sha256)
        if not isinstance(run, FundedRun):raise ValueError('A frozen run specification is required.')
        try:
            if str(uuid.UUID(external_job_id)) != external_job_id:raise ValueError()
        except (ValueError,AttributeError,TypeError):
            raise ValueError('Expected the canonical AWS Batch job UUID.') from None
        if not isinstance(reason,str) or not 8 <= len(reason.strip()) <= 500:
            raise ValueError('A recovery reason of 8–500 characters is required.')
        with self._transaction() as c:
            self._approved(c,actor)
            if not c.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role IN ('admin','owner')",(actor,)).fetchone():
                raise PermissionError('Approved administrator recovery is required.')
            row=c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone()
            if row is None or row['policy_sha256']!=policy_sha256 or row['spec_json']!=_canonical(asdict(run)):
                raise ValueError('Recovery evidence does not match the frozen reservation.')
            if row['external_job_id']:
                if row['external_job_id']!=external_job_id:raise ValueError('Reservation already binds another job.')
                return self._public(row)
            if row['state']!='submitting':raise ValueError('Only an uncertain submission needs operator recovery.')
            c.execute("UPDATE project_funding_jobs SET state='running',external_job_id=?,updated_at=? WHERE id=?",
                      (external_job_id,self.clock(),reservation_id))
            self._audit(c,actor,'project_submission_reconciled',reservation_id=reservation_id,
                        external_job_id=external_job_id,evidence_sha256=evidence_sha256,reason=reason.strip())
            return self._public(c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone())

    def release_unsubmitted(self, user_id, reservation_id):
        """Release only when no adapter has claimed submission, even if suspended."""
        with self._transaction() as c:
            row=self._owned(c,user_id,reservation_id)
            if row['state']=='released':return
            if row['state']!='reserved':raise ValueError('Submission may exist; retain funds for reconciliation.')
            c.execute('UPDATE allocation_accounts SET reserved=reserved-? WHERE user_id=? AND pool_id=?', (row['ceiling'],user_id,row['pool_id']))
            c.execute("UPDATE project_funding_jobs SET state='released',updated_at=? WHERE id=?",(self.clock(),reservation_id))
            self._audit(c,user_id,'project_unsubmitted_released',reservation_id=reservation_id)

    def release_pre_submit_failure(self, user_id, reservation_id, *, profile_sha256,
                                   expected_phase, reason, actor_id=None,
                                   evidence_sha256=None, expected_run=None, dry_run=False):
        """Trusted adapter only: release a claimed hold before SubmitJob's marker.

        The journal and ledger are checked/changed in one write transaction.
        An absent journal, uncertain submit or any AWS job id is never evidence
        for release. Operator recovery additionally requires approved admin
        authority, a frozen run and a nonsecret evidence digest. No HTTP route.
        """
        _digest(profile_sha256)
        if expected_phase not in ('claimed','parameter_ready','definition_ready'):
            raise PermissionError('Only a proven pre-submit phase may release a hold.')
        if not isinstance(reason,str) or not 8 <= len(reason.strip()) <= 500:
            raise ValueError('A recovery reason of 8–500 characters is required.')
        if type(dry_run) is not bool:
            raise ValueError('dry_run must be boolean.')
        if actor_id is not None:
            _digest(evidence_sha256)
            if not isinstance(expected_run,FundedRun):
                raise ValueError('A frozen run is required for operator recovery.')
        elif evidence_sha256 is not None or expected_run is not None:
            raise ValueError('Operator evidence requires an authenticated administrator.')
        with self._transaction() as c:
            if actor_id is not None:
                self._approved(c,actor_id)
                if not c.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role IN ('admin','owner')",(actor_id,)).fetchone():
                    raise PermissionError('Approved administrator recovery is required.')
            row=self._owned(c,user_id,reservation_id)
            attempt=c.execute('SELECT * FROM pilot_submission_attempts WHERE reservation=?',(reservation_id,)).fetchone()
            if (row['policy_sha256']!=self.policy.fingerprint or attempt is None
                    or attempt['profile']!=profile_sha256
                    or row['external_job_id'] is not None or attempt['external_job_id'] is not None
                    or (row['charged'] or 0)!=0):
                raise PermissionError('Pre-submit recovery evidence does not match the reservation.')
            if expected_run is not None and row['spec_json']!=_canonical(asdict(expected_run)):
                raise PermissionError('Recovery run differs from the frozen reservation.')
            if row['state']=='released' and attempt['phase']=='released_before_submit':
                return self._public(row)  # idempotent: no second credit or audit
            if row['state']!='submitting' or attempt['phase']!=expected_phase:
                raise PermissionError('Submission journal changed; retain the hold for reconciliation.')
            if dry_run:
                return dict(self._public(row),pre_submit_release_ready=True)
            now=self.clock()
            result=c.execute('''UPDATE pilot_submission_attempts SET phase='released_before_submit',updated_at=?
                WHERE reservation=? AND profile=? AND phase=? AND external_job_id IS NULL''',
                (now,reservation_id,profile_sha256,expected_phase))
            if result.rowcount!=1:
                raise PermissionError('Submission journal changed; retain the hold for reconciliation.')
            result=c.execute('''UPDATE project_funding_jobs SET state='released',claim_hash=NULL,updated_at=?
                WHERE id=? AND user_id=? AND policy_sha256=? AND state='submitting'
                AND external_job_id IS NULL AND COALESCE(charged,0)=0''',
                (now,reservation_id,user_id,self.policy.fingerprint))
            if result.rowcount!=1:
                raise PermissionError('Reservation changed; retain the hold for reconciliation.')
            result=c.execute('''UPDATE allocation_accounts SET reserved=reserved-?
                WHERE user_id=? AND pool_id=? AND reserved>=?''',
                (row['ceiling'],user_id,row['pool_id'],row['ceiling']))
            if result.rowcount!=1:
                raise PermissionError('Reserved balance differs; operator reconciliation is required.')
            details=dict(reservation_id=reservation_id,phase=expected_phase,
                         profile_sha256=profile_sha256,policy_sha256=self.policy.fingerprint,
                         reason=reason.strip(),ceiling=row['ceiling'])
            if actor_id is not None:
                details['evidence_sha256']=evidence_sha256
            self._audit(c,actor_id or user_id,'project_pre_submit_released',**details)
            return self._public(c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone())

    def settle_terminal(self, reservation_id, *, external_job_id, outcome, charge_cents):
        """Trusted authoritative adapter only; not a browser completion assertion.

        Caller must authenticate terminal AWS evidence and its billing/resource
        bounds. Unknown outcomes or an amount above the reviewed hold fail closed.
        Reconciliation remains available for suspended accounts/paused admission.
        """
        _integer(charge_cents,0,500)
        if outcome not in ('SUCCEEDED','FAILED'):raise ValueError('Authoritative terminal evidence is required.')
        with self._transaction() as c:
            row=c.execute('SELECT * FROM project_funding_jobs WHERE id=?',(reservation_id,)).fetchone()
            if row is None or row['external_job_id']!=external_job_id:
                raise PermissionError('Terminal evidence does not match the reserved AWS job.')
            if charge_cents>row['ceiling']:raise ValueError('Charge exceeds the reserved allowance; operator review required.')
            if row['state']=='settled':
                if row['charged']!=charge_cents or row['outcome']!=outcome:raise ValueError('Conflicting terminal settlement.')
                return
            if row['state']!='running':raise ValueError('A known submitted job is required.')
            c.execute('UPDATE allocation_accounts SET reserved=reserved-?,charged=charged+? WHERE user_id=? AND pool_id=?',
                      (row['ceiling'],charge_cents,row['user_id'],row['pool_id']))
            c.execute("UPDATE project_funding_jobs SET state='settled',charged=?,outcome=?,updated_at=? WHERE id=?",(charge_cents,outcome,self.clock(),reservation_id))
            self._audit(c,row['user_id'],'project_terminal_settled',reservation_id=reservation_id,external_job_id=external_job_id,charge=charge_cents,outcome=outcome)

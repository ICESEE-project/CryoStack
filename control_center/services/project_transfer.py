"""Inert per-reservation transfer leases for a reviewed gateway adapter.

No routes, AWS client, credential discovery or workspace writes. Callers supply
owner-scoped immutable input reads and quota-admitted result writes. A durable
local database keeps hashes/receipts only. A gateway-only key derives narrow
capabilities; neither owner AWS credentials nor this key enter a user kernel.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import io
import json
import re
import stat
import time
import zipfile

from .project_execution import PilotExecutionProfile

MAX_BYTES=64*1024**2
MAX_FILES=256


def validate_result(data):
    """Bounded regular ZIP plus the trusted supervisor's mandatory receipt."""
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES:
        raise ValueError('Result archive exceeds its allowance')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries=archive.infolist()
        if not 1<=len(entries)<=MAX_FILES+1:
            raise ValueError('Invalid result entry count')
        seen=set();total=0;receipt=None
        for entry in entries:
            name=entry.filename.rstrip('/');parts=name.split('/');mode=entry.external_attr>>16
            if (not name or '\\' in name or any(p in ('','.','..') for p in parts)
                    or name in seen or stat.S_IFMT(mode) not in (0,stat.S_IFDIR,stat.S_IFREG)
                    or entry.flag_bits&1):
                raise ValueError('Unsafe result archive entry')
            seen.add(name);total+=entry.file_size
            if total>MAX_BYTES:raise ValueError('Expanded results exceed their allowance')
            # Read to verify CRC/decompression now, before workspace admission.
            with archive.open(entry) as stream:
                count=0;raw=bytearray()
                while chunk:=stream.read(65536):
                    count+=len(chunk)
                    if count>entry.file_size:raise ValueError('Invalid expanded result size')
                    if name=='.cryostack-worker.json':
                        raw.extend(chunk)
                        if len(raw)>4096:raise ValueError('Worker receipt is too large')
                if name=='.cryostack-worker.json':receipt=json.loads(raw)
        if (not isinstance(receipt,dict) or receipt.get('model_processes_stopped') is not True
                or receipt.get('model_uid')!=65534 or type(receipt.get('exit_code')) is not int
                or type(receipt.get('timed_out')) is not bool
                or not isinstance(receipt.get('runtime_seconds'),(int,float))
                or not 0<=receipt['runtime_seconds']<=610
                or type(receipt.get('log_bytes_forwarded')) is not int
                or not 0<=receipt['log_bytes_forwarded']<=2*1024**2):
            raise ValueError('Trusted worker receipt is missing or invalid')
        return receipt


class PilotTransferLeases:
    """Trusted gateway service only. Constructing it never enables HTTP access.

    The single output claim is durable before an external write. An uncertain
    callback never resets the claim: reconcile an existing owner result rather
    than blindly writing/debiting twice. No automatic allowance settlement.
    """
    def __init__(self,ledger,profile: PilotExecutionProfile,*,key,worker_source,
                 enabled=False,clock=time.time):
        if type(enabled) is not bool:raise ValueError('Explicit boolean enablement required')
        if not isinstance(key,bytes) or len(key)<32:raise ValueError('Gateway-only random key required')
        if not isinstance(worker_source,bytes) or not 1<=len(worker_source)<=65536:
            raise ValueError('Bounded reviewed worker source required')
        if hashlib.sha256(worker_source).hexdigest()!=profile.worker_sha256:
            raise PermissionError('Worker source differs from the immutable execution review')
        profile.validate_funding(ledger.policy)
        self.ledger,self.profile,self.key,self.worker_source=ledger,profile,key,worker_source
        self.enabled,self.clock=enabled,clock
        with self._transaction() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS pilot_transfer_leases(
                reservation TEXT PRIMARY KEY REFERENCES project_funding_jobs(id),
                profile TEXT NOT NULL, expires REAL NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('ready','uploading','complete','revoked')),
                output_sha256 TEXT, receipt_json TEXT, updated_at REAL NOT NULL)''')

    @contextmanager
    def _transaction(self):
        c=self.ledger.storage._connect()
        try:
            c.execute('BEGIN IMMEDIATE');yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()

    def _token(self,reservation):
        message=('cryostack-pilot-transfer-v1:'+self.profile.fingerprint+':'+reservation).encode()
        import base64
        return base64.urlsafe_b64encode(hmac.new(self.key,message,hashlib.sha256).digest()).decode().rstrip('=')

    def _current(self,c,reservation):
        row=c.execute('''SELECT j.*,a.credit,a.reserved,p.active,s.status FROM project_funding_jobs j
            JOIN allocation_accounts a ON a.user_id=j.user_id AND a.pool_id=j.pool_id
            JOIN allocation_pools p ON p.id=j.pool_id
            JOIN account_status s ON s.user_id=j.user_id WHERE j.id=?''',(reservation,)).fetchone()
        if (row is None or row['status']!='approved' or not row['active']
                or row['state'] not in ('submitting','running')
                or row['policy_sha256']!=self.ledger.policy.fingerprint):
            raise PermissionError('Current approved allocation and active reservation required')
        return dict(row)

    def issue(self,user_id,reservation):
        """Trusted broker only, after the unique submission claim; no public route."""
        if not self.enabled:raise PermissionError('Pilot transfer is not activated')
        if not isinstance(reservation,str) or not re.fullmatch('[a-f0-9]{32}',reservation):
            raise ValueError('Invalid reservation')
        with self._transaction() as c:
            row=self._current(c,reservation)
            if row['user_id']!=user_id:raise PermissionError('Reservation owner mismatch')
            existing=c.execute('SELECT * FROM pilot_transfer_leases WHERE reservation=?',(reservation,)).fetchone()
            if existing:
                if (existing['profile']!=self.profile.fingerprint or existing['expires']<=self.clock()
                        or existing['state']!='ready'):
                    raise PermissionError('An existing lease cannot be renewed by a retry')
            else:
                duration=self.profile.startup_timeout_seconds+self.profile.task_timeout_seconds+60
                c.execute('INSERT INTO pilot_transfer_leases VALUES(?,?,?,\'ready\',NULL,NULL,?)',
                    (reservation,self.profile.fingerprint,self.clock()+duration,self.clock()))
            return self._token(reservation)

    def authorize(self,reservation,token,*,operation):
        if not self.enabled:raise PermissionError('Pilot transfer is not activated')
        if (operation not in ('worker','input','output') or not isinstance(reservation,str)
                or not re.fullmatch('[a-f0-9]{32}',reservation) or not isinstance(token,str)
                or not re.fullmatch('[A-Za-z0-9_-]{43}',token)
                or not hmac.compare_digest(token,self._token(reservation))):
            raise PermissionError('Invalid transfer capability')
        with self._transaction() as c:
            row=self._current(c,reservation)
            lease=c.execute('SELECT * FROM pilot_transfer_leases WHERE reservation=?',(reservation,)).fetchone()
            if (lease is None or lease['profile']!=self.profile.fingerprint
                    or lease['expires']<=self.clock() or lease['state']=='revoked'
                    or (operation!='output' and lease['state']!='ready')):
                raise PermissionError('Transfer capability expired, completed or revoked')
            return row

    def read(self,reservation,token,*,operation,read_input):
        row=self.authorize(reservation,token,operation=operation)
        if operation=='worker':return self.worker_source
        if operation!='input':raise ValueError('Output downloads are not permitted')
        data=read_input(row['user_id'],reservation)
        spec=json.loads(row['spec_json'])
        if (not isinstance(data,bytes) or len(data)>MAX_BYTES
                or hashlib.sha256(data).hexdigest()!=spec['input_sha256']):
            raise PermissionError('Frozen input bytes no longer match the reservation')
        # Approval/lease may have changed during a filesystem read.
        self.authorize(reservation,token,operation='input')
        return data

    def accept_output(self,reservation,token,data,*,admit_output):
        row=self.authorize(reservation,token,operation='output')
        receipt=validate_result(data);digest=hashlib.sha256(data).hexdigest()
        if receipt['runtime_seconds']>json.loads(row['spec_json'])['seconds']+5:
            raise PermissionError('Result exceeds the reserved model runtime')
        with self._transaction() as c:
            self._current(c,reservation)
            lease=c.execute('SELECT * FROM pilot_transfer_leases WHERE reservation=?',(reservation,)).fetchone()
            if lease['expires']<=self.clock() or lease['state']=='revoked':
                raise PermissionError('Transfer lease is no longer active')
            if lease['state']=='complete':
                if not hmac.compare_digest(lease['output_sha256'],digest):
                    raise PermissionError('Completed transfer cannot be overwritten')
                return json.loads(lease['receipt_json'])
            if lease['state']!='ready':
                raise PermissionError('Output admission requires reconciliation')
            c.execute("UPDATE pilot_transfer_leases SET state='uploading',output_sha256=?,updated_at=? WHERE reservation=?",
                      (digest,self.clock(),reservation))
        # The integration MUST atomically admit compressed+expanded bytes through
        # the owner's existing quota and preserve receipt/hash under this run ID.
        # A timeout leaves 'uploading', preventing a duplicate quota side effect.
        admit_output(row['user_id'],reservation,data,digest)
        with self._transaction() as c:
            c.execute("UPDATE pilot_transfer_leases SET state='complete',receipt_json=?,updated_at=? WHERE reservation=? AND state='uploading' AND output_sha256=?",
                      (json.dumps(receipt,sort_keys=True),self.clock(),reservation,digest))
            if c.execute('SELECT changes()').fetchone()[0]!=1:
                raise PermissionError('Output completion needs operator reconciliation')
        return receipt

    def revoke(self,reservation):
        """Trusted cancellation hook; does not release funds or stop an AWS job."""
        with self._transaction() as c:
            c.execute("UPDATE pilot_transfer_leases SET state='revoked',updated_at=? WHERE reservation=?",(self.clock(),reservation))

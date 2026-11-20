"""Disabled gateway-owned durable result retention before workspace admission.

Injected reviewed S3 client only; no credentials, bucket creation, route or
scheduler. Scientific tasks have no S3 role. The root worker's scoped upload
reaches the gateway; this service retains the ZIP under exactly its owned run.
A full CEDAR workspace can defer import without discarding the cloud archive.
"""
from __future__ import annotations
from dataclasses import asdict,dataclass
import base64
import hashlib
import hmac
import json
import re
import time

from .project_transfer import MAX_BYTES,validate_result


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


@dataclass(frozen=True)
class ResultArchiveBinding:
    account_id:str
    region:str
    bucket:str
    prefix:str

    def __post_init__(self):
        if not re.fullmatch('[0-9]{12}',self.account_id or ''):raise ValueError('Reviewed result account required')
        if not re.fullmatch('[a-z]{2}-[a-z]+-[1-9]',self.region or ''):raise ValueError('Reviewed result region required')
        if (not isinstance(self.bucket,str) or not 3<=len(self.bucket)<=63
                or not re.fullmatch('[a-z0-9][a-z0-9.-]*[a-z0-9]',self.bucket)
                or '..' in self.bucket or '.-' in self.bucket or '-.' in self.bucket
                or self.bucket.endswith(('--x-s3','-s3alias','--ol-s3'))
                or re.fullmatch(r'[0-9]+(?:\.[0-9]+){3}',self.bucket)):
            raise ValueError('Reviewed DNS result bucket required')
        if (not isinstance(self.prefix,str) or len(self.prefix)>200
                or not re.fullmatch('(?:[A-Za-z0-9_-]+/)*pilot-results/',self.prefix)):
            raise ValueError('Reviewed dedicated pilot result prefix required')

    @property
    def fingerprint(self):return hashlib.sha256(canonical(asdict(self)).encode()).hexdigest()


class PilotResultArchives:
    def __init__(self,ledger,profile,binding:ResultArchiveBinding,*,s3,enabled=False):
        if type(enabled) is not bool:raise ValueError('Explicit boolean enablement required')
        profile.validate_funding(ledger.policy)
        if (profile.result_archive_review_sha256!=binding.fingerprint
                or profile.account_id!=binding.account_id or profile.region!=binding.region):
            raise PermissionError('Result account/bucket/prefix must be bound into the execution/funding review')
        self.ledger,self.profile,self.binding,self.s3,self.enabled=ledger,profile,binding,s3,enabled
        self._client_review()
        with ledger._transaction() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS pilot_result_archives(
                reservation TEXT PRIMARY KEY REFERENCES project_funding_jobs(id),
                profile TEXT NOT NULL,binding TEXT NOT NULL,sha256 TEXT NOT NULL,
                nbytes INTEGER NOT NULL,state TEXT NOT NULL CHECK(state IN ('uploading','staged','importing','published')),
                created_at REAL NOT NULL,updated_at REAL NOT NULL)''')

    def _client_review(self):
        if (self.profile.result_archive_review_sha256!=self.binding.fingerprint
                or self.profile.account_id!=self.binding.account_id or self.profile.region!=self.binding.region):
            raise PermissionError('Durable result binding changed after review')
        if getattr(getattr(self.s3,'meta',None),'region_name',None)!=self.binding.region:
            raise PermissionError('Result client region differs from review')
        retries=getattr(getattr(self.s3.meta,'config',None),'retries',{}) or {}
        if 'total_max_attempts' in retries:
            valid=type(retries['total_max_attempts']) is int and retries['total_max_attempts']==1
        else:valid=type(retries.get('max_attempts')) is int and retries['max_attempts']==0
        if not valid:raise PermissionError('Bound result request retries before activation')

    def _owner(self,user_id,reservation):
        if not self.enabled:raise PermissionError('Durable pilot results are not activated')
        self._client_review()
        row=self.ledger.owned(user_id,reservation)
        if row['policy_sha256']!=self.ledger.policy.fingerprint:
            raise PermissionError('Use the original reviewed funding/result binding')
        return row

    def _record(self,user_id,reservation):
        self._owner(user_id,reservation)
        with self.ledger._transaction() as c:
            row=c.execute('SELECT * FROM pilot_result_archives WHERE reservation=?',(reservation,)).fetchone()
            if row is None:raise FileNotFoundError('No retained result is recorded')
            if row['profile']!=self.profile.fingerprint or row['binding']!=self.binding.fingerprint:
                raise PermissionError('Result location differs from its original review')
            return dict(row)

    def _location(self,user_id,reservation):
        # No request accepts a bucket, key or another owner's path.
        owner=hashlib.sha256(user_id.encode()).hexdigest()
        key=self.binding.prefix+owner+'/'+reservation+'/results.zip'
        return {'Bucket':self.binding.bucket,'Key':key,'ExpectedBucketOwner':self.binding.account_id}

    def _metadata(self,user_id,reservation,row):
        return {'sha256':row['sha256'],'reservation':reservation,
                'owner':hashlib.sha256(user_id.encode()).hexdigest(),
                'profile':self.profile.fingerprint,'binding':self.binding.fingerprint}

    @staticmethod
    def _checksum(digest):return base64.b64encode(bytes.fromhex(digest)).decode()

    def _head(self,user_id,reservation,row):
        try:result=self.s3.head_object(**self._location(user_id,reservation),ChecksumMode='ENABLED')
        except Exception:
            raise RuntimeError('Retained result lookup is unavailable; preserve the journal.') from None
        expected=self._metadata(user_id,reservation,row)
        checksum=result.get('ChecksumSHA256','')
        if (result.get('ContentLength')!=row['nbytes'] or result.get('ContentType')!='application/zip'
                or any(result.get('Metadata',{}).get(k)!=v for k,v in expected.items())
                or not isinstance(checksum,str) or not hmac.compare_digest(checksum,self._checksum(row['sha256']))):
            raise PermissionError('Retained object does not match its owned checksum/metadata')

    def stage(self,user_id,reservation,data,digest):
        """Trusted relay callback. Cloud durability precedes CEDAR quota writes."""
        funding=self._owner(user_id,reservation)
        if funding['state'] not in ('submitting','running'):
            raise PermissionError('An active reserved job is required for result upload')
        if (not isinstance(data,bytes) or not 1<=len(data)<=MAX_BYTES
                or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)
                or not hmac.compare_digest(hashlib.sha256(data).hexdigest(),digest)):
            raise ValueError('Bounded result digest mismatch')
        receipt=validate_result(data)
        if receipt['runtime_seconds']>json.loads(funding['spec_json'])['seconds']+5:
            raise PermissionError('Result exceeds the reserved model runtime')
        with self.ledger._transaction() as c:
            old=c.execute('SELECT * FROM pilot_result_archives WHERE reservation=?',(reservation,)).fetchone()
            if old is not None:
                if (old['profile']!=self.profile.fingerprint or old['binding']!=self.binding.fingerprint
                        or old['sha256']!=digest or old['nbytes']!=len(data)):
                    raise PermissionError('A retained result cannot be replaced by different bytes')
                existing=dict(old)
            else:
                now=time.time();c.execute('INSERT INTO pilot_result_archives VALUES(?,?,?,?,?,\'uploading\',?,?)',
                    (reservation,self.profile.fingerprint,self.binding.fingerprint,digest,len(data),now,now))
                existing=None
        row=self._record(user_id,reservation)
        if existing is not None:
            # Never blindly PUT again after an ambiguous upload. A valid HEAD
            # recovers the exact existing object; absence requires reconciliation.
            self._head(user_id,reservation,row)
        else:
            try:
                self.s3.put_object(**self._location(user_id,reservation),Body=data,
                    ContentType='application/zip',ChecksumSHA256=self._checksum(digest),
                    Metadata=self._metadata(user_id,reservation,row),IfNoneMatch='*')
                self._head(user_id,reservation,row)
            except Exception:
                raise RuntimeError('Result upload uncertain; retain the journal and reconcile the owned object.') from None
        with self.ledger._transaction() as c:
            c.execute("UPDATE pilot_result_archives SET state='staged',updated_at=? WHERE reservation=? AND state='uploading'",(time.time(),reservation))
        return {'retained':True,'workspace_admitted':row['state']=='published'}

    def read(self,user_id,reservation):
        """Gateway-only authenticated reader. No S3 credential or URL is returned."""
        row=self._record(user_id,reservation);self._head(user_id,reservation,row)
        try:response=self.s3.get_object(**self._location(user_id,reservation),ChecksumMode='ENABLED')
        except Exception:
            raise RuntimeError('Retained result read is unavailable; no workspace import occurred.') from None
        stream=response.get('Body')
        if stream is None:raise RuntimeError('Retained archive is unavailable')
        try:
            if response.get('ContentLength')!=row['nbytes']:raise PermissionError('Retained archive size changed')
            data=stream.read(MAX_BYTES+1)
        finally:stream.close()
        if (not isinstance(data,bytes) or len(data)!=row['nbytes'] or len(data)>MAX_BYTES
                or not hmac.compare_digest(hashlib.sha256(data).hexdigest(),row['sha256'])):
            raise PermissionError('Retained archive bytes changed')
        validate_result(data)
        self._owner(user_id,reservation)  # suspension may have happened during I/O
        with self.ledger._transaction() as c:
            c.execute("UPDATE pilot_result_archives SET state='staged',updated_at=? WHERE reservation=? AND state='uploading'",(time.time(),reservation))
        return data

    def import_to_workspace(self,user_id,reservation,*,admit_output):
        """One atomic quota-admitted import; uncertain writes need reconciliation.

        The trusted importer must raise QuotaExceeded before writing anything,
        preserve the archive hash and be reconcilable after an interrupted commit.
        A quota refusal keeps cloud results available for download and later import.
        """
        from cryostack_src.workspace.storage_policy import QuotaExceeded
        if not callable(admit_output):raise ValueError('Reviewed quota-admitted importer required')
        data=self.read(user_id,reservation);row=self._record(user_id,reservation)
        with self.ledger._transaction() as c:
            current=c.execute('SELECT state FROM pilot_result_archives WHERE reservation=?',(reservation,)).fetchone()[0]
            if current=='published':return {'retained':True,'workspace_admitted':True}
            if current!='staged':raise PermissionError('Workspace import requires reconciliation')
            c.execute("UPDATE pilot_result_archives SET state='importing',updated_at=? WHERE reservation=?",(time.time(),reservation))
        try:admit_output(user_id,reservation,data,row['sha256'])
        except QuotaExceeded:
            with self.ledger._transaction() as c:
                c.execute("UPDATE pilot_result_archives SET state='staged',updated_at=? WHERE reservation=? AND state='importing'",(time.time(),reservation))
            return {'retained':True,'workspace_admitted':False,'reason':'workspace_capacity'}
        # Any other callback error retains 'importing', preventing duplicate
        # storage admission until an operator verifies the destination/hash.
        with self.ledger._transaction() as c:
            c.execute("UPDATE pilot_result_archives SET state='published',updated_at=? WHERE reservation=? AND state='importing'",(time.time(),reservation))
            if c.execute('SELECT changes()').fetchone()[0]!=1:raise PermissionError('Import completion needs reconciliation')
        return {'retained':True,'workspace_admitted':True}

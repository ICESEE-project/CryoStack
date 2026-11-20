"""Hosted pilot credit: the one object a gateway execution adapter talks to.

A thin facade over ProjectFundingLedger (which owns every money transaction)
and AllocationService's pool/account tables. No AWS client, route or
credential lives here. The policy, pool and per-run hold come from reviewed
gateway configuration; nothing a participant sends chooses a pool or a price.
claim/record/settle are for the trusted adapter only: the submission token
must never be logged or returned to a browser.
"""
from __future__ import annotations

import json
import os
import time

from .project_funding import FundedRun, FundingPolicy, ProjectFundingLedger


_REQUIRED = ('policy_id', 'pool_id', 'execution_profile', 'image_digest', 'ceiling_cents', 'campaign_cap_cents')
_OPTIONAL = ('max_seconds', 'max_platform_jobs')
_FIELDS = ('id', 'state', 'ceiling', 'charged', 'outcome', 'external_job_id', 'created_at', 'updated_at')
PILOT_PARTICIPANT_CAP_CENTS = 2500


def load_policy(mapping) -> FundingPolicy:
    """Build the reviewed FundingPolicy from a plain mapping such as parsed JSON config."""
    if not isinstance(mapping, dict):
        raise ValueError('Pilot funding policy must be a mapping.')
    unknown = sorted(str(k) for k in mapping if k not in _REQUIRED + _OPTIONAL)
    if unknown:
        raise ValueError('Unknown pilot funding policy field(s): ' + ', '.join(unknown) + '.')
    missing = [k for k in _REQUIRED if k not in mapping]
    if missing:
        raise ValueError('Missing pilot funding policy field(s): ' + ', '.join(missing) + '.')
    for key in ('ceiling_cents', 'campaign_cap_cents') + _OPTIONAL:
        if key in mapping and type(mapping[key]) is not int:
            raise ValueError(f'Pilot funding policy field {key} must be an integer.')
    try:
        return FundingPolicy(**mapping)
    except ValueError as error:
        raise ValueError(f'Invalid pilot funding policy: {error}') from None


def _view(row):
    """Participant-safe job fields. No token hash, policy fingerprint, pool or owner id."""
    if row is None:
        return None
    try:
        model = str(json.loads(row['spec_json']).get('model', ''))
    except (ValueError, AttributeError, KeyError, TypeError):
        model = ''
    view = {k: row[k] for k in _FIELDS}
    view['model'] = model
    return view


class PilotFunding:
    def __init__(self, storage, policy: FundingPolicy, *, admission_enabled=False, clock=time.time):
        if not isinstance(policy, FundingPolicy):
            raise ValueError('A reviewed FundingPolicy is required.')
        self.storage, self.policy, self.clock = storage, policy, clock
        self.ledger = ProjectFundingLedger(
            storage, policy, admission_enabled=admission_enabled, clock=clock,
            pilot_participant_cap_cents=PILOT_PARTICIPANT_CAP_CENTS,
            admission_check=lambda: os.environ.get("CRYOSTACK_PILOT_ADMISSION_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        )

    load_policy = staticmethod(load_policy)

    @property
    def admission_enabled(self):
        return self.ledger.admission_enabled

    def summary(self, user_id) -> dict:
        """Balance and state for one user. Unknown or ineligible users get eligible=False and zeros."""
        result = dict(eligible=False, pool_id=None, pool_name='', credit_cents=0, reserved_cents=0, charged_cents=0,
                      available_cents=0, hold_cents=self.policy.ceiling_cents, expires_at=0, expired=False,
                      admission_enabled=self.admission_enabled, active_reservation=None)
        if not isinstance(user_id, str) or not user_id:
            return result
        c = self.storage._connect()
        try:
            active = c.execute("SELECT * FROM project_funding_jobs WHERE user_id=? AND state IN ('reserved','submitting','running')"
                               " ORDER BY created_at DESC LIMIT 1", (user_id,)).fetchone()
            try:
                self.ledger.assert_admission_identity(c, user_id)
            except PermissionError:
                row = None
            else:
                row = c.execute('''SELECT a.credit,a.reserved,a.charged,p.name,p.active,p.expires_at
                    FROM allocation_accounts a JOIN allocation_pools p ON p.id=a.pool_id
                    WHERE a.user_id=? AND a.pool_id=?''', (user_id, self.policy.pool_id)).fetchone()
        finally:
            c.close()
        # A running job stays visible even if the account was suspended or the pool closed meanwhile.
        result['active_reservation'] = _view(active)
        if row is None or not row['active'] or not row['expires_at']:
            return result
        expired = bool(row['expires_at']) and row['expires_at'] <= self.clock()
        credit = self.ledger.admitted_credit(row['credit'])
        result.update(eligible=True, pool_id=self.policy.pool_id, pool_name=row['name'], credit_cents=credit,
                      reserved_cents=row['reserved'], charged_cents=row['charged'],
                      available_cents=0 if expired else max(0, credit - row['reserved'] - row['charged']),
                      expires_at=row['expires_at'], expired=expired)
        return result

    def reserve(self, user_id, *, request_key, model, seconds, input_sha256, script_sha256) -> dict:
        """Hold the policy ceiling against the user's credit. Idempotent per (user, request_key)."""
        return _view(self.ledger.reserve(user_id, request_key=request_key,
                                         run=FundedRun(model, seconds, input_sha256, script_sha256)))

    def claim(self, user_id, reservation_id) -> str:
        """One-use submission token. A second claim raises: it must never authorize a second AWS submit."""
        claimed = self.ledger.claim_submission(user_id, reservation_id)
        if claimed is None:
            raise PermissionError('Submission was already claimed for this reservation.')
        return claimed['submission_token']

    def record(self, reservation_id, *, submission_token, external_job_id) -> dict:
        return _view(self.ledger.record_submission(reservation_id, submission_token=submission_token,
                                                   external_job_id=external_job_id))

    def release(self, user_id, reservation_id) -> None:
        """Return an unsubmitted hold. Raises ValueError once a submission may exist."""
        self.ledger.release_unsubmitted(user_id, reservation_id)

    def settle(self, reservation_id, *, external_job_id, outcome, charge_cents) -> dict:
        """Charge a terminal job (idempotent). Works after the end date and with admission off."""
        self.ledger.settle_terminal(reservation_id, external_job_id=external_job_id, outcome=outcome,
                                    charge_cents=charge_cents)
        return _view(self.ledger.job(reservation_id))

    def jobs(self, user_id, limit=50) -> list:
        if not isinstance(user_id, str) or not user_id:
            return []
        return [_view(row) for row in self.ledger.jobs(user_id, limit=limit)]

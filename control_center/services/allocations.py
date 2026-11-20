"""Persistent resource allocations. Integer cents; no AWS execution or billing API."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager


_KEEP = object()   # "leave the stored end date unchanged"
_EMAIL = re.compile(r"[a-z0-9.!#$%&*+/=?^_`{|}~-]{1,64}@[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63}){1,8}")
# SQL fragments shared by both automatic-grant triggers and the admin backfill.
_NOT_EXPIRED = "(p.expires_at=0 OR p.expires_at>CAST(strftime('%s','now') AS REAL))"
# invite_only=1: only invited addresses, and an empty list grants to nobody.
# invite_only=0: invitations restrict the grant only while the pool has any.
_INVITED = ("((p.invite_only=0 AND NOT EXISTS(SELECT 1 FROM allocation_invites i WHERE i.pool_id=p.id)) OR EXISTS(SELECT 1 FROM "
            "allocation_invites i WHERE i.pool_id=p.id AND i.email=lower(trim({email}))))")


class AllocationService:
    # Conservative demonstration ceilings, not AWS prices. No caller-supplied rates.
    PRESETS = {"small": {"cents_per_hour": 200, "max_minutes": 60},
               "medium": {"cents_per_hour": 800, "max_minutes": 30}}
    APPLICATIONS = {"cryolauncher", "icesee", "frozen-legacies", "livist"}
    MAX_INVITES = 500

    def __init__(self, storage, *, require_approval: bool | None = None):
        if require_approval is not None and type(require_approval) is not bool:
            raise ValueError("Approval policy must be an explicit boolean or inherited.")
        self.storage = storage
        with self._transaction() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS allocation_pools (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, budget INTEGER NOT NULL CHECK(budget>=0),
                    intro_enabled INTEGER NOT NULL DEFAULT 0 CHECK(intro_enabled IN (0,1)),
                    default_credit INTEGER NOT NULL DEFAULT 0 CHECK(default_credit>=0),
                    intro_since REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1);
                CREATE UNIQUE INDEX IF NOT EXISTS one_intro_pool ON allocation_pools(intro_enabled)
                    WHERE intro_enabled=1;
                CREATE TABLE IF NOT EXISTS allocation_accounts (
                    pool_id TEXT NOT NULL REFERENCES allocation_pools(id),
                    user_id TEXT NOT NULL REFERENCES users(id),
                    credit INTEGER NOT NULL CHECK(credit>=0),
                    reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0),
                    charged INTEGER NOT NULL DEFAULT 0 CHECK(charged>=0),
                    CHECK(credit>=reserved+charged), PRIMARY KEY(pool_id,user_id));
                CREATE TABLE IF NOT EXISTS allocation_intro_seen (
                    user_id TEXT PRIMARY KEY REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS allocation_policy_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1),
                    approval_required INTEGER NOT NULL CHECK(approval_required IN (0,1)));
                CREATE TABLE IF NOT EXISTS allocation_jobs (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    pool_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    application TEXT NOT NULL, preset TEXT NOT NULL, minutes INTEGER NOT NULL,
                    ceiling INTEGER NOT NULL CHECK(ceiling>0), state TEXT NOT NULL,
                    created_at REAL NOT NULL, UNIQUE(user_id,request_key),
                    FOREIGN KEY(pool_id,user_id) REFERENCES allocation_accounts(pool_id,user_id));
                CREATE TABLE IF NOT EXISTS allocation_invites (
                    pool_id TEXT NOT NULL REFERENCES allocation_pools(id), email TEXT NOT NULL,
                    added_by TEXT NOT NULL, added_at REAL NOT NULL, PRIMARY KEY(pool_id,email));
                CREATE TABLE IF NOT EXISTS allocation_audit (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    details TEXT NOT NULL, created_at REAL NOT NULL);
            ''')
            columns = {r['name'] for r in c.execute('PRAGMA table_info(allocation_pools)')}
            for column in ('eligible_domain', 'eligible_institution'):
                if column not in columns:
                    c.execute(f"ALTER TABLE allocation_pools ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            if 'invite_only' not in columns:
                c.execute("ALTER TABLE allocation_pools ADD COLUMN invite_only INTEGER NOT NULL DEFAULT 0")
            if 'expires_at' not in columns:
                # 0 = no end date. After it passes, grants stop and balances lapse (history is kept).
                c.execute("ALTER TABLE allocation_pools ADD COLUMN expires_at REAL NOT NULL DEFAULT 0")
            # Trigger replacement is one transaction: a concurrent pending
            # registration must never slip through an intermediate legacy trigger.
            if not c.in_transaction:
                c.execute('BEGIN IMMEDIATE')
            for name in ('allocation_new_user','allocation_intro_approved_insert','allocation_intro_approved_update'):
                c.execute('DROP TRIGGER IF EXISTS '+name)
            from icesee_auth.approval import approval_required_from_env
            requested = approval_required_from_env() if require_approval is None else require_approval
            c.execute('INSERT OR IGNORE INTO allocation_policy_settings VALUES(1,0)')
            if requested:
                c.execute('UPDATE allocation_policy_settings SET approval_required=1 WHERE id=1')
            # A default/legacy constructor must never downgrade a gateway's
            # persisted approval policy during a notebook or service restart.
            gated = bool(c.execute('SELECT approval_required FROM allocation_policy_settings WHERE id=1').fetchone()[0])
            approval_schema = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_status'").fetchone()
            if gated and not approval_schema:
                raise RuntimeError('Initialize the account approval schema before enabling approved introductory grants.')
            if gated:
                # Evaluate the current introductory policy at first approval.
                # Pending sign-ups allocate no pool funds. Existing balances and
                # seen markers are preserved; this does not backfill old users.
                body = '''
                    INSERT OR IGNORE INTO allocation_accounts(pool_id,user_id,credit)
                    SELECT p.id,u.id,p.default_credit FROM allocation_pools p JOIN users u ON u.id=NEW.user_id
                    WHERE p.active=1 AND p.intro_enabled=1 AND u.created_at>=p.intro_since
                    AND (p.eligible_domain='' OR lower(substr(u.email,instr(u.email,'@')+1))=p.eligible_domain)
                    AND (p.eligible_institution='' OR lower(trim(COALESCE(u.institution,'')))=p.eligible_institution)
                    AND '''+_NOT_EXPIRED+' AND '+_INVITED.format(email='u.email')+'''
                    AND p.default_credit>0 AND p.budget >= p.default_credit +
                        COALESCE((SELECT SUM(credit) FROM allocation_accounts WHERE pool_id=p.id),0)
                    AND NOT EXISTS(SELECT 1 FROM allocation_intro_seen WHERE user_id=u.id);
                    INSERT INTO allocation_audit(id,actor,action,details,created_at)
                    SELECT lower(hex(randomblob(16))),NEW.user_id,'intro_granted',
                        json_object('pool_id',a.pool_id,'cents',a.credit),strftime('%s','now')
                    FROM allocation_accounts a JOIN allocation_pools p ON p.id=a.pool_id
                    WHERE a.user_id=NEW.user_id AND p.intro_enabled=1 AND changes()>0;
                    INSERT OR IGNORE INTO allocation_intro_seen(user_id) VALUES(NEW.user_id);
'''
                for name,event,condition in (
                    ('insert','AFTER INSERT',"NEW.status='approved'"),
                    ('update','AFTER UPDATE OF status',"NEW.status='approved' AND OLD.status!='approved'")):
                    c.execute('CREATE TRIGGER allocation_intro_approved_'+name+' '+event+
                              ' ON account_status WHEN '+condition+' BEGIN '+body+' END')
            else:
                # Standalone/demo callers have not enabled approval-bound grants.
                # Retain its established creation-time behavior; live project
                # admission separately requires an actual approved status row.
                c.execute('''CREATE TRIGGER allocation_new_user AFTER INSERT ON users
                BEGIN
                    INSERT OR IGNORE INTO allocation_accounts(pool_id,user_id,credit)
                    SELECT p.id,NEW.id,p.default_credit FROM allocation_pools p
                    WHERE p.active=1 AND p.intro_enabled=1 AND NEW.created_at>=p.intro_since
                    AND (p.eligible_domain='' OR lower(substr(NEW.email,instr(NEW.email,'@')+1))=p.eligible_domain)
                    AND (p.eligible_institution='' OR lower(trim(COALESCE(NEW.institution,'')))=p.eligible_institution)
                    AND '''+_NOT_EXPIRED+' AND '+_INVITED.format(email='NEW.email')+'''
                    AND p.default_credit>0 AND p.budget >= p.default_credit +
                        COALESCE((SELECT SUM(credit) FROM allocation_accounts WHERE pool_id=p.id),0)
                    AND NOT EXISTS(SELECT 1 FROM allocation_intro_seen WHERE user_id=NEW.id);
                    INSERT INTO allocation_audit(id,actor,action,details,created_at)
                    SELECT lower(hex(randomblob(16))),NEW.id,'intro_granted',
                        json_object('pool_id',pool_id,'cents',credit),NEW.created_at
                    FROM allocation_accounts WHERE user_id=NEW.id;
                    INSERT OR IGNORE INTO allocation_intro_seen(user_id) VALUES(NEW.id);
                END;''')

    @contextmanager
    def _transaction(self):
        c = self.storage._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _integer(value, low=0, high=100_000_000):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Integer required between {low} and {high}.")
        return value

    @staticmethod
    def _user(c, user_id):
        if not user_id or not c.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
            raise PermissionError("Authenticated user required.")

    def _admin(self, c, actor):
        self._user(c, actor)
        if not c.execute("SELECT 1 FROM user_roles WHERE user_id=? AND role IN ('admin','owner')",
                         (actor,)).fetchone():
            raise PermissionError("Administrator or owner required.")

    @staticmethod
    def _audit(c, actor, action, **details):
        c.execute("INSERT INTO allocation_audit VALUES(?,?,?,?,?)",
                  (uuid.uuid4().hex, actor, action, json.dumps(details, sort_keys=True), time.time()))

    @staticmethod
    def _expiry(value, current=0.0):
        """None/0 clears; otherwise epoch seconds in the future (or the unchanged stored value)."""
        if value is None or (type(value) in (int, float) and value == 0):
            return 0.0
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("End date must be epoch seconds, or empty for no end date.")
        value = float(value)
        if value != current and not time.time() < value < time.time() + 10 * 366 * 86400:
            raise ValueError("End date must be in the future.")
        return value

    @staticmethod
    def _flag(value, current):
        if value is _KEEP:
            return int(bool(current))
        if type(value) is not bool:
            raise ValueError("invite_only must be a boolean.")
        return int(value)

    @staticmethod
    def _email(value):
        value = value.strip().lower() if isinstance(value, str) else ""
        if not 6 <= len(value) <= 254 or not _EMAIL.fullmatch(value):
            raise ValueError("Invalid email address.")
        return value

    @staticmethod
    def _pool(c, pool_id):
        pool = c.execute("SELECT * FROM allocation_pools WHERE id=?", (pool_id if isinstance(pool_id, str) else "",)).fetchone()
        if not pool:
            raise ValueError("Unknown pool.")
        return pool

    def configure_pool(self, actor, *, name, budget, intro_enabled=False, default_credit=0, pool_id=None,
                       eligible_domain="", eligible_institution="", expires_at=_KEEP, invite_only=_KEEP):
        for value in (eligible_domain, eligible_institution):
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError("Invalid eligible cohort.")
        eligible_domain = eligible_domain.strip().lower()
        eligible_institution = eligible_institution.strip().lower()
        if eligible_domain and ("@" in eligible_domain or " " in eligible_domain or "." not in eligible_domain):
            raise ValueError("Use a complete email domain, such as gatech.edu.")
        self._integer(budget)
        self._integer(default_credit)
        if type(intro_enabled) is not bool or default_credit > budget:
            raise ValueError("Invalid introductory allocation policy.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Pool name must contain 1–100 characters.")
        with self._transaction() as c:
            self._admin(c, actor)
            old = c.execute("SELECT * FROM allocation_pools WHERE id=?", (pool_id,)).fetchone()
            if pool_id and not old:
                raise ValueError("Unknown pool.")
            pool_id = pool_id or uuid.uuid4().hex
            allocated = c.execute("SELECT COALESCE(SUM(credit),0) FROM allocation_accounts WHERE pool_id=?",
                                  (pool_id,)).fetchone()[0]
            if budget < allocated:
                raise ValueError("Budget cannot be below committed allocations.")
            if intro_enabled and c.execute("SELECT 1 FROM allocation_pools WHERE intro_enabled=1 AND id!=?",
                                           (pool_id,)).fetchone():
                raise ValueError("Disable the other introductory pool first.")
            since = old['intro_since'] if old and old['intro_enabled'] and intro_enabled else time.time()
            stored = old['expires_at'] if old else 0.0
            expiry = stored if expires_at is _KEEP else self._expiry(expires_at, stored)
            only = self._flag(invite_only, old['invite_only'] if old else 0)
            c.execute('''INSERT INTO allocation_pools(id,name,budget,intro_enabled,default_credit,intro_since,active,eligible_domain,eligible_institution,expires_at,invite_only) VALUES(?,?,?,?,?,?,1,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,budget=excluded.budget,
                intro_enabled=excluded.intro_enabled,default_credit=excluded.default_credit,
                intro_since=excluded.intro_since,eligible_domain=excluded.eligible_domain,
                eligible_institution=excluded.eligible_institution,expires_at=excluded.expires_at,
                invite_only=excluded.invite_only''',
                (pool_id, name.strip(), budget, int(intro_enabled), default_credit, since, eligible_domain, eligible_institution, expiry, only))
            self._audit(c, actor, "pool_configured", pool_id=pool_id, name=name.strip(), budget=budget,
                        intro_enabled=intro_enabled, default_credit=default_credit,
                        eligible_domain=eligible_domain, eligible_institution=eligible_institution, expires_at=expiry,
                        invite_only=bool(only))
        return pool_id

    def search_users(self, actor, *, query=""):
        if not isinstance(query, str):
            raise ValueError("Invalid search.")
        with self._transaction() as c:
            self._admin(c, actor)
            term = "%" + query.strip()[:200].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            return [dict(r) for r in c.execute("SELECT id,display_name,email,institution FROM users WHERE display_name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' ORDER BY display_name,email LIMIT 50", (term,term))]

    def policy_preview(self, actor, *, pool_id):
        with self._transaction() as c:
            self._admin(c,actor)
            pool=c.execute("SELECT * FROM allocation_pools WHERE id=?",(pool_id,)).fetchone()
            if not pool:
                raise ValueError("Unknown pool.")
            count=c.execute("SELECT COUNT(*) FROM users WHERE (?='' OR lower(substr(email,instr(email,'@')+1))=?) AND (?='' OR lower(trim(COALESCE(institution,'')))=?)",(pool['eligible_domain'],pool['eligible_domain'],pool['eligible_institution'],pool['eligible_institution'])).fetchone()[0]
            allocated=c.execute("SELECT COALESCE(SUM(credit),0) FROM allocation_accounts WHERE pool_id=?",(pool_id,)).fetchone()[0]
            remaining=pool['budget']-allocated
            invited=self._invited(c,pool)
            return {'matching_existing_users':count,'unallocated':remaining,
                    'new_user_grant_capacity':remaining//pool['default_credit'] if pool['default_credit']>0 else None,
                    'intro_enabled':bool(pool['intro_enabled']),
                    'retroactive_grants':False,
                    'invite_only':bool(pool['invite_only']),'invite_count':len(invited),
                    'invited_existing_users':sum(1 for r in invited if r['user_id']),
                    'invited_granted':sum(1 for r in invited if r['granted']),
                    'invited_awaiting_grant':sum(1 for r in invited if r['grantable']),
                    'expires_at':pool['expires_at'],'expired':self._expired(pool['expires_at'])}

    @staticmethod
    def _expired(expires_at, now=None):
        return bool(expires_at) and expires_at <= (time.time() if now is None else now)

    @staticmethod
    def _gated(c):
        return bool(c.execute('SELECT approval_required FROM allocation_policy_settings WHERE id=1').fetchone()[0])

    def _invited(self, c, pool):
        """Invite rows joined to accounts. grantable = approved, matches the pool cohort, no account yet."""
        approved = ("EXISTS(SELECT 1 FROM account_status s WHERE s.user_id=u.id AND s.status='approved')"
                    if self._gated(c) else "1")
        return [dict(r) for r in c.execute(f'''SELECT i.email,i.added_at,i.added_by,u.id user_id,u.display_name,
                a.user_id IS NOT NULL granted,
                (u.id IS NOT NULL AND a.user_id IS NULL AND {approved}
                 AND (p.eligible_domain='' OR lower(substr(u.email,instr(u.email,'@')+1))=p.eligible_domain)
                 AND (p.eligible_institution='' OR lower(trim(COALESCE(u.institution,'')))=p.eligible_institution)) grantable
            FROM allocation_invites i JOIN allocation_pools p ON p.id=i.pool_id
            LEFT JOIN users u ON u.id=(SELECT id FROM users WHERE lower(trim(email))=i.email ORDER BY created_at LIMIT 1)
            LEFT JOIN allocation_accounts a ON a.pool_id=i.pool_id AND a.user_id=u.id
            WHERE i.pool_id=? ORDER BY i.email''', (pool['id'],))]

    def set_invites(self, actor, *, pool_id, emails, replace=False):
        """Add (or, with replace, substitute) the invited cohort.

        The first invitations on a pool switch it to invite_only, so that
        later emptying the list grants to nobody rather than to everyone.
        Only configure_policy/configure_pool can switch invite_only off.
        """
        if type(replace) is not bool or not isinstance(emails, list) or len(emails) > self.MAX_INVITES:
            raise ValueError(f"Provide a list of at most {self.MAX_INVITES} email addresses.")
        bad = 0
        clean = []
        for value in emails:
            try:
                clean.append(self._email(value))
            except ValueError:
                bad += 1
        if bad:
            raise ValueError(f"{bad} of {len(emails)} entries are not valid email addresses; nothing was saved.")
        clean = sorted(set(clean))
        with self._transaction() as c:
            self._admin(c, actor)
            pool = self._pool(c, pool_id)
            before = c.execute("SELECT COUNT(*) FROM allocation_invites WHERE pool_id=?", (pool_id,)).fetchone()[0]
            if replace:
                c.execute("DELETE FROM allocation_invites WHERE pool_id=?", (pool_id,))
            now = time.time()
            added = sum(c.execute("INSERT OR IGNORE INTO allocation_invites VALUES(?,?,?,?)",
                                  (pool_id, email, actor, now)).rowcount for email in clean)
            total = c.execute("SELECT COUNT(*) FROM allocation_invites WHERE pool_id=?", (pool_id,)).fetchone()[0]
            if total > self.MAX_INVITES:
                raise ValueError(f"A pool can hold at most {self.MAX_INVITES} invitations.")
            # Counts only: the cohort's addresses stay in allocation_invites, not in the audit trail.
            switched = bool(not before and total and not pool['invite_only'])
            if switched:
                c.execute("UPDATE allocation_pools SET invite_only=1 WHERE id=?", (pool_id,))
            self._audit(c, actor, "invites_updated", pool_id=pool_id, submitted=len(clean), added=added,
                        before=before, total=total, replace=replace, invite_only_enabled=switched)
            return {'added': added, 'total': total, 'replaced': replace,
                    'invite_only': bool(pool['invite_only']) or switched, 'invite_only_enabled': switched}

    def list_invites(self, actor, *, pool_id):
        with self._transaction() as c:
            self._admin(c, actor)
            return [dict(r, granted=bool(r['granted']), grantable=bool(r['grantable']))
                    for r in self._invited(c, self._pool(c, pool_id))]

    def remove_invite(self, actor, *, pool_id, email):
        """Withdraw one invitation. Credit that was already granted is not revoked."""
        email = self._email(email)
        with self._transaction() as c:
            self._admin(c, actor)
            self._pool(c, pool_id)
            removed = c.execute("DELETE FROM allocation_invites WHERE pool_id=? AND email=?", (pool_id, email)).rowcount
            total = c.execute("SELECT COUNT(*) FROM allocation_invites WHERE pool_id=?", (pool_id,)).fetchone()[0]
            if removed:
                self._audit(c, actor, "invite_removed", pool_id=pool_id, total=total)
            return {'removed': bool(removed), 'total': total}

    def grant_invited_existing(self, actor, *, pool_id):
        """Grant the pool's default credit to invited, already-approved users without an account in it.

        The approval triggers fire once per user, so this covers accounts that
        existed before the pilot and people invited after they signed up. It is
        idempotent, never exceeds the pool budget and never tops up a balance.
        """
        with self._transaction() as c:
            self._admin(c, actor)
            pool = self._pool(c, pool_id)
            if not pool['active'] or self._expired(pool['expires_at']):
                raise ValueError("The pool is inactive or its end date has passed.")
            cents = pool['default_credit']
            if cents <= 0:
                raise ValueError("Set a nonzero credit per eligible user first.")
            invited = self._invited(c, pool)
            room = pool['budget'] - c.execute("SELECT COALESCE(SUM(credit),0) FROM allocation_accounts WHERE pool_id=?",
                                              (pool_id,)).fetchone()[0]
            granted = short = 0
            for row in invited:
                if not row['grantable']:
                    continue
                if room < cents:
                    short += 1
                    continue
                c.execute("INSERT INTO allocation_accounts(pool_id,user_id,credit) VALUES(?,?,?)", (pool_id, row['user_id'], cents))
                c.execute("INSERT OR IGNORE INTO allocation_intro_seen(user_id) VALUES(?)", (row['user_id'],))
                self._audit(c, actor, "invited_granted", pool_id=pool_id, user_id=row['user_id'], cents=cents)
                room -= cents
                granted += 1
            result = {'invited': len(invited), 'granted': granted,
                      'already_granted': sum(1 for r in invited if r['granted']),
                      'not_registered': sum(1 for r in invited if not r['user_id']),
                      'not_eligible': sum(1 for r in invited if r['user_id'] and not r['granted'] and not r['grantable']),
                      'skipped_budget': short, 'cents_each': cents}
            self._audit(c, actor, "invited_existing_granted", pool_id=pool_id, **result)
            return result

    def configure_budget(self, actor, *, name, budget, pool_id=None):
        self._integer(budget)
        if not isinstance(name,str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Pool name must contain 1–100 characters.")
        if not pool_id:
            return self.configure_pool(actor,name=name,budget=budget)
        with self._transaction() as c:
            self._admin(c,actor)
            pool=c.execute("SELECT * FROM allocation_pools WHERE id=?",(pool_id,)).fetchone()
            if not pool:
                raise ValueError("Unknown pool.")
            committed=c.execute("SELECT COALESCE(SUM(credit),0) FROM allocation_accounts WHERE pool_id=?",(pool_id,)).fetchone()[0]
            if budget < max(committed,pool['default_credit']):
                raise ValueError("Budget is below committed credits or the automatic credit amount.")
            c.execute("UPDATE allocation_pools SET name=?,budget=? WHERE id=?",(name.strip(),budget,pool_id))
            self._audit(c,actor,'pool_configured',pool_id=pool_id,name=name.strip(),budget=budget)
        return pool_id

    def configure_policy(self, actor, *, pool_id, intro_enabled, default_credit,
                         eligible_domain="", eligible_institution="", expires_at=_KEEP, invite_only=_KEEP):
        # Read and update within one transaction to avoid overwriting a concurrent budget edit.
        with self._transaction() as c:
            self._admin(c, actor)
            pool = c.execute("SELECT * FROM allocation_pools WHERE id=?", (pool_id,)).fetchone()
            if not pool:
                raise ValueError("Unknown pool.")
            self._integer(default_credit)
            if type(intro_enabled) is not bool or default_credit > pool['budget']:
                raise ValueError("Credit exceeds pool budget.")
            for value in (eligible_domain, eligible_institution):
                if not isinstance(value,str) or len(value)>200:
                    raise ValueError("Invalid eligible cohort.")
            domain=eligible_domain.strip().lower()
            institution=eligible_institution.strip().lower()
            if domain and ("@" in domain or " " in domain or "." not in domain):
                raise ValueError("Use a complete email domain.")
            if intro_enabled and c.execute("SELECT 1 FROM allocation_pools WHERE intro_enabled=1 AND id!=?",(pool_id,)).fetchone():
                raise ValueError("Disable the other automatic-credit policy first.")
            since=pool['intro_since'] if pool['intro_enabled'] and intro_enabled else time.time()
            expiry=pool['expires_at'] if expires_at is _KEEP else self._expiry(expires_at,pool['expires_at'])
            only=self._flag(invite_only,pool['invite_only'])
            c.execute("UPDATE allocation_pools SET intro_enabled=?,default_credit=?,eligible_domain=?,eligible_institution=?,intro_since=?,expires_at=?,invite_only=? WHERE id=?",(int(intro_enabled),default_credit,domain,institution,since,expiry,only,pool_id))
            self._audit(c,actor,'policy_updated',pool_id=pool_id,intro_enabled=intro_enabled,default_credit=default_credit,eligible_domain=domain,eligible_institution=institution,expires_at=expiry,invite_only=bool(only))

    def adjust(self, actor, *, pool_id, user_id, delta, reason):
        self._integer(delta, -100_000_000)
        if not isinstance(reason, str) or not 4 <= len(reason.strip()) <= 500:
            raise ValueError("A reason of 4–500 characters is required.")
        with self._transaction() as c:
            self._admin(c, actor)
            self._user(c, user_id)
            p = c.execute("SELECT * FROM allocation_pools WHERE id=?", (pool_id,)).fetchone()
            if not p or not p['active']:
                raise ValueError("Unknown or inactive pool.")
            allocated = c.execute("SELECT COALESCE(SUM(credit),0) FROM allocation_accounts WHERE pool_id=?",
                                  (pool_id,)).fetchone()[0]
            row = c.execute("SELECT * FROM allocation_accounts WHERE pool_id=? AND user_id=?",
                            (pool_id,user_id)).fetchone()
            credit = (row['credit'] if row else 0) + delta
            floor = row['reserved'] + row['charged'] if row else 0
            if credit < floor or allocated + delta > p['budget']:
                raise ValueError("Adjustment exceeds pool funds or existing charges/reservations.")
            c.execute('''INSERT INTO allocation_accounts(pool_id,user_id,credit) VALUES(?,?,?)
                ON CONFLICT(pool_id,user_id) DO UPDATE SET credit=excluded.credit''', (pool_id,user_id,credit))
            self._audit(c, actor, "credit_adjusted", pool_id=pool_id,user_id=user_id,delta=delta,reason=reason.strip())

    def reserve(self, user_id, *, pool_id, request_key, application, preset, minutes, mode="demo"):
        if mode != "demo":
            raise PermissionError("Live project-funded AWS is disabled; credential and cost review required.")
        if application not in self.APPLICATIONS or preset not in self.PRESETS:
            raise ValueError("Choose a supported application and resource preset.")
        self._integer(minutes, 1, self.PRESETS[preset]['max_minutes'])
        if not isinstance(request_key,str) or not 1 <= len(request_key) <= 100:
            raise ValueError("A request key of 1–100 characters is required.")
        ceiling = (self.PRESETS[preset]['cents_per_hour'] * minutes + 59)//60 + 100
        with self._transaction() as c:
            self._user(c, user_id)
            previous = c.execute("SELECT * FROM allocation_jobs WHERE user_id=? AND request_key=?",
                                 (user_id,request_key)).fetchone()
            if previous:
                if (previous['pool_id'],previous['application'],previous['preset'],previous['minutes']) != (
                        pool_id,application,preset,minutes):
                    raise ValueError("Request key was already used for different job parameters.")
                return dict(previous)
            account = c.execute('''SELECT a.*,p.active,p.expires_at FROM allocation_accounts a
                JOIN allocation_pools p ON p.id=a.pool_id WHERE a.pool_id=? AND a.user_id=?''',
                (pool_id,user_id)).fetchone()
            if (not account or not account['active'] or self._expired(account['expires_at'])
                    or account['credit']-account['reserved']-account['charged']<ceiling):
                raise PermissionError("No authorized allocation or insufficient available credits.")
            if c.execute("SELECT COUNT(*) FROM allocation_jobs WHERE user_id=? AND state='reserved'",
                         (user_id,)).fetchone()[0] >= 2:
                raise PermissionError("At most two active demo jobs per user.")
            if c.execute("SELECT COUNT(*) FROM allocation_jobs WHERE state='reserved'").fetchone()[0] >= 10:
                raise PermissionError("Platform demo job limit reached.")
            job_id = uuid.uuid4().hex
            c.execute("UPDATE allocation_accounts SET reserved=reserved+? WHERE pool_id=? AND user_id=?",
                      (ceiling,pool_id,user_id))
            c.execute("INSERT INTO allocation_jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (job_id,user_id,pool_id,request_key,application,preset,minutes,ceiling,'reserved',time.time()))
            self._audit(c,user_id,"job_reserved",job_id=job_id,pool_id=pool_id,ceiling=ceiling,mode='demo')
            return dict(c.execute("SELECT * FROM allocation_jobs WHERE id=?", (job_id,)).fetchone())

    def finish(self, actor, *, job_id, cancel=False):
        if type(cancel) is not bool:
            raise ValueError("cancel must be a boolean.")
        with self._transaction() as c:
            self._user(c, actor)
            job = c.execute("SELECT * FROM allocation_jobs WHERE id=?", (job_id,)).fetchone()
            if not job or job['user_id'] != actor:
                raise PermissionError("Job is not owned by the signed-in user.")
            state = 'cancelled' if cancel else 'completed'
            if job['state'] != 'reserved':
                if job['state'] != state:
                    raise ValueError("Job already finalized.")
                return
            # Full ceiling charged on simulated completion; only a never-executed demo cancellation releases it.
            c.execute("UPDATE allocation_accounts SET reserved=reserved-?,charged=charged+? WHERE pool_id=? AND user_id=?",
                      (job['ceiling'],0 if cancel else job['ceiling'],job['pool_id'],actor))
            c.execute("UPDATE allocation_jobs SET state=? WHERE id=?", (state,job_id))
            self._audit(c,actor,"job_"+state,job_id=job_id,charge=0 if cancel else job['ceiling'])

    def overview(self, actor, *, admin=False):
        with self._transaction() as c:
            self._user(c, actor)
            if admin:
                self._admin(c, actor)
            pools = [dict(r) for r in c.execute('''SELECT p.*,COALESCE(SUM(a.credit),0) allocated
                FROM allocation_pools p LEFT JOIN allocation_accounts a ON a.pool_id=p.id GROUP BY p.id''')]
            now = time.time()
            accounts = [dict(r) for r in c.execute('''SELECT a.*,p.name,p.expires_at,u.display_name,u.email,credit-reserved-charged available
                FROM allocation_accounts a JOIN allocation_pools p ON p.id=a.pool_id JOIN users u ON u.id=a.user_id'''+
                ("" if admin else " WHERE a.user_id=?"), () if admin else (actor,))]
            jobs = [dict(r) for r in c.execute("SELECT j.*,u.display_name,u.email,p.name pool_name FROM allocation_jobs j JOIN users u ON u.id=j.user_id JOIN allocation_pools p ON p.id=j.pool_id"+
                ("" if admin else " WHERE j.user_id=?")+" ORDER BY j.created_at DESC LIMIT 100", () if admin else (actor,))]
            audit = [dict(r) for r in c.execute("SELECT a.*,u.display_name actor_name,u.email actor_email FROM allocation_audit a LEFT JOIN users u ON u.id=a.actor ORDER BY a.created_at DESC LIMIT 100")] if admin else []
            for a in accounts:
                # Unused credit lapses at the end date; credit/reserved/charged history is untouched.
                a['expired']=self._expired(a['expires_at'],now)
                a['lapsed']=a['available'] if a['expired'] else 0
                if a['expired']:
                    a['available']=0
            funded = []
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_funding_jobs'").fetchone():
                for r in c.execute('''SELECT j.id,j.user_id,j.pool_id,j.policy_id,j.spec_json,j.ceiling,j.state,j.charged,j.outcome,
                        j.external_job_id,j.created_at,j.updated_at,u.display_name,u.email,p.name pool_name
                        FROM project_funding_jobs j JOIN users u ON u.id=j.user_id LEFT JOIN allocation_pools p ON p.id=j.pool_id'''+
                        ("" if admin else " WHERE j.user_id=?")+" ORDER BY j.created_at DESC,j.rowid DESC LIMIT 100", () if admin else (actor,)):
                    job=dict(r)
                    try:
                        job['model']=str(json.loads(job.pop('spec_json')).get('model',''))
                    except (ValueError,AttributeError):
                        job['model']=''
                    funded.append(job)
            for pool in pools:
                rows=[a for a in accounts if a['pool_id']==pool['id']]
                pool['expired']=self._expired(pool['expires_at'],now)
                if not admin:
                    continue
                pool['invite_count']=c.execute("SELECT COUNT(*) FROM allocation_invites WHERE pool_id=?",(pool['id'],)).fetchone()[0]
                pool['lapsed_user_credit']=sum(a['lapsed'] for a in rows)
                pool['available_user_credit']=sum(a['available'] for a in rows)
                pool['reserved']=sum(a['reserved'] for a in rows)
                pool['simulated_charges']=sum(a['charged'] for a in rows)
                pool['unallocated']=pool['budget']-pool['allocated']
                pool['new_user_grant_capacity']=pool['unallocated']//pool['default_credit'] if pool['default_credit'] else None
            return dict(mode="demo",live_project_aws_enabled=False,pools=pools if admin else [],
                        accounts=accounts,jobs=jobs,funded_jobs=funded,audit=audit,presets=self.PRESETS)

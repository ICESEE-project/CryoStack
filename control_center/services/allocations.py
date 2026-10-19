"""Persistent resource allocations. Integer cents; no AWS execution or billing API."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager


class AllocationService:
    # Conservative demonstration ceilings, not AWS prices. No caller-supplied rates.
    PRESETS = {"small": {"cents_per_hour": 200, "max_minutes": 60},
               "medium": {"cents_per_hour": 800, "max_minutes": 30}}
    APPLICATIONS = {"cryolauncher", "icesee", "frozen-legacies", "livist"}

    def __init__(self, storage):
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
                CREATE TABLE IF NOT EXISTS allocation_jobs (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    pool_id TEXT NOT NULL, request_key TEXT NOT NULL,
                    application TEXT NOT NULL, preset TEXT NOT NULL, minutes INTEGER NOT NULL,
                    ceiling INTEGER NOT NULL CHECK(ceiling>0), state TEXT NOT NULL,
                    created_at REAL NOT NULL, UNIQUE(user_id,request_key),
                    FOREIGN KEY(pool_id,user_id) REFERENCES allocation_accounts(pool_id,user_id));
                CREATE TABLE IF NOT EXISTS allocation_audit (
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL,
                    details TEXT NOT NULL, created_at REAL NOT NULL);
            ''')
            columns = {r['name'] for r in c.execute('PRAGMA table_info(allocation_pools)')}
            for column in ('eligible_domain', 'eligible_institution'):
                if column not in columns:
                    c.execute(f"ALTER TABLE allocation_pools ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            c.executescript('''
                DROP TRIGGER IF EXISTS allocation_new_user;
                CREATE TRIGGER allocation_new_user AFTER INSERT ON users
                BEGIN
                    INSERT OR IGNORE INTO allocation_accounts(pool_id,user_id,credit)
                    SELECT p.id,NEW.id,p.default_credit FROM allocation_pools p
                    WHERE p.active=1 AND p.intro_enabled=1 AND NEW.created_at>=p.intro_since
                    AND (p.eligible_domain='' OR lower(substr(NEW.email,instr(NEW.email,'@')+1))=p.eligible_domain)
                    AND (p.eligible_institution='' OR lower(trim(COALESCE(NEW.institution,'')))=p.eligible_institution)
                    AND p.default_credit>0 AND p.budget >= p.default_credit +
                        COALESCE((SELECT SUM(credit) FROM allocation_accounts WHERE pool_id=p.id),0)
                    AND NOT EXISTS(SELECT 1 FROM allocation_intro_seen WHERE user_id=NEW.id);
                    INSERT INTO allocation_audit(id,actor,action,details,created_at)
                    SELECT lower(hex(randomblob(16))),NEW.id,'intro_granted',
                        json_object('pool_id',pool_id,'cents',credit),NEW.created_at
                    FROM allocation_accounts WHERE user_id=NEW.id;
                    INSERT OR IGNORE INTO allocation_intro_seen(user_id) VALUES(NEW.id);
                END;
            ''')

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

    def configure_pool(self, actor, *, name, budget, intro_enabled=False, default_credit=0, pool_id=None,
                       eligible_domain="", eligible_institution=""):
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
            c.execute('''INSERT INTO allocation_pools(id,name,budget,intro_enabled,default_credit,intro_since,active,eligible_domain,eligible_institution) VALUES(?,?,?,?,?,?,1,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,budget=excluded.budget,
                intro_enabled=excluded.intro_enabled,default_credit=excluded.default_credit,
                intro_since=excluded.intro_since,eligible_domain=excluded.eligible_domain,
                eligible_institution=excluded.eligible_institution''',
                (pool_id, name.strip(), budget, int(intro_enabled), default_credit, since, eligible_domain, eligible_institution))
            self._audit(c, actor, "pool_configured", pool_id=pool_id, name=name.strip(), budget=budget,
                        intro_enabled=intro_enabled, default_credit=default_credit,
                        eligible_domain=eligible_domain, eligible_institution=eligible_institution)
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
            return {'matching_existing_users':count,'unallocated':remaining,
                    'new_user_grant_capacity':remaining//pool['default_credit'] if pool['default_credit']>0 else None,
                    'intro_enabled':bool(pool['intro_enabled']),
                    'retroactive_grants':False}

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
                         eligible_domain="", eligible_institution=""):
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
            c.execute("UPDATE allocation_pools SET intro_enabled=?,default_credit=?,eligible_domain=?,eligible_institution=?,intro_since=? WHERE id=?",(int(intro_enabled),default_credit,domain,institution,since,pool_id))
            self._audit(c,actor,'policy_updated',pool_id=pool_id,intro_enabled=intro_enabled,default_credit=default_credit,eligible_domain=domain,eligible_institution=institution)

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
            account = c.execute('''SELECT a.*,p.active FROM allocation_accounts a
                JOIN allocation_pools p ON p.id=a.pool_id WHERE a.pool_id=? AND a.user_id=?''',
                (pool_id,user_id)).fetchone()
            if not account or not account['active'] or account['credit']-account['reserved']-account['charged']<ceiling:
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
            accounts = [dict(r) for r in c.execute('''SELECT a.*,p.name,u.display_name,u.email,credit-reserved-charged available
                FROM allocation_accounts a JOIN allocation_pools p ON p.id=a.pool_id JOIN users u ON u.id=a.user_id'''+
                ("" if admin else " WHERE a.user_id=?"), () if admin else (actor,))]
            jobs = [dict(r) for r in c.execute("SELECT j.*,u.display_name,u.email,p.name pool_name FROM allocation_jobs j JOIN users u ON u.id=j.user_id JOIN allocation_pools p ON p.id=j.pool_id"+
                ("" if admin else " WHERE j.user_id=?")+" ORDER BY j.created_at DESC LIMIT 100", () if admin else (actor,))]
            audit = [dict(r) for r in c.execute("SELECT a.*,u.display_name actor_name,u.email actor_email FROM allocation_audit a LEFT JOIN users u ON u.id=a.actor ORDER BY a.created_at DESC LIMIT 100")] if admin else []
            for pool in pools:
                rows=[a for a in accounts if a['pool_id']==pool['id']]
                if not admin:
                    continue
                pool['available_user_credit']=sum(a['available'] for a in rows)
                pool['reserved']=sum(a['reserved'] for a in rows)
                pool['simulated_charges']=sum(a['charged'] for a in rows)
                pool['unallocated']=pool['budget']-pool['allocated']
                pool['new_user_grant_capacity']=pool['unallocated']//pool['default_credit'] if pool['default_credit'] else None
            return dict(mode="demo",live_project_aws_enabled=False,pools=pools if admin else [],
                        accounts=accounts,jobs=jobs,audit=audit,presets=self.PRESETS)

"""Control Center diagnostics: actionable platform health.

Every check reports a status, a detail, and -- when something is wrong --
what to do about it. Checks are labelled by kind:

* ``live`` -- measured now (HTTP probes, TLS handshake, database checks, disk
  space); the snapshot carries its ``measured_at`` time and is cached for
  :data:`CACHE_S` seconds;
* ``historical`` -- read from records (index runs, experiment outcomes);
* ``configuration`` -- what is configured, without contacting anything.

Rules: probes use loopback HTTP with short timeouts and run off the event
loop; HPC and cloud connectivity is reported only from existing structured
checks (no user credentials are used, none are shown); TLS reads the served
certificate (a handshake) or the public certificate file -- never a private
key; database checks open SQLite read-only and bound ``quick_check`` in time.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import socket
import sqlite3
import ssl
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ..storage import ControlStorage


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "deployment" / "applications.yaml"
PROBE_AGENT = "CryoStack-Diagnostics/1.0"
PROBE_TIMEOUT_S = 3.0
CACHE_S = 15.0
MIN_REFRESH_S = 3.0
QUICK_CHECK_S = 2.0
TLS_TIMEOUT_S = 4.0
TLS_WARN_DAYS = 21
DISK_WARN_FRACTION = 0.05
DISK_WARN_BYTES = 5 * 1024 ** 3
WAL_WARN_BYTES = 256 * 1024 * 1024
DEFAULT_PUBLIC_HOST = "cryostack.eas.gatech.edu"
PUBLIC_HOST_ENV = "CRYOSTACK_PUBLIC_HOSTNAME"
RELAY_URL_ENV = "CRYOSTACK_DIAGNOSTICS_RELAY_URL"
DEFAULT_RELAY_URL = "http://127.0.0.1:8899"
CERT_LIVE_DIR = Path("/etc/letsencrypt/live")
#: Frozen Legacies index worker constants (radar/index_worker.py HEARTBEAT_S,
#: catalog_routes.STALE_RUN_S) -- shown read-only
INDEX_HEARTBEAT_S = 5.0
INDEX_STALE_S = 90.0

_PROCESS_STARTED = time.time()


def _check(name, status, detail, *, action=None, kind="live", measured_at=None):
    return {"name": name, "status": status, "detail": detail, "action": action,
            "kind": kind, "measured_at": measured_at}


def human_bytes(value) -> str:
    if value is None:
        return "—"
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _health_module():
    """deployment/health_check.py (not a package): its registry parsing is
    the single definition of the health targets."""
    name = "cryostack_deployment_health_check"
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "deployment" / "health_check.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module          # dataclasses resolve their module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return module


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True, timeout=1)


# ── application availability ────────────────────────────────────────
#: the same request semantics as deployment/health_check.py (urllib,
#: redirects followed: "/" redirects to the book's index page and an
#: authenticated application redirects anonymous requests to the sign-in page)
_OPENER = urllib.request.build_opener()


def probe_target(base_url: str, target, *, timeout: float = PROBE_TIMEOUT_S,
                 opener=None) -> dict:
    """One registered health target over loopback HTTP, judged like
    ``deployment/health_check.py`` judges it."""
    opener = opener or _OPENER
    url = base_url.rstrip("/") + target.path
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": PROBE_AGENT})
    started = time.monotonic()
    body = ""
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            if target.required_text:
                body = response.read(256 * 1024).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        status = error.code
    except Exception as error:
        return {"ok": False, "status": None, "elapsed_ms": None,
                "detail": f"{type(error).__name__}: {getattr(error, 'reason', error)}"}
    elapsed = int((time.monotonic() - started) * 1000)
    if status not in target.expected_statuses:
        expected = ", ".join(map(str, target.expected_statuses))
        return {"ok": False, "status": status, "elapsed_ms": elapsed,
                "detail": f"HTTP {status} (expected {expected})"}
    if any(text not in body for text in target.required_text):
        return {"ok": False, "status": status, "elapsed_ms": elapsed,
                "detail": "missing expected content"}
    return {"ok": True, "status": status, "elapsed_ms": elapsed, "detail": f"HTTP {status}"}


# ── TLS ─────────────────────────────────────────────────────────────
def certificate_file_expiry(path: Path) -> float:
    """Expiry of the first certificate of a public PEM file."""
    try:
        from cryptography import x509
    except ImportError:                                  # stdlib fallback
        decoded = ssl._ssl._test_decode_cert(str(path))
        return ssl.cert_time_to_seconds(decoded["notAfter"])
    cert = x509.load_pem_x509_certificate(Path(path).read_bytes())
    expiry = getattr(cert, "not_valid_after_utc", None)
    if expiry is None:
        expiry = cert.not_valid_after.replace(tzinfo=timezone.utc)
    return expiry.timestamp()


def served_certificate(host: str, port: int = 443, *, timeout: float = TLS_TIMEOUT_S) -> dict:
    """Handshake with the public host and read the served certificate."""
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            cert = tls.getpeercert()
    issuer = dict(item[0] for item in cert.get("issuer", ()))
    return {"not_after": ssl.cert_time_to_seconds(cert["notAfter"]),
            "issuer": issuer.get("organizationName") or issuer.get("commonName")}


def public_hostname() -> str:
    configured = (os.environ.get(PUBLIC_HOST_ENV) or "").strip()
    if configured:
        return configured
    base = (os.environ.get("CRYOSTACK_PUBLIC_BASE") or "").strip()
    if base.startswith("https://"):
        return base[len("https://"):].split("/")[0].split(":")[0]
    return DEFAULT_PUBLIC_HOST


def tls_status(not_after: float, now: float) -> tuple[str, str, str | None]:
    days = (not_after - now) / 86400
    when = datetime.fromtimestamp(not_after, tz=timezone.utc).strftime("%Y-%m-%d")
    if days <= 0:
        return ("failed", f"Expired on {when}",
                "Renew the certificate (certbot renew) and reload nginx.")
    if days <= TLS_WARN_DAYS:
        return ("degraded", f"Expires {when} ({days:.0f} days)",
                "Check the certbot renewal timer; renewal normally runs 30 days before expiry.")
    return "healthy", f"Valid until {when} ({days:.0f} days)", None


# ── SQLite ──────────────────────────────────────────────────────────
def database_check(label: str, path: Path, *, now: float, expect_private: bool,
                   optional: bool = False) -> dict:
    path = Path(path)
    if not path.is_file():
        if optional:
            return _check(label, "disabled", "Not created on this server", measured_at=now)
        return _check(label, "failed", "Database file not found",
                      action="Check the configured database path.", measured_at=now)
    try:
        info = path.stat()
    except OSError as error:
        return _check(label, "failed", f"Cannot read file status ({error.strerror})",
                      measured_at=now)
    mode = stat.S_IMODE(info.st_mode)
    wal = Path(str(path) + "-wal")
    wal_size = wal.stat().st_size if wal.is_file() else 0
    parts = [human_bytes(info.st_size), f"WAL {human_bytes(wal_size)}", f"mode {mode:03o}"]
    status, action = "healthy", None
    deadline = time.monotonic() + QUICK_CHECK_S
    try:
        connection = _read_only(path)
        try:
            connection.set_progress_handler(
                lambda: 1 if time.monotonic() > deadline else 0, 10_000)
            messages = [row[0] for row in connection.execute("PRAGMA quick_check(5)")]
        finally:
            connection.close()
        if messages != ["ok"]:
            status = "failed"
            parts.append("quick_check: " + "; ".join(messages)[:200])
            action = "Back up the file and run PRAGMA integrity_check offline."
        else:
            parts.append("quick_check ok")
    except sqlite3.OperationalError as error:
        if "interrupt" in str(error):
            status = "unknown"
            parts.append(f"quick_check not finished within {QUICK_CHECK_S:.0f} s")
        else:
            status = "failed"
            parts.append("cannot open read-only")
            action = "Check ownership and permissions of the database and its directory."
    except sqlite3.Error as error:
        status = "failed"
        parts.append(type(error).__name__)
    if expect_private and mode & 0o007:
        if status == "healthy":
            status = "degraded"
        action = action or f"Restrict permissions: chmod 600 {path.name}"
        parts.append("readable by other users")
    if wal_size > WAL_WARN_BYTES and status == "healthy":
        status = "degraded"
        parts.append("large WAL")
        action = "A long-lived reader is preventing checkpoints; restart the gateway at a quiet time."
    return _check(label, status, " · ".join(parts), action=action, measured_at=now)


# ── storage ─────────────────────────────────────────────────────────
def storage_check(label: str, path: Path, *, now: float, needs_write: bool = True) -> dict:
    path = Path(path)
    if not path.exists():
        if needs_write:
            parent = path
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            writable = os.access(parent, os.W_OK)
            return _check(label, "healthy" if writable else "failed",
                          "Not created yet (created on first use)" if writable
                          else "Missing, and its parent is not writable",
                          action=None if writable else "Create the directory for the service user.",
                          measured_at=now)
        return _check(label, "failed", "Directory not found",
                      action="Check the configured path and that the volume is mounted.",
                      measured_at=now)
    readable = os.access(path, os.R_OK)
    writable = os.access(path, os.W_OK)
    try:
        usage = shutil.disk_usage(path)
    except OSError as error:
        return _check(label, "failed", f"Cannot read disk usage ({error.strerror})",
                      measured_at=now)
    fraction = usage.free / usage.total if usage.total else 0
    parts = [f"{human_bytes(usage.free)} free of {human_bytes(usage.total)} ({fraction:.0%})",
             "writable" if writable else "read-only"]
    status, action = "healthy", None
    if not readable:
        status, action = "failed", "The service user cannot read this directory."
    elif needs_write and not writable:
        status, action = "failed", "The service user cannot write this directory."
    elif needs_write and (fraction < DISK_WARN_FRACTION or usage.free < DISK_WARN_BYTES):
        status, action = "degraded", "Free disk space is low; clean up or extend the volume."
    return _check(label, status, " · ".join(parts), action=action, measured_at=now)


class DiagnosticsService:

    def __init__(
        self,
        storage: ControlStorage,
        *,
        ops_database: Path | None = None,
        catalog_path=None,
        registry_path: Path | None = None,
        working_cache_dir=None,
        workspace_root=None,
        ursa_availability=None,
        tls_probe=served_certificate,
        relay_opener=None,
        clock=time.time,
    ) -> None:
        self.storage = storage
        self.ops_database = ops_database
        self._catalog_path = catalog_path
        self.registry_path = Path(registry_path) if registry_path else REGISTRY
        self._working_cache_dir = working_cache_dir
        self._workspace_root = workspace_root
        self._ursa_availability = ursa_availability
        self.tls_probe = tls_probe
        self.relay_opener = relay_opener or _OPENER
        self.clock = clock
        self._cache: tuple[float, str, dict] | None = None
        self._lock = threading.Lock()

    # ── lazily resolved sources ─────────────────────────────────────
    def catalog_path(self) -> Path:
        if self._catalog_path is not None:
            return Path(self._catalog_path)
        from icesee_jupyter_book.applications.frozen_legacies.radar.catalog import catalog_path
        return catalog_path()

    def working_cache_dir(self) -> Path:
        if self._working_cache_dir is not None:
            return Path(self._working_cache_dir)
        from icesee_jupyter_book.applications.frozen_legacies.radar.working_cache import (
            working_cache)
        return Path(working_cache().directory)

    def workspace_root(self) -> Path:
        if self._workspace_root is not None:
            return Path(self._workspace_root)
        from cryostack_src.workspace.roots import resolve_workspace_root
        return resolve_workspace_root()

    def ursa_availability(self) -> dict:
        if self._ursa_availability is not None:
            return self._ursa_availability()
        from icesee_jupyter_book.applications.frozen_legacies.radar import automatic
        return automatic.availability()

    # ── public ──────────────────────────────────────────────────────
    async def collect(self, *, app=None, base_url: str = "http://127.0.0.1:8080",
                      refresh: bool = False) -> dict:
        """A diagnostics snapshot, measured off the event loop and cached
        briefly (a refresh is honoured once the snapshot is a few seconds
        old, so the page cannot be used to hammer the probes)."""
        with self._lock:
            cached = self._cache
        if cached and cached[1] == base_url:
            age = self.clock() - cached[0]
            if age < CACHE_S and not (refresh and age >= MIN_REFRESH_S):
                return {**cached[2], "cached": True}
        data = await asyncio.to_thread(self.measure, base_url)
        data["sections"].insert(0, self.gateway_section(app, data["measured_at"]))
        data["summary"] = self._summary(data["sections"])
        with self._lock:
            self._cache = (data["measured_at"], base_url, data)
        return {**data, "cached": False}

    def get_diagnostics(self, *, base_url: str = "http://127.0.0.1:8080") -> dict:
        """Synchronous snapshot without the gateway's process state."""
        data = self.measure(base_url)
        data["sections"].insert(0, self.gateway_section(None, data["measured_at"]))
        data["summary"] = self._summary(data["sections"])
        return data

    def measure(self, base_url: str) -> dict:
        now = self.clock()
        jobs = (
            ("applications", "Application availability",
             lambda: self.applications_section(base_url, now)),
            ("connections", "Connections", lambda: self.connections_section(now)),
            ("workers", "Workers and indexing", lambda: self.workers_section(now)),
            ("databases", "Databases", lambda: self.databases_section(now)),
            ("storage", "Storage", lambda: self.storage_section(now)),
            ("tls", "TLS certificate", lambda: self.tls_section(now)),
        )
        sections = []
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [(key, title, pool.submit(job)) for key, title, job in jobs]
            for key, title, future in futures:
                try:
                    sections.append(future.result(timeout=30))
                except Exception as error:
                    sections.append({"id": key, "title": title, "kind": "live", "checks": [
                        _check(title, "unknown", f"Check did not run ({type(error).__name__})",
                               measured_at=now)]})
        return {"measured_at": now, "cache_seconds": CACHE_S, "sections": sections,
                "summary": self._summary(sections)}

    @staticmethod
    def _summary(sections: list[dict]) -> dict:
        counts: dict[str, int] = {}
        for section in sections:
            for check in section["checks"]:
                counts[check["status"]] = counts.get(check["status"], 0) + 1
        return counts

    # ── sections ────────────────────────────────────────────────────
    def gateway_section(self, app, now: float) -> dict:
        checks = [_check(
            "Gateway process", "healthy",
            f"Serving · up {_duration(now - _PROCESS_STARTED)} · Python {sys.version.split()[0]}",
            measured_at=now,
        )]
        try:
            state = app.get("state") if app is not None else None
        except Exception:
            state = None
        lazy = os.environ.get("CRYOSTACK_APP_START_MODE", "background").strip().lower() == "lazy"
        for attr, label in (("icesheets", "CryoLauncher backend (Voila)"),
                            ("run_center", "ICESEE backend (Voila)")):
            service = getattr(state, attr, None)
            if service is None:
                continue
            value = getattr(getattr(service, "state", None), "value", "unknown")
            port = getattr(service, "port", "?")
            if value == "ready":
                checks.append(_check(label, "healthy", f"Ready on 127.0.0.1:{port}",
                                     measured_at=now))
            elif value == "starting":
                checks.append(_check(label, "unknown", "Starting", measured_at=now))
            elif value == "failed":
                checks.append(_check(label, "failed",
                                     f"Failed to start: {str(service.error)[:200]}",
                                     action="Open the application to retry; check icesee.log.",
                                     measured_at=now))
            else:
                checks.append(_check(
                    label, "disabled" if lazy else "unknown",
                    "Stopped (lazy start: starts on its first request)" if lazy else "Stopped",
                    action=None if lazy else
                    "Open the application to start it; check icesee.log if it fails.",
                    measured_at=now))
        if state is None:
            checks.append(_check("Voila backends", "unknown",
                                 "Not managed by this process", kind="configuration"))
        return {"id": "gateway", "title": "Gateway", "kind": "live", "checks": checks}

    def _registry(self, health) -> dict:
        if self.registry_path == REGISTRY:
            return health.load_registry()
        import yaml
        with self.registry_path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}

    def applications_section(self, base_url: str, now: float) -> dict:
        section = {"id": "applications", "title": "Application availability", "kind": "live",
                   "note": "Health targets registered in deployment/applications.yaml, probed "
                           "over loopback HTTP with a 3 s timeout, judged like deployment/health_check.py."}
        try:
            health = _health_module()
            registry = self._registry(health)
            targets = health.registered_health_targets(registry)
        except Exception as error:
            section["checks"] = [_check(
                "Deployment registry", "failed",
                f"applications.yaml could not be read ({type(error).__name__})",
                action="Validate it with deployment/preflight.py.", measured_at=now)]
            return section
        titles = {}
        for name, application in (registry.get("applications") or {}).items():
            target = (application.get("health") or {}).get("target")
            if target and target not in titles:
                titles[target] = application.get("title") or name
        titles.setdefault("cryostack", "CryoStack site")
        titles.setdefault("cryolauncher", "CryoLauncher")
        titles.setdefault("icesee", "ICESEE")
        checks = []
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as pool:
            results = {name: pool.submit(probe_target, base_url, target)
                       for name, target in targets.items()}
            for name, target in targets.items():
                result = results[name].result()
                elapsed = (f" · {result['elapsed_ms']} ms"
                           if result["elapsed_ms"] is not None else "")
                checks.append(_check(
                    f"{titles.get(name, name)} {target.path}",
                    "healthy" if result["ok"] else "failed",
                    result["detail"] + elapsed,
                    action=None if result["ok"] else
                    "Run deployment/health_check.py on the host and check the gateway log "
                    "and the application's build artifacts.",
                    measured_at=now))
        section["checks"] = checks
        return section

    def connections_section(self, now: float) -> dict:
        checks = []
        relay = (os.environ.get(RELAY_URL_ENV) or DEFAULT_RELAY_URL).rstrip("/")
        request = urllib.request.Request(
            f"{relay}/connector/status/diagnostics-probe",
            headers={"User-Agent": PROBE_AGENT})
        try:
            with self.relay_opener.open(request, timeout=PROBE_TIMEOUT_S) as response:
                ok, status_text = response.status == 200, f"HTTP {response.status}"
        except urllib.error.HTTPError as error:
            ok, status_text = False, f"HTTP {error.code}"
        except Exception as error:
            ok, status_text = False, type(error).__name__
        checks.append(_check(
            "HPC connector relay", "healthy" if ok else "failed",
            f"Answering ({status_text})" if ok else f"Not reachable ({status_text})",
            action=None if ok else
            "Start the relay on the host (deployment/services.sh start-connector).",
            measured_at=now))
        checks.append(_check(
            "HPC clusters", "unknown",
            "Cluster access uses each user's own SSH or connector session; the server holds "
            "no credentials to test it. Per-run status is on the HPC page.",
            kind="configuration"))
        aws = bool(os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION"))
        checks.append(_check(
            "AWS cloud execution", "configured" if aws else "disabled",
            "Region configured in the gateway environment" if aws else "No AWS region configured",
            kind="configuration"))
        checks.extend(self._cloud_history(now))
        for provider, names in (
            ("GitHub sign-in", ("CRYOSTACK_GITHUB_CLIENT_ID", "CRYOSTACK_GITHUB_CLIENT_SECRET",
                                "CRYOSTACK_GITHUB_REDIRECT_URI")),
            ("ORCID sign-in", ("CRYOSTACK_ORCID_CLIENT_ID", "CRYOSTACK_ORCID_CLIENT_SECRET",
                               "CRYOSTACK_ORCID_REDIRECT_URI")),
        ):
            configured = all(os.environ.get(name) for name in names)
            checks.append(_check(provider, "configured" if configured else "disabled",
                                 "Client configured" if configured else "Not configured",
                                 kind="configuration"))
        return {"id": "connections", "title": "Connections", "kind": "mixed", "checks": checks}

    def _cloud_history(self, now: float) -> list[dict]:
        path = Path(self.storage.database_path)
        if not path.is_file():
            return []
        try:
            connection = _read_only(path)
            try:
                rows = connection.execute(
                    "SELECT status, COUNT(*) FROM experiments WHERE created_at >= ?"
                    " AND (lower(backend) LIKE '%cloud%' OR lower(backend) LIKE '%aws%'"
                    " OR lower(backend) LIKE '%batch%') GROUP BY status",
                    (now - 7 * 86400,)).fetchall()
            finally:
                connection.close()
        except sqlite3.Error:
            return []
        counts = {str(status).lower(): int(n) for status, n in rows}
        if not counts:
            return [_check("Cloud runs (7 days)", "healthy", "No cloud runs recorded",
                           kind="historical")]
        failed = counts.get("failed", 0)
        finished = failed + counts.get("completed", 0) + counts.get("cancelled", 0)
        status = "degraded" if finished and failed / finished > 0.5 else "healthy"
        return [_check(
            "Cloud runs (7 days)", status,
            ", ".join(f"{n} {s}" for s, n in sorted(counts.items())), kind="historical",
            action="Open the failed runs on the Experiments page for their AWS diagnostics."
            if status != "healthy" else None)]

    def tls_section(self, now: float) -> dict:
        host = public_hostname()
        label = f"Served certificate ({host})"
        checks = []
        try:
            served = self.tls_probe(host)
            status, detail, action = tls_status(served["not_after"], now)
            if served.get("issuer"):
                detail += f" · issuer {served['issuer']}"
            checks.append(_check(label, status, detail, action=action, measured_at=now))
        except ssl.SSLCertVerificationError as error:
            checks.append(_check(label, "failed",
                                 f"Verification failed: {error.verify_message}",
                                 action="Renew or reinstall the certificate.", measured_at=now))
        except Exception as error:
            checks.append(_check(label, "unknown",
                                 f"No TLS handshake from this host ({type(error).__name__})",
                                 measured_at=now))
        # the public certificate only; private keys are never opened
        cert_file = CERT_LIVE_DIR / host / "fullchain.pem"
        try:
            readable = cert_file.is_file() and os.access(cert_file, os.R_OK)
        except OSError:
            readable = False
        if readable:
            try:
                status, detail, action = tls_status(certificate_file_expiry(cert_file), now)
                checks.append(_check("Certificate file (fullchain.pem)", status, detail,
                                     action=action, measured_at=now))
            except Exception as error:
                checks.append(_check("Certificate file (fullchain.pem)", "unknown",
                                     f"Not parsable ({type(error).__name__})", measured_at=now))
        return {"id": "tls", "title": "TLS certificate", "kind": "live", "checks": checks}

    def workers_section(self, now: float) -> dict:
        checks = []
        path = self.catalog_path()
        if not path.is_file():
            checks.append(_check("Frozen Legacies index workers", "disabled",
                                 "No catalog on this server", measured_at=now))
        else:
            try:
                connection = _read_only(path)
                connection.row_factory = sqlite3.Row
                try:
                    active = connection.execute(
                        "SELECT run_id, source_id, status, started_at, heartbeat_at"
                        " FROM index_runs WHERE status IN ('queued', 'running')").fetchall()
                    recent = connection.execute(
                        "SELECT status, COUNT(*) AS n FROM index_runs WHERE started_at >= ?"
                        " AND status IN ('failed', 'interrupted', 'unavailable') GROUP BY status",
                        (now - 7 * 86400,)).fetchall()
                    asset_errors = connection.execute(
                        "SELECT COUNT(*) FROM radar_assets"
                        " WHERE status IN ('invalid', 'unavailable')").fetchone()[0]
                finally:
                    connection.close()
            except sqlite3.Error as error:
                checks.append(_check("Frozen Legacies index workers", "unknown",
                                     f"Catalog not readable ({type(error).__name__})",
                                     measured_at=now))
            else:
                if not active:
                    checks.append(_check("Active index runs", "healthy", "None running",
                                         measured_at=now))
                for run in active:
                    age = now - (run["heartbeat_at"] or run["started_at"])
                    stalled = age > INDEX_STALE_S
                    checks.append(_check(
                        f"Index run #{run['run_id']} ({run['source_id']})",
                        "failed" if stalled else "healthy",
                        f"{run['status']} · last heartbeat {age:.0f} s ago",
                        action="The worker has stopped. Open the Frozen Legacies data sources "
                               "(marks the run interrupted) and retry." if stalled else None,
                        measured_at=now))
                counts = {row["status"]: row["n"] for row in recent}
                checks.append(_check(
                    "Index failures (7 days)", "degraded" if counts else "healthy",
                    ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "None",
                    action="Review the runs on the Frozen Legacies data-sources page; a retry "
                           "continues incrementally." if counts else None,
                    kind="historical"))
                if asset_errors:
                    checks.append(_check(
                        "Files not indexable", "degraded",
                        f"{asset_errors} file(s) recorded invalid or unavailable",
                        action="Use Retry on the source to re-read them.", kind="historical"))
        checks.append(_check(
            "Index worker limits", "configured",
            f"One worker process per source · heartbeat every {INDEX_HEARTBEAT_S:.0f} s · "
            f"marked interrupted after {INDEX_STALE_S:.0f} s without one",
            kind="configuration"))
        try:
            availability = self.ursa_availability()
            available = bool(availability.get("available"))
            checks.append(_check(
                "URSA automatic picker", "healthy" if available else "disabled",
                "Available" if available else (availability.get("reason") or "Not available"),
                action=None if available else
                "Install URSA and its dependencies (CRYOSTACK_FROZEN_LEGACIES_URSA_ROOT and "
                "CRYOSTACK_FROZEN_LEGACIES_URSA_PYTHON).",
                measured_at=now))
        except Exception as error:
            checks.append(_check("URSA automatic picker", "unknown",
                                 f"Availability not determined ({type(error).__name__})",
                                 measured_at=now))
        return {"id": "workers", "title": "Workers and indexing", "kind": "mixed",
                "checks": checks}

    def databases_section(self, now: float) -> dict:
        checks = [
            database_check("Auth and experiments", self.storage.database_path,
                           now=now, expect_private=True),
            database_check("Frozen Legacies catalog", self.catalog_path(),
                           now=now, expect_private=True, optional=True),
        ]
        if self.ops_database is not None:
            checks.append(database_check("Control Center operations", self.ops_database,
                                         now=now, expect_private=True))
        return {"id": "databases", "title": "Databases (SQLite)", "kind": "live",
                "checks": checks}

    def storage_section(self, now: float) -> dict:
        checks = [
            storage_check("Workspace root", self.workspace_root(), now=now),
            storage_check("Frozen Legacies working cache", self.working_cache_dir(), now=now),
            storage_check("Service data directory", Path(self.storage.database_path).parent,
                          now=now),
        ]
        try:
            from icesee_jupyter_book.applications.frozen_legacies.radar.storage import (
                approved_roots, mask_location)
            roots = approved_roots()
        except Exception:
            roots, mask_location = [], str
        for root in roots:
            checks.append(storage_check(f"Approved data root {mask_location(str(root))}",
                                        root, now=now, needs_write=False))
        if not roots:
            checks.append(_check("Approved local data roots", "disabled",
                                 "None configured", kind="configuration"))
        return {"id": "storage", "title": "Storage", "kind": "live", "checks": checks}

"""Authenticated-user, per-resource configuration state (B2).

The gateways own widgets; this module owns the *shape* of the persisted state
and the safe hydration lifecycle. It performs no I/O -- the controller is given
``load_state`` / ``save_state`` callbacks so the same logic serves every
CryoLauncher application.

Ownership (established in B1):

    RESOURCE facts       login host, port, scheduler defaults, VPN/MFA -- live
                         in ComputeProfile, never persisted here for a known
                         resource. Only a *custom* resource persists a
                         user-entered host/port.
    USER x RESOURCE      hpc_username, remote_directory, account, access_mode,
                         auth_mode -- persisted per (user, resource).
    USER                 email -- persisted per resource for now (B4 decides the
                         final Slurm UX); still a user preference.
    RUN                  job name, nodes, tasks, ... -- persisted under "run",
                         never mixed into a resource profile.

Persisted schema (v2)::

    {
      "schema_version": 2,
      "selected_resource": "pace",
      "resources": {
        "pace": {"hpc_username": "...", "remote_directory": "...",
                 "account": "...", "email": "...",
                 "access_mode": "connector", "auth_mode": "ssh_key"},
        "custom-univ-cluster-1a2b3c4d": {..., "custom_login_host": "...",
                                        "custom_ssh_port": 2222}
      },
      "run": {"model": "...", "job_name": "...", "nodes": 1, ...}
    }

Nothing secret is ever written: see :data:`SECRET_MARKERS` /
:func:`strip_secrets`.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Callable

from cryostack_src.resources.profiles import COMPUTE_PROFILES

#: known-resource login hosts -- a persisted host equal to one of these is a
#: stale B1 default, not a user-entered custom host.
_KNOWN_LOGIN_HOSTS = frozenset(
    p.login_host for p in COMPUTE_PROFILES.values() if p.login_host
)

STATE_SCHEMA_VERSION = 2

#: user-owned personal fields persisted per (user, resource)
PERSONAL_FIELDS = (
    "hpc_username",
    "remote_directory",
    "account",
    "email",
    "access_mode",
    "auth_mode",
)
#: extra fields only a *custom* (unknown) resource may persist
CUSTOM_RESOURCE_FIELDS = ("custom_login_host", "custom_ssh_port")

_ALLOWED_RESOURCE_KEYS = frozenset(PERSONAL_FIELDS + CUSTOM_RESOURCE_FIELDS)

#: developer/personal values that must never be canonised into a user's profile
#: even if an old persisted blob happens to contain them (see B1).
DEVELOPER_DEFAULTS = frozenset({
    "~/r-arobel3-0",
    "gts-arobel3-atlas",
    "bankyanjo@gmail.com",
})

#: substrings that mark a key as carrying a secret -- stripped from any state
SECRET_MARKERS = (
    "password", "passphrase", "secret", "token", "private_key", "privatekey",
    "pairing_code", "credential", "matlab_license", "aws_access", "aws_secret",
)

_ACCESS_MODES = {"auto", "direct", "connector"}


# ── resource identity ────────────────────────────────────────────────────
def normalize_resource_id(cluster_name: str | None) -> str:
    """A stable, safe key for a resource.

    Known resources (any alias) collapse to their canonical profile name so
    ``pace`` and ``phoenix`` share one settings entry. An unknown name is
    slugged and hashed -- a raw hostname / username string is never used
    directly as a storage key.
    """
    raw = (cluster_name or "").strip()
    key = raw.lower()
    if key in COMPUTE_PROFILES:
        return COMPUTE_PROFILES[key].name
    if not raw:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:32] or "resource"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"custom-{slug}-{digest}"


def is_known_resource(cluster_name: str | None) -> bool:
    return (cluster_name or "").strip().lower() in COMPUTE_PROFILES


# ── personal settings for one resource ──────────────────────────────────
def blank_personal() -> dict:
    return {f: "" for f in PERSONAL_FIELDS}


def read_resource_settings(state: dict, resource_id: str) -> dict:
    """Persisted personal settings for one resource, with blanks for anything
    missing. Never returns resource facts."""
    entry = {}
    if isinstance(state, dict):
        entry = (state.get("resources") or {}).get(resource_id) or {}
    out = blank_personal()
    for f in PERSONAL_FIELDS:
        v = entry.get(f)
        out[f] = "" if v is None else v
    for f in CUSTOM_RESOURCE_FIELDS:
        if f in entry and entry[f] not in (None, ""):
            out[f] = entry[f]
    return out


def _clean_personal(settings: dict, *, service_username: str = "") -> dict:
    """Keep only allowed keys; drop developer defaults / the service account
    username; coerce ``None`` to ``""``."""
    bad = set(DEVELOPER_DEFAULTS)
    if service_username.strip():
        bad.add(service_username.strip())
    out: dict = {}
    for k, v in (settings or {}).items():
        if k not in _ALLOWED_RESOURCE_KEYS:
            continue
        if isinstance(v, str) and (
            v.strip() in bad
            or any(b in v for b in DEVELOPER_DEFAULTS)
            or "arobel3" in v
        ):
            v = ""
        if k == "access_mode" and v not in _ACCESS_MODES:
            continue
        if k == "custom_ssh_port":
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        out[k] = "" if v is None else v
    return out


def write_resource_settings(
    state: dict, resource_id: str, settings: dict, *, service_username: str = ""
) -> dict:
    """Return a new state with ``settings`` merged under ``resources[resource_id]``."""
    new = copy.deepcopy(state) if isinstance(state, dict) else {}
    new.setdefault("resources", {})
    merged = dict(new["resources"].get(resource_id) or {})
    merged.update(_clean_personal(settings, service_username=service_username))
    new["resources"][resource_id] = merged
    new["schema_version"] = STATE_SCHEMA_VERSION
    return strip_secrets(new)


# ── secrets ────────────────────────────────────────────────────────────
def _is_secret_key(key: str) -> bool:
    k = str(key).lower()
    return any(marker in k for marker in SECRET_MARKERS)


def strip_secrets(value):
    """Recursively drop any mapping key that looks like a secret."""
    if isinstance(value, dict):
        return {k: strip_secrets(v) for k, v in value.items() if not _is_secret_key(k)}
    if isinstance(value, list):
        return [strip_secrets(v) for v in value]
    return value


def assert_no_secrets(state: dict) -> None:
    """Raise ``ValueError`` if any secret-looking key is present (tests)."""
    def walk(v, path=""):
        if isinstance(v, dict):
            for k, sub in v.items():
                if _is_secret_key(k):
                    raise ValueError(f"secret-looking key in workspace state: {path}{k}")
                walk(sub, f"{path}{k}.")
        elif isinstance(v, list):
            for i, sub in enumerate(v):
                walk(sub, f"{path}{i}.")

    walk(state)


# ── legacy migration ──────────────────────────────────────────────────
def migrate_legacy_state(state: dict, *, service_username: str = "") -> dict:
    """Read any historical workspace-state blob into the v2 shape.

    v2 already present -> sanitised as-is. v1 (flat ``cluster`` / ``slurm`` /
    ``access_mode``) -> only unambiguously user-owned fields are carried over;
    a known developer default is never canonised into a resource profile.
    Personal fields that v1 never stored stay blank.
    """
    if not isinstance(state, dict) or not state:
        return {"schema_version": STATE_SCHEMA_VERSION, "selected_resource": "", "resources": {}}

    if state.get("schema_version") == STATE_SCHEMA_VERSION and "resources" in state:
        out = strip_secrets(copy.deepcopy(state))
        for rid, entry in list((out.get("resources") or {}).items()):
            out["resources"][rid] = _clean_personal(entry, service_username=service_username)
        out.setdefault("selected_resource", "")
        out.setdefault("selected_resource_name", "")
        return out

    # ---- v1 (IceSheets `cluster.*` / ICESEE `remote.*`) ----
    cluster = state.get("cluster") or {}
    remote = state.get("remote") if isinstance(state.get("remote"), dict) else {}
    selected_name = (cluster.get("name") or remote.get("cluster") or "").strip()
    rid = normalize_resource_id(selected_name)

    resources: dict = {}
    if rid:
        entry: dict = {}
        am = state.get("access_mode") or remote.get("access_mode")
        if am in _ACCESS_MODES:
            entry["access_mode"] = am
        # a user-entered remote dir is worth keeping (scrubbed of dev defaults);
        # the historical default was ~/r-arobel3-0, which _clean_personal drops.
        legacy_dir = (remote.get("remote_base_dir") or "").strip()
        if legacy_dir:
            entry["remote_directory"] = legacy_dir
        # host/port are ambiguous (historically the hard-coded PACE default);
        # only keep them for an unknown resource, and only if not a known host.
        if not is_known_resource(selected_name):
            host = (cluster.get("host") or remote.get("host") or "").strip()
            if (
                host
                and host not in DEVELOPER_DEFAULTS
                and host not in _KNOWN_LOGIN_HOSTS
                and "arobel3" not in host
            ):
                entry["custom_login_host"] = host
            try:
                port = int(cluster.get("port") or remote.get("port"))
                if port and port != 22:
                    entry["custom_ssh_port"] = port
            except (TypeError, ValueError):
                pass
        resources[rid] = _clean_personal(entry, service_username=service_username)

    slurm = state.get("slurm") or {}
    run = {
        "model": state.get("model", ""),
        "backend": state.get("backend", ""),
        "execution_mode": state.get("execution_mode", ""),
        "user_mode": state.get("user_mode", ""),
        "example": state.get("example", ""),
        "example_directory": state.get("example_directory", ""),
        "run_target": state.get("run_target", ""),
        "job_name": slurm.get("job_name", ""),
        "nodes": slurm.get("nodes", ""),
        "tasks": slurm.get("tasks", ""),
        "tasks_per_node": slurm.get("tasks_per_node", ""),
        "memory": slurm.get("memory", ""),
        "wall_time_override": slurm.get("time", ""),
        "partition_override": slurm.get("partition", ""),
    }

    return strip_secrets({
        "schema_version": STATE_SCHEMA_VERSION,
        "selected_resource": rid,
        "selected_resource_name": selected_name,
        "resources": resources,
        "run": {k: v for k, v in run.items() if v not in (None, "")},
    })


# ── controller ────────────────────────────────────────────────────────
_READY = "ready"


class ResourceStateController:
    """Owns the in-memory state + the hydration lifecycle for one gateway.

    Phases: ``building`` -> ``loading`` -> ``applying`` -> ``ready``. No persist
    happens before ``ready``; applying restored fields never triggers a save of
    a partially-restored state.
    """

    def __init__(
        self,
        *,
        load_state: Callable[[], dict | None],
        save_state: Callable[[dict], None],
        read_personal: Callable[[], dict],
        apply_personal: Callable[[dict], None],
        resource_name: Callable[[], str],
        set_resource_name: Callable[[str], None] | None = None,
        service_username: str = "",
    ) -> None:
        self._load_state = load_state
        self._save_state = save_state
        self._read_personal = read_personal
        self._apply_personal = apply_personal
        self._resource_name = resource_name
        self._set_resource_name = set_resource_name
        self._svc = service_username or ""
        self._phase = "building"
        self._state: dict = {"schema_version": STATE_SCHEMA_VERSION, "selected_resource": "", "resources": {}}

    # -- lifecycle ------------------------------------------------------
    @property
    def hydrating(self) -> bool:
        return self._phase != _READY

    @property
    def state(self) -> dict:
        return copy.deepcopy(self._state)

    def hydrate(self) -> list[str]:
        """Load + migrate + apply the selected resource's personal settings.

        Returns a list of non-fatal warnings (empty on success).
        """
        self._phase = "loading"
        warnings: list[str] = []
        try:
            raw = self._load_state()
        except Exception:
            warnings.append(
                "Could not load your saved HPC settings — starting with blank "
                "personal fields. Resource defaults are unaffected."
            )
            raw = {}
        if not isinstance(raw, dict):     # "no row" -> blank, not an error
            raw = {}

        self._state = migrate_legacy_state(raw, service_username=self._svc)

        self._phase = "applying"
        selected_name = (self._state.get("selected_resource_name") or "").strip()
        if (
            selected_name
            and normalize_resource_id(selected_name) != normalize_resource_id(self._resource_name())
            and self._set_resource_name
        ):
            self._set_resource_name(selected_name)
        rid = normalize_resource_id(self._resource_name())
        self._apply_personal(read_resource_settings(self._state, rid))

        self._phase = _READY
        return warnings

    # -- events -------------------------------------------------------
    def switch_resource(self, old_name: str | None, new_name: str | None) -> None:
        """Save the outgoing resource's personal values, restore the incoming."""
        if self.hydrating:
            return
        old_id = normalize_resource_id(old_name)
        new_id = normalize_resource_id(new_name)
        if old_id == new_id:
            return
        if old_id:
            self._state = write_resource_settings(
                self._state, old_id, self._read_personal(), service_username=self._svc
            )
        self._phase = "applying"
        self._apply_personal(read_resource_settings(self._state, new_id))
        self._phase = _READY
        self._state["selected_resource"] = new_id
        self._state["selected_resource_name"] = (new_name or "").strip()
        self.persist()

    def capture(self) -> dict:
        """Fold the current personal widgets into state for the selected
        resource and return the full v2 state."""
        if self.hydrating:
            return copy.deepcopy(self._state)
        name = (self._resource_name() or "").strip()
        rid = normalize_resource_id(name)
        if rid:
            self._state = write_resource_settings(
                self._state, rid, self._read_personal(), service_username=self._svc
            )
            self._state["selected_resource"] = rid
            self._state["selected_resource_name"] = name
        return copy.deepcopy(self._state)

    def persist(self) -> None:
        if self.hydrating:
            return
        try:
            self._save_state(strip_secrets(self.capture()))
        except Exception:
            pass

    def selected_resource_settings(self) -> dict:
        return read_resource_settings(self._state, normalize_resource_id(self._resource_name()))

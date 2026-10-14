# control_center/services/settings.py

"""Allowlisted platform settings for the Control Center.

Only the settings declared in :data:`SETTINGS` exist: each has a type, a
range or choice list, a default, a description, the component that reads
it and its restart semantics. Nothing else can be read or written through
this service -- no arbitrary configuration files, no paths, no commands.

Every setting is consumed today as an environment variable by the component
named in ``reader``. The Control Center therefore makes a stored value
effective by exporting it into the gateway's environment:

* at gateway start (:meth:`SettingsService.apply_at_startup`, called while the
  application is assembled -- before the Voila services and index workers
  are spawned, so they inherit it);
* immediately on change for settings whose reader re-reads the variable on
  every use (``restart == "none"``).

Precedence (highest first), decided explicitly:

1. **environment** -- a variable already set in the gateway's environment
   when it started (systemd unit, ``services.sh``, shell). Deployment
   configuration is the operator's explicit pin; the UI never overrides it.
   A value stored while the variable is pinned is kept but marked shadowed.
2. **stored** -- the value saved here by a maintainer (audited).
3. **default** -- the reader's built-in default.

Secrets are never settings: a variable name that looks like a credential
cannot be registered (checked at import).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from ..ops_store import OpsStore


#: roles that may change settings; developers see them read-only
SETTINGS_WRITE_ROLES = frozenset({"maintainer", "admin", "owner"})

_SECRET_HINTS = (
    "secret", "token", "password", "passwd", "credential", "session",
    "access_key", "accesskey", "api_key", "apikey", "private", "cookie",
)

MAX_REASON = 500


class SettingsError(ValueError):
    """A settings request was rejected (unknown key, invalid value...)."""


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    label: str
    group: str
    env: str
    kind: str                       # "int" | "bool" | "choice"
    default: object
    description: str
    reader: str
    restart: str                    # "none" | "gateway"
    minimum: int | None = None
    maximum: int | None = None
    unit: str = ""
    choices: tuple[str, ...] = field(default_factory=tuple)
    restart_note: str = ""

    def parse(self, raw) -> object:
        """Validate a submitted value (form text or JSON) server-side."""
        if self.kind == "bool":
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off"):
                return False
            raise SettingsError(f"{self.label}: expected true or false.")
        if self.kind == "choice":
            text = str(raw).strip().lower()
            if text not in self.choices:
                raise SettingsError(
                    f"{self.label}: must be one of {', '.join(self.choices)}."
                )
            return text
        if isinstance(raw, bool):
            raise SettingsError(f"{self.label}: expected a whole number.")
        try:
            text = str(raw).strip()
            if not re.fullmatch(r"[+-]?\d{1,12}", text):
                raise ValueError
            value = int(text)
        except (TypeError, ValueError):
            raise SettingsError(f"{self.label}: expected a whole number.")
        if self.minimum is not None and value < self.minimum:
            raise SettingsError(
                f"{self.label}: must be at least {self.minimum}{self.unit and ' ' + self.unit}."
            )
        if self.maximum is not None and value > self.maximum:
            raise SettingsError(
                f"{self.label}: must be at most {self.maximum}{self.unit and ' ' + self.unit}."
            )
        return value

    def to_env(self, value) -> str:
        if self.kind == "bool":
            return "1" if value else "0"
        return str(value)

    def from_env(self, text: str):
        """Interpret an environment value the way the reader does (an
        unparsable value is shown as such, not silently replaced)."""
        try:
            return self.parse(text)
        except SettingsError:
            return text


SETTINGS: tuple[SettingDefinition, ...] = (
    SettingDefinition(
        key="frozen_legacies.ursa_concurrency",
        label="URSA concurrent jobs",
        group="Frozen Legacies workers",
        env="CRYOSTACK_FROZEN_LEGACIES_URSA_CONCURRENCY",
        kind="int", default=1, minimum=1, maximum=8, unit="jobs",
        description="Automatic-picking (URSA) jobs that may run at the same "
                    "time on this server. Each job is a separate process.",
        reader="Frozen Legacies automatic picking (gateway)",
        restart="gateway",
        restart_note="The job limiter is created on the first job after start.",
    ),
    SettingDefinition(
        key="frozen_legacies.ursa_timeout_s",
        label="URSA job timeout",
        group="Frozen Legacies workers",
        env="CRYOSTACK_FROZEN_LEGACIES_URSA_TIMEOUT",
        kind="int", default=3600, minimum=60, maximum=86400, unit="s",
        description="An automatic-picking job running longer than this is "
                    "stopped and recorded as failed.",
        reader="Frozen Legacies automatic picking (gateway)",
        restart="none",
        restart_note="Read when each job starts; running jobs keep their limit.",
    ),
    SettingDefinition(
        key="frozen_legacies.working_cache_mb",
        label="Working cache limit",
        group="Caches",
        env="CRYOSTACK_FROZEN_LEGACIES_WORKING_CACHE_MB",
        kind="int", default=20480, minimum=256, maximum=1048576, unit="MB",
        description="Size bound of local working copies of remote radar files "
                    "(least recently used copies are evicted).",
        reader="Frozen Legacies working cache (gateway)",
        restart="gateway",
        restart_note="The cache is created on first use after start.",
    ),
    SettingDefinition(
        key="frozen_legacies.radar_cache_mb",
        label="Decoded radar image cache",
        group="Caches",
        env="CRYOSTACK_FROZEN_LEGACIES_RADAR_CACHE_MB",
        kind="int", default=768, minimum=64, maximum=16384, unit="MB",
        description="Memory budget for decoded radar images kept for the "
                    "picker views.",
        reader="Frozen Legacies radar rendering (gateway)",
        restart="gateway",
    ),
    SettingDefinition(
        key="frozen_legacies.radar_decodes",
        label="Concurrent radar decodes",
        group="Frozen Legacies workers",
        env="CRYOSTACK_FROZEN_LEGACIES_RADAR_DECODES",
        kind="int", default=1, minimum=1, maximum=8, unit="decodes",
        description="Radar files decoded at the same time. A decode briefly "
                    "holds about twice the image in memory.",
        reader="Frozen Legacies radar rendering (gateway)",
        restart="gateway",
    ),
    SettingDefinition(
        key="cloud.poll_seconds",
        label="Cloud job status poll interval",
        group="Execution",
        env="CRYOSTACK_CLOUD_POLL_SECONDS",
        kind="int", default=20, minimum=5, maximum=600, unit="s",
        description="How often CryoLauncher polls AWS Batch for the status of "
                    "a running cloud job.",
        reader="CryoLauncher (Voila application)",
        restart="gateway",
        restart_note="The Voila services inherit the environment when the "
                     "gateway starts them.",
    ),
    SettingDefinition(
        key="gateway.app_start_mode",
        label="Application start mode",
        group="Operational defaults",
        env="CRYOSTACK_APP_START_MODE",
        kind="choice", default="background", choices=("background", "lazy"),
        description="background: start CryoLauncher and ICESEE when the "
                    "gateway starts; lazy: start each on its first request.",
        reader="Gateway (bin/icesee_app.py)",
        restart="gateway",
    ),
    SettingDefinition(
        key="platform.perf_instrumentation",
        label="Performance instrumentation",
        group="Operational defaults",
        env="CRYOSTACK_PERF",
        kind="bool", default=False,
        description="Log timing spans (static labels only, no user data) to "
                    "the service log.",
        reader="Gateway and Voila applications (cryostack_src.perf)",
        restart="gateway",
        restart_note="The gateway re-reads it on every span; the Voila "
                     "applications see it after a restart.",
    ),
)

for _definition in SETTINGS:
    _lowered = _definition.env.lower()
    assert not any(hint in _lowered for hint in _SECRET_HINTS), _definition.env

SETTINGS_BY_KEY = {definition.key: definition for definition in SETTINGS}

#: values this module exported into the environment (so a later service
#: instance does not mistake them for operator pins)
_EXPORTED: dict[str, str] = {}


class SettingsService:

    def __init__(self, store: OpsStore, *, environ=None) -> None:
        self.store = store
        self.environ = os.environ if environ is None else environ
        # operator pins: what the environment held before we exported anything
        self.pinned: dict[str, str] = {}
        for definition in SETTINGS:
            value = self.environ.get(definition.env)
            if value is None or value.strip() == "":
                continue
            if _EXPORTED.get(definition.env) == value:
                continue
            self.pinned[definition.env] = value
        # what the running processes were started with (restart semantics)
        self.applied: dict[str, object] = {}

    # ── effective values ────────────────────────────────────────────
    def apply_at_startup(self) -> None:
        stored = self.store.stored_settings()
        for definition in SETTINGS:
            if definition.env in self.pinned:
                self.applied[definition.key] = definition.from_env(
                    self.pinned[definition.env]
                )
                continue
            if definition.key in stored:
                value = stored[definition.key]["value"]
                self._export(definition, value)
                self.applied[definition.key] = value
            else:
                self._unexport(definition)
                self.applied[definition.key] = definition.default

    def _export(self, definition: SettingDefinition, value) -> None:
        text = definition.to_env(value)
        self.environ[definition.env] = text
        _EXPORTED[definition.env] = text

    def _unexport(self, definition: SettingDefinition) -> None:
        if definition.env in _EXPORTED and definition.env not in self.pinned:
            self.environ.pop(definition.env, None)
            _EXPORTED.pop(definition.env, None)

    def describe(self) -> list[dict]:
        stored = self.store.stored_settings()
        out = []
        for definition in SETTINGS:
            entry = stored.get(definition.key)
            stored_value = entry["value"] if entry else None
            if definition.env in self.pinned:
                source = "environment"
                configured = definition.from_env(self.pinned[definition.env])
            elif entry is not None:
                source = "stored"
                configured = stored_value
            else:
                source = "default"
                configured = definition.default
            running = configured
            pending = False
            if definition.restart != "none" and definition.key in self.applied:
                running = self.applied[definition.key]
                pending = running != configured
            out.append({
                "key": definition.key,
                "label": definition.label,
                "group": definition.group,
                "env": definition.env,
                "type": definition.kind,
                "minimum": definition.minimum,
                "maximum": definition.maximum,
                "unit": definition.unit,
                "choices": list(definition.choices),
                "default": definition.default,
                "description": definition.description,
                "reader": definition.reader,
                "restart": definition.restart,
                "restart_required": definition.restart != "none",
                "restart_note": definition.restart_note,
                "source": source,
                "configured_value": configured,
                "running_value": running,
                "pending_restart": pending,
                "stored_value": stored_value,
                "shadowed": source == "environment" and entry is not None,
                "updated_at": entry["updated_at"] if entry else None,
            })
        return out

    def audit(self, *, limit: int = 50) -> list[dict]:
        items = self.store.audit(limit=limit)
        for item in items:
            definition = SETTINGS_BY_KEY.get(item["key"])
            item["label"] = definition.label if definition else item["key"]
        return items

    # ── changes ─────────────────────────────────────────────────────
    @staticmethod
    def _reason(reason) -> str:
        text = " ".join(str(reason or "").split())
        if not text:
            raise SettingsError("A reason is required for every settings change.")
        if len(text) > MAX_REASON:
            raise SettingsError(f"The reason is limited to {MAX_REASON} characters.")
        return text

    @staticmethod
    def _definition(key) -> SettingDefinition:
        definition = SETTINGS_BY_KEY.get(str(key or ""))
        if definition is None:
            raise SettingsError("Unknown setting.")
        return definition

    def _after_change(self, definition: SettingDefinition, value) -> None:
        if definition.env in self.pinned:
            return
        if definition.restart == "none":
            if value is None:
                self._unexport(definition)
            else:
                self._export(definition, value)

    def change(self, *, key, value, actor_id: str, actor_label: str | None,
               reason) -> dict:
        definition = self._definition(key)
        parsed = definition.parse(value)
        reason = self._reason(reason)
        audit_id = self.store.change_setting(
            key=definition.key, new_value=parsed, actor_id=actor_id,
            actor_label=actor_label, reason=reason, action="set",
        )
        self._after_change(definition, parsed)
        return {"audit_id": audit_id, "key": definition.key, "value": parsed}

    def reset(self, *, key, actor_id: str, actor_label: str | None, reason) -> dict:
        """Remove the stored value: the default (or the environment) applies."""
        definition = self._definition(key)
        reason = self._reason(reason)
        audit_id = self.store.change_setting(
            key=definition.key, new_value=None, actor_id=actor_id,
            actor_label=actor_label, reason=reason, action="reset",
        )
        self._after_change(definition, None)
        return {"audit_id": audit_id, "key": definition.key, "value": None}

    def rollback(self, *, audit_id, actor_id: str, actor_label: str | None,
                 reason=None) -> dict:
        """Restore the value a setting had before audit entry ``audit_id``."""
        try:
            entry = self.store.audit_entry(int(audit_id))
        except (TypeError, ValueError):
            entry = None
        if entry is None:
            raise SettingsError("Unknown audit entry.")
        definition = self._definition(entry["key"])
        previous = entry["old_value"]
        if previous is not None:
            previous = definition.parse(previous)      # still within today's range
        text = " ".join(str(reason or "").split())
        reason = self._reason(text or f"Rollback of change #{entry['id']}")
        new_id = self.store.change_setting(
            key=definition.key, new_value=previous, actor_id=actor_id,
            actor_label=actor_label, reason=reason, action="rollback",
            rollback_of=entry["id"],
        )
        self._after_change(definition, previous)
        return {"audit_id": new_id, "key": definition.key, "value": previous}

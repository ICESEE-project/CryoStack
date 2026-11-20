"""Kernel-side client of the hosted pilot (imported by the CryoLauncher UI).

Standard library only at import time; never imports Control Center or an AWS
SDK. The kernel holds no hosted AWS credential: it proves its user to the gateway
with the grant the proxy placed in its environment, and the gateway does every
AWS operation. ``HostedBridge`` has the same call shape as ``CloudBridge`` so
the run controller can drive either.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from icesee_auth.kernel_access import (
    DEFAULT_GATEWAY_URL,
    GATEWAY_URL_ENV,
    KERNEL_PILOT_PATH,
    PILOT_GRANT_ENV,
    PILOT_GRANT_HEADER,
)

ROUTE_HOSTED = "hosted"
ROUTE_BYO = "byo"
ROUTE_NONE = "none"

USER_ID_ENV = "HTTP_X_CRYOSTACK_USER_ID"
_MAX_RESPONSE = 1 << 22
#: provisioning, upload and result transfer happen inside these calls
LONG_TIMEOUT = 900.0


@dataclass(frozen=True)
class PilotSummary:
    enabled: bool = False
    eligible: bool = False
    credit_cents: int = 0
    reserved_cents: int = 0
    charged_cents: int = 0
    available_cents: int = 0
    hold_cents: int = 0
    expires_at: float = 0
    expired: bool = False
    pool_name: str = ""
    region: str = ""
    models: tuple = ()
    limits: dict = field(default_factory=dict)
    message: str = ""
    license_configured: bool = False
    #: Gateway-reported readiness of the configured hosted license path,
    #: including its required institution Connector when applicable.
    license_available: bool = False
    license_requires_connector: bool = False
    connector_connected: bool = False
    holds: dict = field(default_factory=dict)

    @classmethod
    def unavailable(cls, message: str = "") -> "PilotSummary":
        return cls(message=str(message or ""))

    @property
    def can_run(self) -> bool:
        return bool(self.enabled and self.eligible and not self.expired
                    and self.available_cents >= self.hold_cents > 0)

    @classmethod
    def from_payload(cls, payload) -> "PilotSummary":
        if not isinstance(payload, dict):
            return cls.unavailable("Hosted pilot information is unavailable.")

        def number(name):
            value = payload.get(name)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0

        models = payload.get("models")
        limits = payload.get("limits")
        license_ = payload.get("matlab_license")
        license_ = license_ if isinstance(license_, dict) else {}
        return cls(
            enabled=payload.get("enabled") is True, eligible=payload.get("eligible") is True,
            credit_cents=int(number("credit_cents")), reserved_cents=int(number("reserved_cents")),
            charged_cents=int(number("charged_cents")), available_cents=int(number("available_cents")),
            hold_cents=int(number("hold_cents")), expires_at=number("expires_at"),
            expired=payload.get("expired") is True, pool_name=str(payload.get("pool_name") or ""),
            region=str(payload.get("region") or ""),
            models=tuple(str(m) for m in models) if isinstance(models, (list, tuple)) else (),
            limits=dict(limits) if isinstance(limits, dict) else {},
            license_configured=license_.get("configured") is True,
            license_available=license_.get("available") is True,
            license_requires_connector=license_.get("requires_connector") is True,
            connector_connected=license_.get("connector_connected") is True,
            holds={str(k): int(v) for k, v in (payload.get("holds") or {}).items()
                   if isinstance(v, int) and not isinstance(v, bool)}
            if isinstance(payload.get("holds"), dict) else {})


class _GatewayError(RuntimeError):
    pass


def _request(path: str, payload: dict | None, *, user_id: str | None, timeout: float):
    """One call to the gateway. Raises ``RuntimeError`` with a safe message."""
    grant = (os.environ.get(PILOT_GRANT_ENV) or "").strip()
    user = (user_id or os.environ.get(USER_ID_ENV) or "").strip()
    if not grant or not user:
        raise _GatewayError("Hosted pilot runs are not available in this session.")
    base = (os.environ.get(GATEWAY_URL_ENV) or DEFAULT_GATEWAY_URL).rstrip("/")
    headers = {"X-CryoStack-User-Id": user, PILOT_GRANT_HEADER: grant}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{base}{KERNEL_PILOT_PATH}{path}", data=data, headers=headers,
                                     method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL
            body = response.read(_MAX_RESPONSE)
    except urllib.error.HTTPError as error:
        message = ""
        try:
            detail = json.loads(error.read(65536).decode("utf-8"))
            message = str(detail.get("error") or "") if isinstance(detail, dict) else ""
        except Exception:  # noqa: BLE001
            pass
        raise _GatewayError(message or f"The hosted run service refused the request ({error.code}).") from None
    except Exception:  # noqa: BLE001 - transport: no detail worth showing
        raise _GatewayError("The hosted run service could not be reached.") from None
    try:
        result = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise _GatewayError("The hosted run service returned an unreadable response.") from None
    if not isinstance(result, dict):
        raise _GatewayError("The hosted run service returned an unreadable response.")
    return result


def pilot_summary(user_id: str | None = None, *, timeout: float = 5.0) -> PilotSummary:
    """The user's pilot credit. Never raises; any problem is ``unavailable``."""
    try:
        if not (os.environ.get(PILOT_GRANT_ENV) or "").strip():
            return PilotSummary.unavailable()
        return PilotSummary.from_payload(_request("/summary", None, user_id=user_id, timeout=timeout))
    except Exception as error:  # noqa: BLE001
        return PilotSummary.unavailable(str(error) if isinstance(error, _GatewayError) else
                                        "Hosted pilot information is unavailable.")


def select_route(*, has_byo_connection: bool, summary: PilotSummary, preference: str | None,
                 model: str) -> tuple[str, str]:
    """Which account a run uses, and a sentence explaining it."""
    model = (model or "").strip().lower()
    # A payer choice is authorization, not a hint. Never change it after a
    # balance, eligibility, service or connection failure.
    if preference == ROUTE_BYO:
        if has_byo_connection:
            return ROUTE_BYO, "Using your connected AWS account."
        return ROUTE_NONE, "Connect an AWS account to use your own AWS account."
    if preference not in (None, "", ROUTE_HOSTED):
        return ROUTE_NONE, "Choose how to pay for this run."
    if not summary.enabled or not summary.eligible:
        if preference != ROUTE_HOSTED and has_byo_connection:
            return ROUTE_BYO, "Using your connected AWS account."
        return ROUTE_NONE, ("Pilot credit is unavailable. Choose your own AWS account "
                            "explicitly to pay for a run there.")
    if summary.expired:
        return ROUTE_NONE, ("The pilot has ended. Choose your own AWS account "
                            "explicitly to keep running in the cloud.")
    if model not in summary.models:
        return ROUTE_NONE, (f"{model or 'This model'} is not available on pilot credit. "
                            "Choose your own AWS account explicitly to run it there.")
    hold = summary.holds.get(model, summary.hold_cents)
    if hold <= 0 or summary.available_cents < hold:
        return ROUTE_NONE, ("Your pilot credit is used up or held by a run in progress. "
                            "Choose your own AWS account explicitly to pay for a run there.")
    if model == "issm" and not summary.license_configured:
        # Keep the hosted form reachable for invitees without an AWS account.
        return ROUTE_HOSTED, "Add your MATLAB license to run ISSM on pilot credit."
    return ROUTE_HOSTED, "Using your CryoStack pilot credit."


def set_matlab_license(value: str, *, user_id: str | None = None, timeout: float = 120.0) -> dict:
    """Store the user's MATLAB license for hosted ISSM. The value goes to the
    gateway once and is not kept here; errors never contain it."""
    message = None
    try:
        _request("/license", {"value": value}, user_id=user_id, timeout=timeout)
    except _GatewayError as error:
        message = str(error).replace(str(value), "[license]") if value else str(error)
    if message is not None:          # raised outside the handler: no chained exception keeps the value
        raise RuntimeError(message)
    return {"configured": True}


def clear_matlab_license(*, user_id: str | None = None, timeout: float = 30.0) -> dict:
    try:
        _request("/license/clear", {}, user_id=user_id, timeout=timeout)
    except _GatewayError as error:
        raise RuntimeError(str(error)) from None
    return {"configured": False}


class HostedExecution:
    """Credential context of a hosted run: there is none in the kernel."""

    mode = "hosted"
    is_byo = False
    is_hosted = True
    credentials = None
    profile = None
    account_id = ""

    def __init__(self, region: str = "") -> None:
        self.region = region


class HostedBridge:
    """``CloudBridge``-shaped operations carried out by the gateway."""

    provider = "aws"
    credentials = None
    profile = None

    def __init__(self, user_id: str | None = None, *, region: str = "", timeout: float = 30.0) -> None:
        self.user_id = user_id
        self.region = region
        self.timeout = timeout

    def _call(self, path: str, payload: dict, *, timeout: float | None = None) -> dict:
        try:
            return _request(path, payload, user_id=self.user_id, timeout=timeout or self.timeout)
        except _GatewayError as error:
            raise RuntimeError(str(error)) from None

    def submit(self, **kwargs):
        from cryostack_src.execution.backend import ExecutionResult

        source = kwargs.get("staged_source") or kwargs.get("source")
        source = getattr(source, "path", source)
        model = str(kwargs.get("model") or "").strip().lower()
        payload = {
            "staged_source": str(source or ""),
            "model": model,
            "run_target": str(kwargs.get("run_target") or ""),
            "request_key": str(kwargs.get("request_key") or uuid.uuid4().hex),
        }
        if kwargs.get("seconds") is not None:
            payload["seconds"] = int(kwargs["seconds"])
        result = self._call("/submit", payload, timeout=LONG_TIMEOUT)
        # The run handle is the gateway's reservation id: every later call
        # (status, logs, stop, results) names the reservation, never an AWS id.
        handle = str(result.get("reservation_id") or "")
        if not handle:
            raise RuntimeError("The hosted run service did not return a reservation id.")
        self.region = str(result.get("region") or self.region)
        return ExecutionResult(
            success=True, backend="cloud", job_id=handle or None,
            working_directory=None, output_directory=None, log_path=None,
            metadata={"provider": "aws", "route": ROUTE_HOSTED, "model": model,
                      "run_target": payload["run_target"], "region": result.get("region"),
                      "reservation_id": handle or None, "aws_job_id": result.get("job_id"),
                      "hold_cents": result.get("hold_cents")},
            messages=[f"submitted hosted pilot run {handle}",
                      f"pilot credit on hold: {int(result.get('hold_cents') or 0)} cents"])

    def status(self, *, job_id: str, **_ignored):
        from cryostack_src.execution.backend import ExecutionStatus

        result = self._call("/status", {"reservation_id": str(job_id)})
        return ExecutionStatus(
            state=str(result.get("state") or "unknown"), raw_state=result.get("raw_state"),
            reason=str(result.get("status_reason") or ""), exit_code=None,
            metadata={"provider": "aws", "route": ROUTE_HOSTED, "region": self.region,
                      "aws_job_id": result.get("job_id"),
                      "results": result.get("results") or "",
                      "settled": result.get("charged_cents") is not None,
                      "charged_cents": result.get("charged_cents"),
                      "hold_cents": result.get("hold_cents")})

    def logs(self, *, job_id: str, **_ignored) -> str:
        return str(self._call("/logs", {"reservation_id": str(job_id)}).get("text") or "")

    def terminate(self, *, job_id: str, **_ignored):
        return self._call("/terminate", {"reservation_id": str(job_id)})

    def results(self, *, s3_uri=None, job_id: str, destination, **_ignored) -> Path:
        self._call("/results", {"reservation_id": str(job_id), "destination": str(destination)},
                   timeout=LONG_TIMEOUT)
        return Path(destination)

    def set_matlab_license(self, value: str) -> dict:
        return set_matlab_license(value, user_id=self.user_id)

    def clear_matlab_license(self) -> dict:
        return clear_matlab_license(user_id=self.user_id)


__all__ = ["ROUTE_HOSTED", "ROUTE_BYO", "ROUTE_NONE", "PilotSummary", "pilot_summary",
           "select_route", "HostedExecution", "HostedBridge", "set_matlab_license",
           "clear_matlab_license"]

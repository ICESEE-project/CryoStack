"""Hosted pilot presentation and gateway transport, disabled unless explicitly enabled.

No AWS SDK or credential resolution lives here. A persisted reservation is the
only handle used for a hosted run, including after the payer selection changes.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from types import SimpleNamespace

FEATURE_ENV = "CRYOSTACK_PILOT_UI_ENABLED"
HOSTED = "hosted"
BYO = "byo"


def enabled() -> bool:
    return os.environ.get(FEATURE_ENV, "").strip() == "1"


def _money(cents) -> str:
    return f"${max(0, int(cents)) / 100:.2f}"


def _limit(summary, *names) -> int:
    for name in names:
        value = summary.limits.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            return int(value)
    return 0


def hosted_digest(*, summary, model, example, run_target, scientific_overrides=None,
                  image_digest="", source_digest="") -> str:
    # Balance and license readiness are rechecked at submit by the gateway;
    # they are intentionally not configuration drift. The funding source,
    # model, resource limits, expiry and scientific inputs are immutable here.
    payload = {"route": HOSTED, "pool": summary.pool_name, "region": summary.region,
               "expires_at": summary.expires_at, "limits": summary.limits,
               "hold_cents": summary.holds.get(model, summary.hold_cents),
               "model": model, "example": example, "run_target": run_target,
               "scientific_overrides": scientific_overrides or {}, "image_digest": image_digest,
               "source_digest": source_digest}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def source_fingerprint(manager, example_path, limits):
    """Bind a hosted review to saved script and referenced dataset bytes.

    The same bounded input limits as the gateway keep this local check finite.
    Ownership of datasets is resolved by the existing workspace manager. No
    symlink or special file is followed while taking the source snapshot.
    """
    import stat
    from pathlib import Path
    root = Path(example_path).expanduser()
    byte_limit = int(limits.get("max_input_mib", 64)) * 1024 * 1024
    file_limit = int(limits.get("max_input_files", 256))
    if byte_limit <= 0 or file_limit <= 0:
        raise ValueError("The pilot input limits are unavailable.")
    paths = []
    def collect(path, label):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            for child in sorted(path.iterdir()):
                collect(child, label + "/" + child.name)
        elif stat.S_ISREG(mode):
            paths.append((label, path))
            if len(paths) > file_limit:
                raise ValueError("This pilot run has too many input files.")
        else:
            raise ValueError("Pilot inputs must be regular files and directories.")
    collect(root, "source")
    for ref in manager.example_dataset_references(root):
        name = ref.get("name", "")
        paths.append(("dataset/" + str(ref.get("as") or name), manager._resolve_dataset(name)))
    digest = hashlib.sha256()
    total = 0
    read_total = 0
    for label, path in paths:
        if len(paths) > file_limit:
            raise ValueError("This pilot run has too many input files.")
        total += path.stat().st_size
        if total > byte_limit:
            raise ValueError("This pilot run exceeds the input size limit.")
        digest.update(label.encode("utf-8") + b"\0")
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                read_total += len(block)
                if read_total > byte_limit:
                    raise ValueError("This pilot run exceeds the input size limit.")
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass
class HostedReview:
    model: str
    example: str
    run_target: str
    region: str
    vcpu: float
    memory_gib: float
    time_limit_minutes: float
    hold_cents: int
    available_cents: int
    blocked_reasons: list
    digest: str
    config: object
    cost: object
    image_key: str = ""
    image_label: str = ""
    image_reference: str = ""
    image_digest: str = ""
    route: str = HOSTED
    account_id: str = ""
    expected_runtime_minutes: float = 0
    issm_runtime_ready: bool | None = None

    @property
    def can_launch(self):
        return not self.blocked_reasons

    @property
    def infrastructure(self):
        # Used only to keep the common Review button visible. Hosted Review
        # renders allocation/profile facts, never unperformed AWS probes.
        return SimpleNamespace(all_ready=True)

    def resource_summary(self):
        return f"{self.vcpu:g} vCPU · {self.memory_gib:g} GiB"

    def cost_summary(self):
        return f"up to {_money(self.hold_cents)} held from pilot credit"


def build_hosted_review(*, summary, model, example, run_target, scientific_overrides=None,
                        image=None, source_digest=""):
    from cryostack_src.cloud.estimate.models import CloudCostEstimate
    from cryostack_src.cloud.pilot.client import ROUTE_HOSTED, select_route
    route, reason = select_route(has_byo_connection=False, summary=summary,
                                 preference=ROUTE_HOSTED, model=model)
    problems = [] if route == HOSTED else [reason]
    vcpu = _limit(summary, "vcpu")
    memory = _limit(summary, "memory_mib")
    seconds = _limit(summary, "max_seconds", "max_model_seconds")
    if not (summary.region and vcpu and memory and seconds):
        problems.append("The pilot resource profile is unavailable. Refresh pilot credit before launching.")
    runtime_ready = None
    if model == "issm":
        runtime_ready = bool(summary.license_configured and summary.license_available)
        if not summary.license_configured:
            problems.append("Configure your MATLAB license for this pilot account.")
        elif getattr(summary, "license_requires_connector", False) and not getattr(summary, "connector_connected", False):
            problems.append("Connect your institution's Connector before launching ISSM.")
        elif not summary.license_available:
            problems.append("The MATLAB license service is unavailable for this hosted run.")
    image_digest = getattr(image, "digest", "") or ""
    return HostedReview(
        model=model, example=example, run_target=run_target, region=summary.region,
        vcpu=vcpu, memory_gib=memory / 1024, time_limit_minutes=seconds / 60,
        hold_cents=summary.holds.get(model, summary.hold_cents), available_cents=summary.available_cents,
        blocked_reasons=problems,
        digest=hosted_digest(summary=summary, model=model, example=example, run_target=run_target,
                             scientific_overrides=scientific_overrides, image_digest=image_digest, source_digest=source_digest),
        config=SimpleNamespace(region=summary.region, time_limit_minutes=seconds / 60),
        cost=CloudCostEstimate(region=summary.region),
        image_key=getattr(image, "key", "") or "", image_label=getattr(image, "label", "") or "",
        image_reference=getattr(image, "reference", "") or "", image_digest=image_digest,
        issm_runtime_ready=runtime_ready,
    )


def render_hosted_estimate(widgets, review):
    """A hosted credit ceiling and model timeout are bounds, not estimates."""
    widgets.run_estimate_section.layout.display = "flex"
    widgets.run_estimate_line.value = (
        "<div style='font-size:11px;color:#66758d;line-height:1.7;'>"
        f"Fixed pilot resources&nbsp;&nbsp;{escape(review.resource_summary())}<br>"
        f"Model time limit&nbsp;&nbsp;{review.time_limit_minutes:g} min<br>"
        f"Maximum credit hold&nbsp;&nbsp;<b>{_money(review.hold_cents)}</b>"
        "</div>")


def render_hosted_review(widgets, review):
    r = review
    widgets._review_route = HOSTED
    rows = [("Pay with", "CryoStack pilot credit"), ("Model", r.model.upper()),
            ("Example", r.example), ("Run target", r.run_target), ("Region", r.region),
            ("Resources", r.resource_summary()), ("Model time limit", f"{r.time_limit_minutes:g} min"),
            ("Available credit", _money(r.available_cents)), ("Maximum credit hold", _money(r.hold_cents))]
    if r.image_reference:
        rows.extend([("Tested image", r.image_reference), ("Image digest", r.image_digest)])
    if r.issm_runtime_ready is not None:
        rows.append(("ISSM runtime", "Ready" if r.issm_runtime_ready else "Needs MATLAB license access"))
    table = "".join(f"<tr><td style='padding:3px 12px 3px 0'>{escape(k)}</td><td>{escape(str(v))}</td></tr>" for k,v in rows)
    blocked = ""
    if r.blocked_reasons:
        blocked = "<p><b>Launch blocked:</b></p><ul>" + "".join(f"<li>{escape(str(x))}</li>" for x in r.blocked_reasons) + "</ul>"
    widgets.review_body.value = f"<table style='font-size:12px'>{table}</table>{blocked}"
    widgets.review_notice.value = (
        "<div style='font-size:11px;padding:8px;background:#f6f8fb'>"
        "This run uses pilot credit. The maximum hold is reserved before submission; "
        "unused credit is released after settlement. The gateway checks the allocation, "
        "license access and hosted resources at launch. Your own AWS account will not "
        "be charged by this selection.</div>")
    widgets.launch_button.disabled = not r.can_launch


def sync_hosted_results(manager, bridge, *, run_job_id=None, **_ignored):
    run = manager._run_by_job_id(str(run_job_id)) if run_job_id else manager.selected_run()
    if run is None or run.execution_mode != "cloud" or (run.metadata or {}).get("route") != HOSTED:
        raise RuntimeError("Select the hosted run whose results you want to retrieve.")
    reservation = str((run.metadata or {}).get("reservation_id") or "")
    if not reservation or reservation != str(run.jobid):
        raise RuntimeError("The hosted run is missing its reservation handle.")
    # Existing owner checks and verified storage guard run before the gateway
    # receives this destination. The gateway independently validates ownership.
    destination = manager.local_run_cache_dir(run) / "cloud_outputs"
    manager.invalidate_result_package_cache(run.id)
    return bridge.results(job_id=reservation, destination=destination)


class HostedPilotPanel:
    """Payer and credit controls; all network work runs off the UI event loop."""
    def __init__(self, *, user_id, widgets, model, connection_summary, on_change=lambda: None,
                 connector_box=None, connector_refresh=lambda: None, on_open_compute=None):
        import ipywidgets as W
        from cryostack_src.cloud.pilot.client import PilotSummary
        self.user_id, self.widgets = user_id, widgets
        self.model, self.connection_summary, self.on_change = model, connection_summary, on_change
        self.connector_box, self.connector_refresh = connector_box, connector_refresh
        self.summary = PilotSummary.unavailable()
        # An explicit selection is required, even if only BYO is available.
        # Losing a Hosted allocation never selects a different payer.
        self._preference = None
        self.byo_button = W.Button(
            description="Bring your own AWS (BYO)", icon="cloud",
            layout=W.Layout(width="225px", max_width="100%"),
        )
        self.hosted_button = W.Button(
            description="Hosted Access", icon="cloud",
            layout=W.Layout(width="160px", max_width="100%", display="none"),
        )
        self.choices = W.VBox([
            W.HTML("<b>Cloud access</b><br>Choose how to run in the cloud."),
            W.HBox([self.byo_button, self.hosted_button], layout=W.Layout(flex_flow="row wrap", gap="8px")),
        ], layout=W.Layout(gap="8px"))
        self.back_button = W.Button(
            description="Back to cloud access", icon="arrow-left",
            layout=W.Layout(width="195px", max_width="100%"),
        )
        self.credit = W.HTML()
        self.reason = W.HTML()
        self.refresh_button = W.Button(description="Refresh pilot credit", icon="refresh")
        self.open_compute_button = W.Button(
            description="Open Advanced Compute", icon="sliders",
            disabled=on_open_compute is None,
            layout=W.Layout(width="235px", max_width="100%", display="none"),
        )
        def open_compute(_):
            if self._preference == HOSTED and on_open_compute is not None:
                on_open_compute()
        self.open_compute_button.on_click(open_compute)
        self.license_value = W.Password(description="MATLAB license:", layout=W.Layout(width="100%"),
                                        style={"description_width": "120px"})
        self.license_button = W.Button(description="Configure pilot license", icon="lock")
        self.license_status = W.HTML()
        self.license_box = W.VBox([self.license_value, self.license_button, self.license_status])
        self.hosted_details = W.VBox([self.credit, self.reason, self.open_compute_button,
                                     self.refresh_button, self.license_box],
                                     layout=W.Layout(gap="6px", width="100%"))
        self.container = W.VBox([self.choices, self.back_button, self.hosted_details],
                                layout=W.Layout(gap="8px", width="100%"))
        self.byo_button.on_click(lambda _: self._select(BYO))
        self.hosted_button.on_click(lambda _: self._select(HOSTED))
        self.back_button.on_click(self.back)
        self.refresh_button.on_click(self.refresh)
        self.license_button.on_click(self.configure_license)
        self.render()

    @property
    def has_hosted_access(self):
        s = self.summary
        return s.enabled and s.eligible and s.credit_cents > 0 and not s.expired

    def route(self, *, fresh=False):
        from cryostack_src.cloud.pilot.client import ROUTE_NONE, pilot_summary, select_route
        if fresh:
            self.summary = pilot_summary(self.user_id)
            self.render()
        if self._preference is None:
            return ROUTE_NONE, "Choose a cloud access option."
        if self._preference == HOSTED and not self.has_hosted_access:
            return ROUTE_NONE, "Hosted Access is unavailable for your account."
        try:
            connected = self.connection_summary().get("status") == "connected"
        except Exception:
            connected = False
        return select_route(has_byo_connection=connected, summary=self.summary,
                            preference=self._preference, model=self.model())

    def _select(self, route):
        if route == HOSTED and not self.has_hosted_access:
            self.render()
            return
        self._preference = route
        self.render()
        self.on_change()

    def back(self, _=None):
        self._select(None)
        self.refresh()

    def render(self):
        s = self.summary
        hosted_view = self._preference == HOSTED
        choosing = self._preference is None
        show_hosted = self.has_hosted_access
        self.choices.layout.display = "flex" if choosing else "none"
        self.hosted_button.layout.display = "" if show_hosted else "none"
        self.back_button.layout.display = "none" if choosing else ""
        self.hosted_details.layout.display = "flex" if hosted_view else "none"
        self.open_compute_button.layout.display = "" if hosted_view else "none"
        self.widgets.setup_section.layout.display = "none" if choosing else "flex"
        self.widgets.byo_configuration.layout.display = "flex" if self._preference == BYO else "none"
        if not hosted_view:
            return
        _, reason = self.route()
        try:
            expiry = (datetime.fromtimestamp(s.expires_at, timezone.utc).strftime("%b %d, %Y %H:%M UTC")
                      if s.expires_at else "not provided")
        except (ValueError, OverflowError, OSError):
            expiry = "unavailable"
        self.credit.value = (
            f"<div style='padding:10px;background:#eef5ff;border:1px solid #ceddf0'>"
            f"<b>{escape(s.pool_name or 'CryoStack pilot credit')}</b><br>"
            f"Available {_money(s.available_cents)} · Held {_money(s.reserved_cents)} · Used {_money(s.charged_cents)}"
            f"<br>Expires: {escape(expiry)}. Allocations do not refill automatically.</div>"
        ) if show_hosted else ""
        self.reason.value = f"<div style='font-size:12px'>{escape(reason)}</div>"
        self.widgets.run_estimate_section.layout.display = "flex"
        self.widgets.run_estimate_line.value = "<div>Fixed pilot resources. Review the credit hold before launching.</div>"
        hosted_issm = show_hosted and self.model() == "issm" and "issm" in s.models
        self.license_box.layout.display = "flex" if hosted_issm else "none"
        self.license_value.layout.display = "none" if s.license_configured else ""
        self.license_button.description = "Replace pilot license" if s.license_configured else "Configure pilot license"
        self.license_status.value = "MATLAB license configured." if s.license_configured else "A MATLAB license is required for ISSM."
        if self.connector_box is not None:
            required = hosted_issm and getattr(s, "license_requires_connector", False)
            self.connector_box.layout.display = "flex" if required else "none"
            if required:
                self.connector_refresh()

    def refresh(self, _=None):
        import asyncio
        from cryostack_src.cloud.pilot.client import pilot_summary
        from cryostack_src.frontend.cryolauncher.cloud_runtime import _spawn
        if self.refresh_button.disabled:
            return

        async def drive():
            self.refresh_button.disabled = True
            try:
                previous = self.summary
                self.summary = await asyncio.to_thread(pilot_summary, self.user_id)
                self.render()
                if self._preference == HOSTED and self.summary != previous:
                    self.on_change()
            finally:
                self.refresh_button.disabled = False
        _spawn(drive())

    def configure_license(self, _=None):
        import asyncio
        from cryostack_src.cloud.pilot.client import set_matlab_license
        from cryostack_src.frontend.cryolauncher.cloud_runtime import _spawn
        if self.summary.license_configured and self.license_value.layout.display == "none":
            self.license_value.layout.display = ""
            return
        value = self.license_value.value
        self.license_value.value = ""  # never preserve the raw value in widget state
        if not value.strip():
            self.license_status.value = "Enter the MATLAB license value."
            return
        async def drive():
            self.license_button.disabled = True
            try:
                await asyncio.to_thread(set_matlab_license, value, user_id=self.user_id)
                self.license_status.value = "MATLAB license configured. Refreshing pilot credit…"
                self.refresh()
            except Exception as error:
                # Client removes the raw license from errors; escape markup too.
                self.license_status.value = escape(str(error))
            finally:
                self.license_button.disabled = False
        _spawn(drive())


def workspace_hosted_bridge(manager, *, user_id, region=""):
    from cryostack_src.cloud.pilot.client import HostedBridge
    raw = HostedBridge(user_id, region=region)
    class BoundBridge:
        def __getattr__(self, name):
            return getattr(raw, name)
        def results(self, **kwargs):
            return sync_hosted_results(manager, raw, run_job_id=kwargs.get("job_id"))
    return BoundBridge()

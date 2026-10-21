"""Mode selection, the workflow stepper, the Local environment panel, and
Review & Launch -- which becomes the active-run panel once a run starts.

Mode is the first decision: it decides where the run executes, which
environment settings apply, and what "Launch" means (start a local process,
submit a Slurm job, or review an AWS Batch launch). Changing it swaps the
environment panel and re-validates; nothing from the previous mode leaks
into the summary.
"""
from __future__ import annotations

import re
import threading

import ipywidgets as W

from icesee_jupyter_book.core import run_lifecycle as lc
from icesee_jupyter_book.core.experiment_files import Issue
from icesee_jupyter_book.core.local_jobs import environments

from .components import (
    BusyButton, ConfirmAction, badge, button, callout, card, esc, field, human_duration, issues_html, kv,
    state_badge,
)

MODES = (("Local", "local"), ("Remote HPC", "cluster"), ("Cloud", "cloud"))
MODE_HELP = {
    "local": "Runs on this CryoStack server, in its Python or in the ICESEE container. Best for small "
             "experiments and checking a configuration.",
    "cluster": "Submits a Slurm job to your HPC allocation (e.g. PACE) through the CryoStack Connector or SSH, "
               "using ICESEE-Spack or the ICESEE container with MPI.",
    "cloud": "Launches an AWS Batch job in your connected AWS account. You review the cost and readiness "
             "before anything starts.",
}
LAUNCH_LABEL = {"local": ("Launch run", "play"), "cluster": ("Submit to cluster", "server"),
                "cloud": ("Review cloud launch", "cloud-upload")}
STEPS = ("Mode", "Experiment", "Environment", "Parameters", "Review & launch", "Monitor", "Results")


class ModeSelector:
    def __init__(self, initial: str = "local"):
        self.toggle = W.ToggleButtons(options=list(MODES), value=initial, icons=["laptop", "server", "cloud"],
                                      tooltips=[MODE_HELP[m] for _l, m in MODES], style={"button_width": "auto"})
        self.note = W.HTML()
        box = W.Box([self.toggle], layout=W.Layout(width="100%"))
        box.add_class("icw-modes")
        self.container = card([box, self.note], title="Mode", number=1, css="icw-anchor-mode",
                              subtitle="Where should this experiment run? This decides the rest of the setup.")
        self.toggle.observe(lambda _c: self._note(), names="value")
        self._note()

    @property
    def value(self) -> str:
        return self.toggle.value

    def _note(self) -> None:
        self.note.value = f'<div class="icw-mode-note">{esc(MODE_HELP[self.toggle.value])}</div>'

    def attach_assistant(self, widget: W.Widget) -> None:
        """Place the configuration assistant (Auto-config) inside the Mode card,
        under the mode note: it fills in mode, experiment and resources, so it
        belongs with the first decision rather than below Review & launch."""
        widget.add_class("icw-mode-assistant")
        self.container.children = (*self.container.children, widget)


#: where each step lives on the page (card anchor class, or a workspace tab)
STEP_TARGETS = {"Mode": ".icw-anchor-mode", "Experiment": ".icw-anchor-experiment",
                "Environment": ".icw-anchor-environment", "Parameters": ".icw-anchor-parameters",
                "Review & launch": ".icw-anchor-launch", "Monitor": "tab:Run", "Results": "tab:Results"}


def tab_slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


class Stepper:
    """Sticky progress bar: where the user is in the workflow, what needs
    attention, and the active run's live state. Steps are links to their
    section."""

    def __init__(self, steps=STEPS, targets=None):
        """``steps`` and ``targets`` default to ICESEE's; another application
        passes its own (a ``tab:<title>`` target also opens an ipywidgets Tab
        of that title, for applications whose workspace is a W.Tab)."""
        self.step_names = tuple(steps)
        self.targets = dict(targets or STEP_TARGETS)
        self.steps = W.HTML()
        self.live = W.HTML()
        self.html = W.HBox([self.steps, self.live], layout=W.Layout(width="100%"))
        self.html.add_class("icw-bar")
        self.update({})

    def update(self, states: dict) -> None:
        items = []
        for i, name in enumerate(self.step_names, 1):
            cls = states.get(name, "")
            aria = ' aria-current="step"' if "current" in cls else ""
            target = self.targets[name]
            if target.startswith("tab:"):
                tab = target[4:]
                # ICESEE's own tab bar, else a hidden jump button an application
                # with an ipywidgets Tab provides (class icw-tabjump-<slug>)
                js = ("var b=document.querySelector('.icw-tabs button[data-value=\\'" + tab + "\\']')"
                      "||document.querySelector('.icw-tabjump-" + tab_slug(tab) + "');"
                      "if(b){b.click();(document.querySelector('.cryostack-output-workspace,.icw-cl-workspace')||b)"
                      ".scrollIntoView({behavior:'smooth',block:'nearest'});}")
            else:
                js = f"var e=document.querySelector('{target}');if(e)e.scrollIntoView({{behavior:'smooth',block:'start'}});"
            label = {"attention": "needs attention", "done": "done", "current": "current step"}
            sr = next((v for k, v in label.items() if k in cls), "")
            items.append(f'<li class="icw-step {cls}"{aria} role="link" tabindex="0" title="{esc(name)}'
                         f'{": " + sr if sr else ""}" onclick="{js}" onkeydown="if(event.key===\'Enter\'){{{js}}}">'
                         f'<span class="n">{"✓" if "done" in cls else i}</span>{esc(name)}</li>')
        self.steps.value = f'<ol class="icw-stepper" aria-label="Workflow progress">{"".join(items)}</ol>'

    def set_live(self, html: str) -> None:
        self.live.value = f'<div class="icw-live" aria-live="polite">{html}</div>' if html else ""


class LocalEnvironmentPanel:
    """Local mode: which environment runs the model, and its processes."""

    def __init__(self):
        self.env = W.ToggleButtons(options=[("Launcher Python", "native"), ("ICESEE container", "container")],
                                   value="native", style={"button_width": "auto"})
        seg = W.Box([self.env])
        seg.add_class("icw-segment")
        self.status = W.HTML()
        self.np = W.BoundedIntText(value=2, min=1, max=64, tooltip="MPI ranks (container only)")
        self.model_nprocs = W.BoundedIntText(value=1, min=0, max=64, tooltip="Processes per model run")
        self.np_row = field("MPI processes", self.np, "mpirun -np")
        self.nprocs_row = field("Model processes", self.model_nprocs, "per model run")
        self.report = W.Checkbox(value=False, description="Also run read_results.ipynb (saved as report.ipynb)",
                                 indent=False, layout=W.Layout(width="auto"))
        self.container = W.VBox([field("Runs in", seg), self.status, self.np_row, self.nprocs_row, self.report],
                                layout=W.Layout(gap="8px"))
        self.env.observe(lambda _c: self._toggle(), names="value")
        self._model = ""
        self._toggle()

    def set_model(self, model: str) -> None:
        self._model = model
        envs = {e.kind: e for e in environments(model)}
        if not envs["native"].available and envs["container"].available and self.env.value == "native":
            self.env.value = "container"
        elif not envs["container"].available and envs["native"].available and self.env.value == "container":
            self.env.value = "native"
        self._render(envs)

    def _toggle(self) -> None:
        container = self.env.value == "container"
        self.np_row.layout.display = "" if container else "none"
        self.nprocs_row.layout.display = "" if container else "none"
        self.report.layout.display = "none" if container else ""
        if self._model:
            self._render({e.kind: e for e in environments(self._model)})

    def _render(self, envs) -> None:
        chosen = envs[self.env.value]
        other = envs["container" if self.env.value == "native" else "native"]
        if chosen.available:
            msg = badge("Ready", "ok") + f' <span class="icw-card-sub">{esc(chosen.label)}</span>'
        else:
            msg = badge("Not available", "bad") + f' <span class="icw-card-sub">{esc(chosen.reason)}</span>'
        hint = ""
        if not chosen.available and other.available:
            hint = f'<div class="icw-card-sub">Choose <b>{esc(other.label)}</b> instead.</div>'
        self.status.value = f'<div class="icw-badges">{msg}</div>{hint}'


class LaunchPanel:
    """Review & Launch, and the active run after launch.

    ``on_launch`` is called on a worker thread and must return ``(ok,
    message, run_id)``; the button shows the transition Launch ->
    Submitting… -> Submitted and repeated clicks are ignored while it runs.
    """

    def __init__(self, *, on_launch, on_validate, on_cancel, on_open_logs, on_open_results):
        self.on_launch, self.on_validate, self.on_cancel = on_launch, on_validate, on_cancel
        self.on_open_logs, self.on_open_results = on_open_logs, on_open_results
        self.mode = "local"
        self.summary = W.HTML()
        self.issues = W.HTML()
        self.launch_btn = button("Launch run", icon="play", kind="hero", tooltip="Start the run with this configuration")
        self.launch_busy = BusyButton(self.launch_btn)
        self.launch_btn.on_click(lambda _b: self._launch())
        self.validate_btn = button("Check configuration", icon="check-square-o", kind="secondary")
        self.validate_btn.on_click(lambda _b: self.revalidate(show_ok=True))
        self.activity = W.HTML()
        self.message = W.HTML()
        actions = W.HBox([self.launch_btn, self.validate_btn])
        actions.add_class("icw-actions")
        self.review = W.VBox([self.summary, self.issues, actions, self.activity, self.message], layout=W.Layout(gap="10px"))

        # active run
        self.run_head = W.HTML()
        self.run_progress = W.HTML()
        self.run_detail = W.HTML()
        self.logs_btn = button("View logs", icon="terminal", kind="secondary")
        self.logs_btn.on_click(lambda _b: self.on_open_logs())
        self.results_btn = button("Open results", icon="line-chart", kind="primary")
        self.results_btn.on_click(lambda _b: self.on_open_results())
        self.cancel_btn = button("Cancel run", icon="stop", kind="danger")
        self.cancel_confirm = ConfirmAction(self.cancel_btn, lambda: threading.Thread(target=self._cancel, daemon=True).start(),
                                            confirm_label="Confirm cancel")
        self.new_btn = button("Configure a new run", icon="plus", kind="quiet")
        self.new_btn.on_click(lambda _b: self.show_review())
        run_actions = W.HBox([self.results_btn, self.logs_btn, self.cancel_confirm.box, self.new_btn])
        run_actions.add_class("icw-actions")
        self.active = W.VBox([self.run_head, self.run_progress, self.run_detail, run_actions], layout=W.Layout(gap="10px"))
        self.active.layout.display = "none"

        self.header_badge = W.HTML(badge("Ready to review", "neutral"))
        self.container = card([self.review, self.active], title="Review & launch", number=5,
                              subtitle="What will run, where, and whether it is ready.", right=self.header_badge,
                              emphasis=True, css="icw-anchor-launch")
        self._issues: list = []
        self._run = None
        self.live_html = ""

    # ── review ────────────────────────────────────────────────────────────
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        label, icon = LAUNCH_LABEL[mode]
        self.launch_busy.relabel(label, icon)

    def set_summary(self, rows) -> None:
        self.summary.value = kv(rows)

    def revalidate(self, *, show_ok: bool = False) -> list:
        try:
            issues = list(self.on_validate())
        except Exception as exc:  # noqa: BLE001
            issues = [Issue("error", f"validation failed: {exc}")]
        self._issues = issues
        errors = [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning"]
        if errors:
            self.issues.value = issues_html(errors + warnings)
            self.header_badge.value = badge(f"{len(errors)} to fix", "bad")
            self.launch_btn.disabled = True
            self.launch_btn.tooltip = "Fix the problems listed above first"
        else:
            self.issues.value = issues_html(warnings) if warnings else (
                callout("Configuration checked — ready to launch.", "ok") if show_ok else "")
            self.header_badge.value = badge("Ready", "ok") if not warnings else badge("Ready, with notes", "warn")
            if not self.launch_busy.busy:
                self.launch_btn.disabled = False
            self.launch_btn.tooltip = LAUNCH_LABEL[self.mode][0]
        return issues

    def set_activity(self, state: str, text: str = "") -> None:
        """Feedback for backend operations (SSH checks, submissions, status)."""
        tone = {"running": "running", "done": "ok", "fail": "bad", "idle": "neutral"}.get(state, "neutral")
        label = {"running": "Working…", "done": "Done", "fail": "Failed — see Logs › Launcher activity",
                 "idle": ""}.get(state, state)
        if state == "idle" or not label:
            self.activity.value = ""
            return
        spin = '<span class="icw-spinner"></span> ' if state == "running" else ""
        self.activity.value = (f'<div class="icw-badges">{spin}{badge(label, tone, dot=state != "running")}'
                               f'<span class="icw-card-sub" style="margin:0">{esc(text)}</span></div>')

    def _launch(self) -> None:
        if not self.launch_busy.claim():
            return                                        # already launching: ignore the extra click
        if [i for i in self.revalidate() if i.level == "error"]:
            self.launch_busy._lock.release()
            return
        busy = {"local": "Starting…", "cluster": "Submitting…", "cloud": "Preparing review…"}[self.mode]
        done = {"local": "Started", "cluster": "Submitted", "cloud": "Review ready"}[self.mode]
        holder = {}

        def act():
            ok, message, run_id = self.on_launch()
            holder.update(ok=ok, message=message, run_id=run_id)
            return bool(ok)

        def worker():
            self.message.value = ""
            self.launch_busy.run(act, busy_label=busy, done_label=done, fail_label="Not launched", claimed=True)
            if holder.get("ok"):
                self.message.value = callout(holder.get("message") or "", "ok") if holder.get("message") else ""
            else:
                self.message.value = callout(holder.get("message") or "The launch did not complete. See Logs.", "bad")
        threading.Thread(target=worker, daemon=True).start()

    # ── active run ────────────────────────────────────────────────────────
    def show_review(self) -> None:
        self.review.layout.display = ""
        self.active.layout.display = "none"
        self.revalidate()

    def show_run(self, run, *, status=None) -> None:
        """Show ``run`` (RunInfo) as the active run; ``status`` is a live
        JobStatus for local runs."""
        self._run = run
        state = lc.current_state(run)
        self.review.layout.display = "none"
        self.active.layout.display = ""
        meta = run.metadata or {}
        elapsed = status.elapsed if status is not None else None
        if elapsed is None:
            started = next((e.get("at") for e in meta.get("lifecycle") or [] if e.get("state") == "running"), None)
            if started:
                from datetime import datetime

                try:
                    end = run.finished or datetime.now()
                    elapsed = (end - datetime.fromisoformat(started)).total_seconds()
                except (TypeError, ValueError):
                    elapsed = None
        self.header_badge.value = state_badge(state)
        live_bits = [state_badge(state), f"<span>Run <b>{esc(run.id)}</b></span>"]
        if elapsed is not None:
            live_bits.append(f"<span>elapsed {human_duration(elapsed)}</span>")
        if status is not None and status.step and state in lc.ACTIVE:
            live_bits.append(f"<span>step {status.step[0]}/{status.step[1]}</span>")
        self.live_html = " ".join(live_bits)
        self.run_head.value = (f'<div class="icw-runhead"><div><div class="icw-card-sub" style="margin:0">Run</div>'
                               f'<div style="font-weight:700;color:var(--ic-ink)">{esc(run.id)}</div>'
                               f'<div class="icw-card-sub">{esc(str(meta.get("example") or ""))}</div></div>'
                               f'<div style="text-align:right"><div class="icw-card-sub" style="margin:0">Elapsed</div>'
                               f'<div class="big" aria-live="off">{human_duration(elapsed)}</div></div></div>')
        pct = status.progress if status is not None else None
        if state in lc.ACTIVE:
            stage = (status.stage if status is not None and status.stage else lc.LABELS.get(state, state))
            step = f" · step {status.step[0]} of {status.step[1]}" if status is not None and status.step else ""
            bar = (f'<div class="icw-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" '
                   f'aria-valuenow="{int((pct or 0) * 100)}"><span style="width:{(pct or 0) * 100:.1f}%"></span></div>'
                   if pct is not None else '<div class="icw-progress indeterminate"><span></span></div>')
            self.run_progress.value = (f'<div class="icw-badges" style="margin-bottom:6px">{state_badge(state)}'
                                       f'<span class="icw-card-sub" style="margin:0">{esc(stage)}{esc(step)}</span></div>{bar}')
        elif state == lc.COMPLETED:
            warn = meta.get("warnings")
            self.run_progress.value = callout("The run finished. Its results are ready to inspect.", "ok") + (
                callout("; ".join(map(str, warn)), "warn") if warn else "")
        elif state == lc.FAILED:
            self.run_progress.value = callout(str(meta.get("final_detail") or "The run failed. See Logs."), "bad",
                                              title="Run failed:")
        elif state == lc.CANCELLED:
            self.run_progress.value = callout("The run was cancelled.", "info")
        self.run_detail.value = kv([
            ("Mode", esc({"local": "Local", "remote": "Remote HPC", "cloud": "Cloud"}.get(run.execution_mode, run.execution_mode))),
            ("Backend", esc(run.backend)),
            ("Job ID", f"<code>{esc(str(run.jobid))}</code>" if run.jobid else ""),
            ("Filter · members", esc(f"{meta.get('assimilation_filter') or '?'} · {meta.get('ensemble_size') or '?'}")),
        ])
        self.results_btn.disabled = state in lc.ACTIVE and run.execution_mode == "local"
        self.results_btn.description = "Open results" if state == lc.COMPLETED else "Results"
        self.cancel_confirm.box.layout.display = "" if state in lc.ACTIVE else "none"
        self.new_btn.layout.display = "none" if state in lc.ACTIVE else ""

    def _cancel(self) -> None:
        if self._run is None:
            return
        self.run_progress.value = callout("Cancelling…", "info")
        ok, message = self.on_cancel(self._run)
        if not ok:
            self.run_progress.value = callout(message, "bad")


class Ticker:
    """Calls ``fn`` every ``interval`` seconds on a daemon thread until stopped."""

    def __init__(self, fn, interval: float = 1.0):
        self.fn, self.interval = fn, interval
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if self.fn() is False:
                    return
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._stop.set()

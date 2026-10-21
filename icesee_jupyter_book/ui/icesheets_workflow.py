"""CryoLauncher's page in the workflow layout ICESEE uses (ui/icesee_workflow).

Mode first (where the run executes, and the interface: Basic, Advanced or
Auto-config) -> Experiment -> Environment & resources -> Parameters ->
Review & launch on the left; the run Workspace (Editor / Runs / Files /
Run Log / Results) on the right; a stepper on top.

This module only *arranges* widgets the gateway (icesheets_gateway.py) has
already built and wired -- every control, handler and visibility rule stays
where it was. The only new controls are the mode toggle (two-way bound to
the existing execution-mode dropdown) and the card shells. A card whose
contents are all hidden by the gateway's ``update_visibility`` (e.g. every
manual card while Auto-config is selected) is hidden with them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import ipywidgets as W

from icesee_jupyter_book.ui.icesee_workflow.components import card, esc
from icesee_jupyter_book.ui.icesee_workflow.launch import Stepper, tab_slug

STEPS = ("Mode", "Experiment", "Environment", "Parameters", "Review & launch", "Monitor", "Results")
STEP_TARGETS = {"Mode": ".icw-anchor-mode", "Experiment": ".icw-anchor-experiment",
                "Environment": ".icw-anchor-environment", "Parameters": ".icw-anchor-parameters",
                "Review & launch": ".icw-anchor-launch", "Monitor": "tab:Run Log", "Results": "tab:Results"}
MODE_ICONS = {"local": "laptop", "remote": "server", "cluster": "server", "cloud": "cloud"}
MODE_LABELS = {"remote": "Remote HPC", "cloud": "Cloud", "local": "Local"}
MODE_HELP = {
    "remote": "Submits a Slurm job to your HPC allocation through the CryoStack Connector or SSH, using "
              "ICESEE-Spack or the ICESEE container.",
    "cloud": "Launches an AWS Batch job in your connected AWS account. You review the cost and readiness "
             "before anything starts.",
    "local": "Runs on this CryoStack server.",
}
INTERFACE_HELP = {
    "basic": "Basic: curated examples and validated parameters.",
    "advanced": "Advanced: custom paths, the file editor and your own datasets.",
    "agent": "Auto-config: describe the run and the assistant prepares its configuration for the "
             "selected execution mode. Switch to Basic or Advanced to review it field by field.",
}


@dataclass
class CryoLauncherWorkflow:
    hero: W.HTML
    stepper: Stepper
    shell: W.HBox
    left: W.VBox
    right: W.VBox
    mode_toggle: W.ToggleButtons
    modes_box: W.Box = None
    cards: dict = field(default_factory=dict)
    _sections: dict = field(default_factory=dict)

    def refresh(self, *, example_chosen: bool = False, run_state: str = "", manual: bool = True) -> None:
        """Hide cards whose contents are all hidden; update the stepper.
        ``manual`` is False while Auto-config is the interface. The execution
        mode toggle stays visible in every interface: Auto-config plans for
        the selected mode and never changes it."""
        for name, widgets in self._sections.items():
            shown = any(getattr(w.layout, "display", "") != "none" for w in widgets)
            self.cards[name].layout.display = "" if shown else "none"
        states = {"Mode": "done"}
        if self.cards["experiment"].layout.display != "none":
            states["Experiment"] = "done" if example_chosen else "current"
            if example_chosen:
                states["Review & launch"] = "current"
        if run_state in ("running", "submitted", "queued", "pending"):
            states["Monitor"] = "current"
        elif run_state in ("completed", "done", "succeeded"):
            states.update({"Monitor": "done", "Results": "current"})
        elif run_state in ("failed", "error"):
            states["Monitor"] = "attention"
        self.stepper.update(states)


def _tab_jumps(tabs: W.Tab | None, titles: list) -> list:
    """Hidden buttons the stepper clicks to open a workspace tab by title
    (titles, not indices: Advanced mode inserts the Editor tab first)."""
    if tabs is None:
        return []
    out = []
    for title in titles:
        b = W.Button(description=title, layout=W.Layout(display="none"))
        b.add_class(f"icw-tabjump-{tab_slug(title)}")

        def go(_b, title=title):
            for i in range(len(tabs.children)):
                if tabs.get_title(i) == title:
                    tabs.selected_index = i
                    return
        b.on_click(go)
        out.append(b)
    return out


def _mode_toggle(mode_dd: W.Dropdown) -> W.ToggleButtons:
    options = [(MODE_LABELS.get(v, label), v) for label, v in mode_dd.options]
    toggle = W.ToggleButtons(options=options, value=mode_dd.value,
                             icons=[MODE_ICONS.get(v, "circle") for _l, v in options],
                             tooltips=[MODE_HELP.get(v, "") for _l, v in options],
                             style={"button_width": "auto"})
    busy = [False]

    def to_dropdown(change):
        if busy[0]:
            return
        busy[0] = True
        try:
            if mode_dd.value != change["new"]:
                mode_dd.value = change["new"]
        finally:
            busy[0] = False

    def to_toggle(change):
        if busy[0]:
            return
        busy[0] = True
        try:
            if toggle.value != change["new"]:
                toggle.value = change["new"]
        finally:
            busy[0] = False

    toggle.observe(to_dropdown, names="value")
    mode_dd.observe(to_toggle, names="value")
    return toggle


def build_cryolauncher_workflow(*, mode_dd: W.Dropdown, ui_mode_dd: W.ToggleButtons, agent_panel=None,
                                experiment_rows: list, environment_rows: list, parameter_rows: list,
                                review_rows: list, workspace: W.Widget,
                                workspace_tabs: W.Tab | None = None) -> CryoLauncherWorkflow:
    hero = W.HTML(
        "<div class='icw-hero'><div><h1>Ice-Sheet Modeling</h1>"
        "<p>Launch supported ice-sheet models (ISSM, Icepack) on your HPC allocation or in the cloud, "
        "without the ICESEE data-assimilation layer, and inspect their results here.</p></div></div>")
    stepper = Stepper(steps=STEPS, targets=STEP_TARGETS)

    # ── 1. Mode ─────────────────────────────────────────────────────────
    toggle = _mode_toggle(mode_dd)
    modes = W.Box([toggle], layout=W.Layout(width="100%"))
    modes.add_class("icw-modes")
    modes.add_class(f"icw-modes-{len(toggle.options)}")
    mode_note = W.HTML()
    interface_note = W.HTML()

    def _notes(_=None):
        mode_note.value = f'<div class="icw-mode-note">{esc(MODE_HELP.get(mode_dd.value, ""))}</div>'
        interface_note.value = f'<div class="icw-mode-note">{esc(INTERFACE_HELP.get(ui_mode_dd.value, ""))}</div>'

    mode_dd.observe(_notes, names="value")
    ui_mode_dd.observe(_notes, names="value")
    _notes()
    ui_mode_dd.style = {"button_width": "auto"}
    segment = W.Box([ui_mode_dd])
    segment.add_class("icw-segment")
    interface = W.HBox([W.HTML("<label>Interface</label>"), segment], layout=W.Layout(width="100%"))
    interface.add_class("icw-field")
    assistant = []
    if agent_panel is not None:
        agent_panel.container.add_class("icw-mode-assistant")
        assistant.append(agent_panel.container)
    mode_card = card([modes, mode_note, interface, interface_note, *assistant], title="Mode", number=1,
                     subtitle="Where should this run execute, and how do you want to configure it?",
                     css="icw-anchor-mode")

    # ── 2-5 ─────────────────────────────────────────────────────────────
    experiment_card = card(list(experiment_rows), title="Experiment", number=2,
                           subtitle="The model and the example to run.", css="icw-anchor-experiment")
    environment_card = card(list(environment_rows), title="Environment & resources", number=3,
                            subtitle="Connection, software and compute for the selected mode.",
                            css="icw-anchor-environment")
    parameters_card = card(list(parameter_rows), title="Parameters", number=4,
                           subtitle="The model's validated configuration (Basic).", css="icw-anchor-parameters")
    review_card = card(list(review_rows), title="Review & launch", number=5,
                       subtitle="Check what will run, then launch it.", css="icw-anchor-launch", emphasis=True)

    for rows in (experiment_rows, environment_rows, parameter_rows, review_rows):
        for row in rows:
            row.add_class("icw-cl-row")

    left = W.VBox([mode_card, experiment_card, environment_card, parameters_card, review_card],
                  layout=W.Layout(width="100%", min_width="0"))
    for css in ("icw-col", "cryostack-left-workspace"):
        left.add_class(css)

    head = W.HTML('<div class="icw-card-head"><div><div class="icw-card-title">Workspace</div>'
                  '<div class="icw-card-sub">Your runs, their files, logs and results.</div></div></div>')
    jumps = _tab_jumps(workspace_tabs, [t[4:] for t in STEP_TARGETS.values() if t.startswith("tab:")])
    workspace_card = W.VBox([head, workspace, *jumps], layout=W.Layout(width="100%", gap="10px"))
    for css in ("icw-card", "icw-right", "icw-cl-workspace"):
        workspace_card.add_class(css)
    right = W.VBox([workspace_card], layout=W.Layout(width="100%", min_width="0"))
    for css in ("icw-col", "cryostack-right-workspace"):
        right.add_class(css)

    shell = W.HBox([left, right], layout=W.Layout(width="100%"))
    shell.add_class("icw-shell")

    wf = CryoLauncherWorkflow(
        hero=hero, stepper=stepper, shell=shell, left=left, right=right, mode_toggle=toggle, modes_box=modes,
        cards={"mode": mode_card, "experiment": experiment_card, "environment": environment_card,
               "parameters": parameters_card, "review": review_card},
        _sections={"experiment": list(experiment_rows), "environment": list(environment_rows),
                   "parameters": list(parameter_rows), "review": list(review_rows)})
    wf.refresh()
    return wf


#: CryoLauncher-specific touches on top of the shared workflow stylesheet:
#: legacy form rows and the W.Tab workspace in the workflow look.
CSS = """
<style>
/* layout: the workflow card owns the heading; legacy boxes inside cards lose their own frame */
.icw .icw-cl-workspace .cryostack-workspace-heading { display:none !important; }
.icw .icw-modes-2 .widget-toggle-buttons > div { grid-template-columns: repeat(2, minmax(0,1fr)) !important; }
.icw .icw-anchor-mode .icw-field { align-items:center; }
.icw .icw-anchor-mode .icw-field label { font-size:13px; font-weight:600; color: var(--ic-ink); min-width:120px; }
.icw .icw-cl-row .icesee-lbl { font-size:13px; font-weight:600; color: var(--ic-ink); }
.icw .icw-cl-row.widget-hbox { align-items:center; }
.icw .icw-card .icw-cl-row.icesee-card, .icw .icw-card .icw-cl-row .icesee-card,
.icw .icw-anchor-launch .icw-cl-row, .icw .icw-anchor-launch .icw-cl-row > .widget-vbox {
  border:0 !important; box-shadow:none !important; background:transparent !important; padding-left:0 !important; padding-right:0 !important; }

/* accordions (Remote connection, Slurm, ISSM/Icepack Basic, Command preview ...) */
.icw .icw-card .jupyter-widget-Collapse, .icw .icw-card .lm-Collapse { border:1px solid var(--ic-border); border-radius:10px; overflow:hidden; margin:0 0 8px 0; }
.icw .icw-card .jupyter-widget-Collapse-header, .icw .icw-card .lm-Collapse-header {
  background: var(--ic-surface) !important; border:0 !important; color: var(--ic-ink) !important;
  font-weight:600; font-size:13px; padding:9px 12px !important; }
.icw .icw-card .jupyter-widget-Collapse-header:hover, .icw .icw-card .lm-Collapse-header:hover { background: var(--ic-primary-soft) !important; }
.icw .icw-card .jupyter-widget-Collapse-open > .jupyter-widget-Collapse-header { color: var(--ic-primary) !important; }
.icw .icw-card .jupyter-widget-Collapse-contents, .icw .icw-card .lm-Collapse-contents {
  border:0 !important; border-top:1px solid var(--ic-border) !important; background: var(--ic-surface) !important; }

/* the workspace Tab in the workflow tab look */
.icw .icw-cl-workspace .lm-TabBar, .icw .icw-cl-workspace .p-TabBar { border-bottom:1px solid var(--ic-border) !important; min-height:38px; background:transparent !important; }
.icw .icw-cl-workspace .lm-TabBar-content, .icw .icw-cl-workspace .p-TabBar-content { border:0 !important; gap:2px; }
.icw .icw-cl-workspace .lm-TabBar-tab, .icw .icw-cl-workspace .p-TabBar-tab {
  background: transparent !important; border:0 !important; border-bottom:2px solid transparent !important;
  color: var(--ic-muted) !important; font-weight:600; font-size:13px; padding:8px 14px !important;
  margin:0 !important; min-width:0 !important; max-width:none !important; flex: 0 0 auto !important; height:auto !important; }
.icw .icw-cl-workspace .lm-TabBar-tab:hover, .icw .icw-cl-workspace .p-TabBar-tab:hover { color: var(--ic-ink) !important; }
.icw .icw-cl-workspace .lm-TabBar-tab.lm-mod-current, .icw .icw-cl-workspace .p-TabBar-tab.p-mod-current {
  color: var(--ic-primary) !important; border-bottom-color: var(--ic-primary) !important; transform:none !important; }
.icw .icw-cl-workspace .lm-TabBar-tab.lm-mod-current:before, .icw .icw-cl-workspace .p-TabBar-tab.p-mod-current:before { display:none !important; }
.icw .icw-cl-workspace .widget-tab-contents, .icw .icw-cl-workspace .jupyter-widget-tab-contents {
  border:0 !important; padding:12px 0 0 0 !important; background: transparent !important; }

/* buttons in the workflow button look */
.icw .icw-cl-workspace .jupyter-button:not(.mod-danger):not(.mod-success):not(.mod-primary),
.icw .icw-card .icw-cl-row .jupyter-button:not(.mod-danger):not(.mod-success):not(.mod-primary):not(.mod-active) {
  background: var(--ic-surface) !important; color: var(--ic-ink) !important; border:1px solid var(--ic-border-strong) !important;
  border-radius:8px !important; font-weight:600; }
.icw .icw-cl-workspace .jupyter-button:not(.mod-danger):not(.mod-success):hover { background: var(--ic-primary-soft) !important; }
.icw .icw-cl-workspace .jupyter-button.mod-danger, .icw .icw-card .jupyter-button.mod-danger { border-radius:8px !important; }
.icw .icw-anchor-launch .jupyter-button.mod-success, .icw .icw-anchor-launch .jupyter-button.mod-primary {
  background: var(--ic-primary) !important; color:#fff !important; border-radius:10px !important; font-weight:650; }
</style>
"""

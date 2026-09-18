"""Agent-Beta review over the host's manual configuration, with no run callback."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import html
import re
import ipywidgets as W

from cryostack_src.agents.intent import infer_request
from cryostack_src.agents.diagnosis import (
    diagnosis_request, diagnose_configuration, REMOTE_REVIEW_NOTE,
)


@dataclass
class ConfigurationAgent:
    container: W.VBox
    ask: object
    apply: object


def _value_label(key, value, data):
    if key == "example":
        ex = next((e for e in data["examples"] if e["id"] == value), None)
        return ex["label"].lstrip("⧉ ").strip() if ex else "Current example"
    if key == "model":
        return {"issm": "ISSM", "icepack": "Icepack"}.get(str(value), str(value).title())
    if key == "profile":
        return str(value).upper()
    if key in ("mode", "backend"):
        return str(value).title()
    if value in ("", None):
        return "Not set"
    return str(value)


def _configuration_table(data, proposed=None, retained=()):
    current = data["current"]
    values = dict(current, **(proposed or {}))
    if not values.get("model"):
        ex = next((e for e in data["examples"] if e["id"] == values.get("example")), None)
        if ex:
            values["model"] = ex["model"]
    labels = [("model", "Forecast model" if data["application"] == "icesee" else "Model"),
              ("example", "Example"), ("mode", "Execution")]
    if values.get("mode") == "remote":
        labels += [("profile", "Resource"), ("cpus", "CPUs"), ("nodes", "Nodes"),
                   ("tasks_per_node", "Tasks per node"), ("wall_time", "Time limit"),
                   ("memory", "Memory"), ("account", "Allocation")]
    if data["application"] == "icesee":
        labels += [("filter", "Filter"), ("ensemble_size", "Ensemble members")]
    elif values.get("mode") == "remote":
        labels.append(("backend", "Software"))
    rows = []
    for key, label in labels:
        if key not in values:
            continue
        # Keep the main proposal short. The complete current settings remain
        # available below, including unchanged scheduler details.
        if proposed is not None and key in ("nodes", "tasks_per_node", "wall_time", "memory", "account", "backend") and key not in proposed:
            continue
        if key == "tasks_per_node" and values.get(key) == values.get("cpus") and values.get("nodes", 1) == 1:
            continue
        source = ""
        if proposed is not None:
            source = "<span class='cryostack-help'>Retained</span>" if key not in proposed or key in retained else "<span class='cryostack-help'>From request</span>"
        rows.append(f"<tr><th scope='row' style='text-align:left;font-weight:500;padding:3px 12px 3px 0;vertical-align:top'>{html.escape(label)}</th>"
                    f"<td style='padding:3px 8px 3px 0;overflow-wrap:anywhere'>{html.escape(_value_label(key, values[key], data))}</td><td style='padding:3px 0;white-space:nowrap'>{source}</td></tr>")
    specs = {p["key"]: p["label"] for p in data.get("parameters", {}).get(values.get("model"), [])}
    for key, value in (proposed or {}).get("parameters", {}).items():
        rows.append(f"<tr><th scope='row' style='text-align:left;font-weight:500;padding:3px 12px 3px 0'>{html.escape(specs.get(key,key))}</th><td>{html.escape(str(value))}</td><td class='cryostack-help'>From request</td></tr>")
    return "<table style='width:100%;border-collapse:collapse;font-size:12px;line-height:1.4'>" + "".join(rows) + "</table>"


def _review_values(data):
    """Comparable manual settings, excluding nested ICESEE configuration copies."""
    values = {k: v for k, v in data["current"].items()
              if k not in ("parameters", "overrides")}
    if not values.get("model"):
        example = next((e for e in data["examples"] if e["id"] == values.get("example")), None)
        if example:
            values["model"] = example["model"]
    values.update({"parameter:" + k: v for k, v in data["current"].get("overrides", {}).items()})
    return values


def _configuration_summary(data, values=None, exclude=()):
    """Scientist-facing context only; full snapshots remain internal to safety checks."""
    values = _review_values(data) if values is None else values
    keys = ["model", "example", "mode"]
    if values.get("mode") == "remote":
        keys += ["profile", "cpus"]
    if data["application"] == "icesee":
        keys += ["filter", "ensemble_size"]
    parts = []
    for key in keys:
        if key in exclude or key not in values:
            continue
        label = _value_label(key, values[key], data)
        if key == "cpus":
            label += " CPUs"
        elif key == "ensemble_size":
            label += " ensemble members"
        parts.append(html.escape(label))
    return " · ".join(parts)


def _proposal_source(proposal, key):
    if key in proposal.suggested:
        return "Suggested"
    if key in proposal.retained or (key not in proposal.values and not key.startswith("parameter:")):
        return "Retained"
    return "From request"


def _explanation_request(text):
    text = re.sub(r"[?.!]+$", "", text.strip().lower().replace("’", "'"))
    text = re.sub(r"\s+", " ", text)
    questions = {
        "why did you change this": "changes", "what did you change": "changes",
        "why did you retain this": "retained", "why is this suggested": "suggested",
        "why can't this be applied": "blocked", "why cannot this be applied": "blocked",
        "explain this configuration": "configuration", "why do i need matlab": "matlab",
        "why can't i use gpu": "gpu", "why cannot i use gpu": "gpu",
        "why can't i use multi-node": "multinode", "why can't i use multiple nodes": "multinode",
    }
    return questions.get(text)


def _explain_configuration(kind, data, context=None, findings=()):
    """Presentation over existing provenance/diagnosis; never applies or validates."""
    def messages(title, lines):
        # Explanations never surface paths that may appear in a validation message.
        lines = [re.sub(r"(?<!\w)/[^\s,;]+", "the selected location", str(line)) for line in lines]
        return _messages(title, lines)
    if kind in ("gpu", "multinode", "matlab"):
        from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities
        current = _review_values(data)
        model = current.get("model", "")
        if context and not context.get("applied"):
            model = context["frozen"].values.get("model", model)
        if not model:
            return messages("Workflow requirement", ["Select a supported model and example first."])
        cap = resolve_workflow_capabilities(model="icesee" if data["application"] == "icesee" else model,
                                            forecast_model=model)
        if kind == "matlab":
            reason = ("The selected workflow uses ISSM, which requires MATLAB licensing. This explains the requirement; it does not check license readiness."
                      if cap.requires_matlab_license else "The selected workflow does not require MATLAB licensing.")
        elif kind == "gpu":
            reason = ("The current workflow does not support GPU execution. A GPU request cannot be applied."
                      if not cap.supports_gpu else "GPU capability is available. The existing resource and readiness checks still determine whether this configuration can use it.")
        else:
            reason = ("The current cloud runtime does not support multi-node execution. This does not describe Remote Slurm support."
                      if not cap.supports_multinode else "Multi-node cloud capability is available; the existing resource checks still apply.")
        return messages("Workflow requirement", [reason])
    if kind == "configuration":
        diagnosis = diagnose_configuration(data, findings)
        return ("<div class='cryostack-group-title'>Current experiment</div><div style='font-size:12px'>"
                + _configuration_summary(data) + "</div>"
                + messages("Review needed", diagnosis.issues)
                + messages("Before execution", diagnosis.notes))
    if not context:
        return messages("No current proposal", ["Create a proposal to explain its changes. The existing controls remain the current configuration."])
    proposal = context["frozen"]
    if kind == "blocked":
        blockers = proposal.errors + proposal.unresolved + context.get("issues", [])
        return messages("Why Apply is unavailable" if blockers else "Proposal status", blockers or
                        (["This proposal has already been applied. Review the existing controls."] if context.get("applied") else
                         ["No proposal blocker was found. Create the plan again before applying; execution still requires the existing review checks."]))
    if not proposal.applicable:
        return messages("Proposal needs attention", proposal.errors + proposal.unresolved + context.get("issues", []))
    baseline = context["catalog"]
    current = _review_values(baseline)
    proposed = {k: v for k, v in proposal.values.items() if k != "parameters"}
    proposed.update({"parameter:" + k: v for k, v in proposal.values.get("parameters", {}).items()})
    if kind == "retained":
        changed = {k for k, v in proposed.items() if current.get(k) != v}
        summary = _configuration_summary(baseline, current, exclude=changed)
        return ("<div class='cryostack-group-title'>Retained settings</div><div class='cryostack-help'>"
                + (summary or "No important settings were retained.") + "</div>"
                + messages("Reason", ["These values were already in the controls and were left unchanged. This is not a claim that all execution checks have passed."]))
    labels = dict(model="Model", example="Example", mode="Execution", profile="Resource", cpus="CPUs",
                  nodes="Nodes", tasks_per_node="Tasks per node", wall_time="Time limit", memory="Memory",
                  account="Allocation", backend="Software", filter="Filter", ensemble_size="Ensemble members",
                  parallel_processes="Forecast processes")
    labels.update({"parameter:" + p["key"]: p["label"] for p in baseline.get("parameters", {}).get(proposed.get("model"), [])})
    lines = []
    for key, value in proposed.items():
        source = _proposal_source(proposal, key)
        if (kind == "suggested" and source != "Suggested") or (kind == "changes" and current.get(key) == value):
            continue
        if key not in labels:
            continue
        old = "No override" if key.startswith("parameter:") and key not in current else _value_label(key, current.get(key), baseline)
        reason = proposal.reasons.get(key) or ("You explicitly requested this value." if source == "From request" else
                 "The existing configuration rule supplies this adjustment." if source == "Suggested" else
                 "The current value was left unchanged.")
        lines.append(f"{labels[key]}: {old} → {_value_label(key, value, baseline)} · {source}. {reason}")
    return messages("Applied changes" if context.get("applied") else "Proposed changes",
                    lines or ["No suggested adjustment was made." if kind == "suggested" else "No changes needed."])


def _change_preview(data, proposal):
    current = _review_values(data)
    proposed = {k: v for k, v in proposal.values.items() if k != "parameters"}
    proposed.update({"parameter:" + k: v for k, v in proposal.values.get("parameters", {}).items()})
    labels = dict(model="Forecast model" if data["application"] == "icesee" else "Model",
                  example="Example", mode="Execution", profile="Resource", cpus="CPUs",
                  nodes="Nodes", tasks_per_node="Tasks per node", wall_time="Time limit",
                  memory="Memory", account="Allocation", backend="Software",
                  filter="Filter", ensemble_size="Ensemble members", parallel_processes="Forecast processes")
    model = proposed.get("model", current.get("model"))
    labels.update({"parameter:" + p["key"]: p["label"] for p in data.get("parameters", {}).get(model, [])})
    changes = {k: v for k, v in proposed.items() if k not in current or current[k] != v}
    rows = []
    # Only actual changes receive table rows; unchanged context is secondary.
    keys = list(changes)
    for key in keys:
        value = proposed.get(key, current.get(key))
        source = _proposal_source(proposal, key)
        old = current.get(key)
        old_label = "No override" if key.startswith("parameter:") and key not in current else _value_label(key, old, data)
        cells = [labels.get(key, key.replace("_", " ").capitalize()), old_label,
                 _value_label(key, value, data), source]
        rows.append("<tr>" + "".join("<td style='padding:4px 8px 4px 0;vertical-align:top;overflow-wrap:anywhere'>"
                                     + html.escape(str(cell)) + "</td>" for cell in cells) + "</tr>")
    heading = "<tr>" + "".join("<th scope='col' style='text-align:left;padding:4px 8px 4px 0'>" + label + "</th>"
                               for label in ("Setting", "Current", "Proposed", "Source")) + "</tr>"
    count = len(changes)
    summary = f"{count} setting{'s' if count != 1 else ''} to change" if count else "No changes needed"
    table = ("<table style='width:100%;border-collapse:collapse;font-size:12px;line-height:1.4'><thead>"
             + heading + "</thead><tbody>" + "".join(rows) + "</tbody></table>") if changes else ""
    retained = _configuration_summary(data, dict(current, **proposed), exclude=changes)
    context = ("<div class='cryostack-help' style='margin-top:8px;overflow-wrap:anywhere'>Retained: "
               + retained + "</div>") if retained else ""
    return ("<div class='cryostack-group-title' style='margin:8px 0 4px'>Configuration changes</div>"
            + "<div class='cryostack-help'>" + summary + "</div>" + table + context), changes



def _messages(title, messages):
    if not messages:
        return ""
    # Validation is authoritative; only remove log prefixes for presentation.
    clean = [str(m).replace("[cloud][ERROR] ", "").replace("by the current workflow runtime", "for this experiment").replace("available example metadata", "available examples") for m in dict.fromkeys(messages)]
    return (f"<div style='margin-top:8px;font-weight:600'>{html.escape(title)}</div>"
            "<ul style='margin:4px 0;padding-left:18px;font-size:12px;line-height:1.45'>"
            + "".join(f"<li>{html.escape(m)}</li>" for m in clean) + "</ul>")


def build_configuration_agent(*, catalog, apply_values, snapshot, validate, diagnosis_validate=None):
    """Prepare and apply configuration only; the host owns all execution checks."""
    header = W.HTML("<div class='cryostack-group-title'>Describe your experiment "
                    "<span style='font-size:10px;border:1px solid currentColor;border-radius:8px;padding:1px 5px;margin-left:5px;opacity:.7'>Beta</span></div>"
                    "<div class='cryostack-help'>Prepare settings, review the changes, then apply. Nothing runs automatically.</div>")
    question = W.Textarea(placeholder="Describe the model, example and where to run it.",
                         layout=W.Layout(width="100%", height="70px"))
    create = W.Button(description="Create plan", button_style="primary", layout=W.Layout(width="140px"))
    apply = W.Button(description="Apply to configuration", button_style="primary", disabled=True,
                     layout=W.Layout(width="190px", display="none"))
    result = W.HTML(layout=W.Layout(width="100%"))
    result.add_class("cryostack-agent-proposal")
    state = {}
    # One bounded provenance record, replaced per proposal; no conversation history.
    explanation = {}
    read_only_validate = diagnosis_validate if diagnosis_validate is not None else validate

    def remember(proposal, data, *, issues=()):
        explanation.clear()
        explanation.update(proposal=proposal, frozen=copy.deepcopy(proposal),
                           catalog=copy.deepcopy(data), snapshot=copy.deepcopy(snapshot()),
                           issues=list(issues), applied=False)

    def explain(kind):
        state.clear()
        apply.disabled = True
        apply.layout.display = "none"
        try:
            data = catalog()
            context = explanation or None
            warning = ""
            if context and (data != context.get("current_catalog", context["catalog"])
                            or snapshot() != context["snapshot"]):
                warning = _messages("Stale proposal", ["The manual configuration changed. Create a new proposal; the summary below uses the current controls."])
                context = None
                kind = kind if kind in ("gpu", "multinode", "matlab") else "configuration"
            elif context and context["proposal"] != context["frozen"]:
                warning = _messages("Proposal changed", ["Create a new proposal before asking about its changes."])
                context = None
                kind = "configuration"
            findings = diagnosis_validate() if kind == "configuration" and diagnosis_validate is not None else []
            result.value = warning + _explain_configuration(kind, data, context, findings)
        except Exception:
            result.value = _messages("Unable to explain", ["Review the current controls and create a new proposal."])
        return None

    def ask(text):
        if question.value != text:
            question.value = text
        if _explanation_request(text):
            return explain(_explanation_request(text))
        explanation.clear()
        state.clear()
        apply.disabled = True
        apply.layout.display = "none"
        try:
            data = catalog()
            kind = diagnosis_request(text)
            diagnosis = diagnose_configuration(data, read_only_validate()) if kind else None
            proposal = diagnosis.proposal if diagnosis else infer_request(text, data)
            remember(proposal, data, issues=diagnosis.issues if diagnosis else ())
            if diagnosis:
                result.value = (_messages("Configuration issues", diagnosis.issues)
                                + _messages("Review before execution", diagnosis.notes))
                if not diagnosis.issues:
                    result.value = ("<div class='cryostack-help'>No changes needed in the settings checked here. "
                                    "Use the existing Review controls to confirm execution readiness.</div>" + result.value)
                elif kind == "repair" and proposal.applicable:
                    preview, _ = _change_preview(data, proposal)
                    result.value += preview
                    state.update(kind=kind, text=text, catalog=copy.deepcopy(data),
                                 snapshot=copy.deepcopy(snapshot()), proposal=proposal)
                    apply.layout.display = ""
                    apply.disabled = False
                elif kind == "repair":
                    result.value += "<div class='cryostack-help'>No deterministic repair is available. Resolve these choices in the existing controls, then check again.</div>"
                return proposal
            state.update(text=text, catalog=copy.deepcopy(data), snapshot=copy.deepcopy(snapshot()), proposal=proposal)
            if proposal.applicable:
                result.value, _ = _change_preview(data, proposal)
                result.value += _messages("Required adjustment", proposal.explanations)
                apply.layout.display = ""
                apply.disabled = False
            else:
                unsupported = [m for m in proposal.errors if "not supported" in m or "not available" in m]
                invalid = [m for m in proposal.errors if m not in unsupported]
                result.value = (_messages("Unsupported request", unsupported)
                                + _messages("Invalid settings", invalid)
                                + _messages("Please clarify", proposal.unresolved))
            return proposal
        except Exception:
            state.clear()
            result.value = _messages("Unable to prepare settings", ["Check the selected example and manual configuration, then try again."])
            return None

    def apply_plan():
        proposal = state.get("proposal")
        if proposal is None or not proposal.applicable:
            return None
        try:
            data = catalog()
            if data != state["catalog"] or snapshot() != state["snapshot"]:
                raise ValueError("Settings changed since this proposal. Create a new plan to use the current values.")
            if state.get("kind") == "repair":
                fresh = diagnose_configuration(data, read_only_validate()).proposal
            else:
                fresh = infer_request(state["text"], data)
            if not fresh.applicable or fresh.values != proposal.values:
                raise ValueError("The proposal changed. Create a new plan before applying.")
            apply.disabled = True
            apply.layout.display = "none"
            state.clear()
            before = _review_values(data)
            _, changes = _change_preview(data, fresh)
            if changes:
                apply_values(copy.deepcopy(fresh.values))
            findings = read_only_validate() if fresh.refinement else validate()
            data = catalog()
            explanation.update(current_catalog=copy.deepcopy(data), snapshot=copy.deepcopy(snapshot()),
                               applied=True, issues=list(findings))
            after = _review_values(data)
            count = sum(before.get(k) != after.get(k) for k in before.keys() | after.keys())
            result.value = ("<div class='cryostack-group-title' style='margin-top:8px'>✓ Configuration updated</div>"
                            f"<div class='cryostack-help'>{count} setting{'s' if count != 1 else ''} changed</div>"
                            + "<div style='font-size:12px;margin:6px 0;overflow-wrap:anywhere'>" + _configuration_summary(data) + "</div>"
                            + "<div class='cryostack-help'>The existing controls remain authoritative for review and execution. Nothing has run.</div>"
                            + _messages("Before execution", findings))
            return findings
        except Exception as exc:
            apply.disabled = True
            apply.layout.display = "none"
            state.clear()
            result.value = _messages("Review needed", [str(exc), "No run was started. Check the current controls before continuing."])
            return None

    def request_changed(_):
        state.clear()
        apply.disabled = True
        apply.layout.display = "none"
        result.value = "<div class='cryostack-help'>Request changed. Create a plan to review the new settings.</div>" if question.value.strip() else ""

    create.on_click(lambda _: ask(question.value))
    apply.on_click(lambda _: apply_plan())
    question.observe(request_changed, names="value")
    return ConfigurationAgent(W.VBox([header, question, create, result, apply],
                                    layout=W.Layout(width="100%")), ask, apply_plan)


def parameter_metadata():
    from cryostack_src.models.icepack import BASIC_MODE_PARAMETERS
    from cryostack_src.models.issm import CURATED_MD_PARAMETERS
    return {
        "icepack": [dict(key=p.name, label=p.label, kind=p.kind, min=p.minimum, max=p.maximum)
                    for p in BASIC_MODE_PARAMETERS],
        "issm": [dict(key=p.key, label=p.label, kind=p.kind, min=p.min, max=p.max)
                 for p in CURATED_MD_PARAMETERS if p.kind in ("int", "float", "multiplier", "bool")],
    }


def remote_findings(fields):
    from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources
    from cryostack_src.resources.profiles import get_compute_profile
    profile = get_compute_profile(fields["profile"].value)
    errors = validate_slurm_resources(
        nodes=fields["nodes"].value, tasks=fields["cpus"].value,
        tasks_per_node=fields["tasks_per_node"].value,
        wall_time=fields["wall_time"].value, memory=fields["memory"].value,
        account=fields["account"].value, account_required=profile.account_required)
    from icesee_jupyter_book.ui.shared_validation import validate_remote_identity
    errors.extend(validate_remote_identity(hpc_username=fields["user"].value,
                                           remote_directory=fields["directory"].value))
    errors.append(REMOTE_REVIEW_NOTE)
    return errors


def field_values(fields):
    # Only the explicit scientific/resource allowlist, never passwords or tokens.
    return {k: w.value for k, w in fields.items()}


def set_fields(values, fields):
    # Validate bounds first: ipywidgets otherwise silently clamps values.
    for k, v in values.items():
        if k not in fields:
            continue
        w = fields[k]
        if isinstance(v, (int, float)) and (v < getattr(w, "min", float("-inf")) or v > getattr(w, "max", float("inf"))):
            raise ValueError(f"{k} is outside the manual control's supported range.")
    for k, w in fields.items():
        if k in values:
            w.value = values[k]


def build_icesheets_configuration_agent(*, manager, fields, model, example, mode,
                                       backend, md_panel, icepack_panel,
                                       snapshot, cloud_validate, show_manual):
    from cryostack_src.models import SUPPORTED_MODELS, get_model_adapter, get_model_capabilities
    from cryostack_src.resources.profiles import COMPUTE_PROFILES
    from icesee_jupyter_book.core.icesheet_examples import merged_examples_for_model

    def catalog():
        examples = []
        for name in SUPPORTED_MODELS:
            adapter = get_model_adapter(name)
            for ex in merged_examples_for_model(name, user_examples=manager.list_user_examples(name),
                                               runnable_check=getattr(adapter, "example_runnable", None)):
                if ex.runnable:
                    specs = parameter_metadata().get(name, [])
                    if name == "issm":
                        from cryostack_src.models.issm import detect_solvers, curated_parameters_for
                        from pathlib import Path
                        entry = ex.path / (ex.entrypoint or "runme.m") if ex.path.is_dir() else ex.path
                        try:
                            allowed = {p.key for p in curated_parameters_for(detect_solvers(Path(entry).read_text()))}
                        except OSError:
                            allowed = set()
                        specs = [spec for spec in specs if spec["key"] in allowed]
                    examples.append(dict(id=str(ex.path), label=ex.label, model=name,
                                         modes=list(get_model_capabilities(name).execution_modes),
                                         parameters=specs,
                                         aliases=[ex.path.stem, ex.label.lstrip("⧉ ").strip()]))
        return dict(application="icesheets", examples=examples, resource_switch_requires_review=True, example_switch_requires_review=True,
                    profiles=list(COMPUTE_PROFILES), modes=[v for _, v in mode.options],
                    backends=[v for _, v in backend.options], parameters=parameter_metadata(),
                    current=dict(field_values(fields), model=model.value, example=example.value,
                                 mode=mode.value, backend=backend.value,
                                 overrides=(md_panel.overrides() if model.value == "issm" else icepack_panel.overrides())))

    def apply_values(values):
        model.value = values["model"]
        example.value = values["example"]
        if "mode" in values:
            mode.value = values["mode"]
        if "backend" in values:
            backend.value = values["backend"]
        set_fields(values, fields)
        overrides = values.get("parameters", {})
        panel = md_panel if model.value == "issm" else icepack_panel
        rows = panel._state["rows"] if model.value == "issm" else panel._rows
        unknown = set(overrides) - set(rows)
        if unknown:
            raise ValueError("These settings do not apply to the selected example's solvers: " + ", ".join(sorted(unknown)))
        for key, value in overrides.items():
            set_fields({key: value}, {key: rows[key][1]})
            rows[key][0].value = True

    def validate():
        panel = md_panel if model.value == "issm" else icepack_panel
        errors = list(panel.validate().errors)
        if mode.value == "remote":
            errors.extend(remote_findings(fields))
        elif mode.value == "cloud":
            errors.extend(cloud_validate())
        return errors

    def full_snapshot():
        return dict(snapshot(), model_overrides=(md_panel.overrides() if model.value == "issm" else icepack_panel.overrides()))

    def diagnosis_validate():
        panel = md_panel if model.value == "issm" else icepack_panel
        errors = list(panel.validate().errors)
        if mode.value == "remote":
            errors.extend(remote_findings(fields))
        elif mode.value == "cloud":
            errors.append("Cloud readiness has not been checked here. Use the existing Cloud Review to check account, resources, licensing and runtime support.")
        return errors

    panel = build_configuration_agent(catalog=catalog, apply_values=apply_values,
                                      snapshot=full_snapshot, validate=validate,
                                      diagnosis_validate=diagnosis_validate)
    panel.container.children[1].placeholder = "Run SquareIceShelf with ISSM on PACE using 4 CPUs."
    review = W.Button(description="Review in Advanced", layout=W.Layout(width="190px"))
    review.on_click(lambda _: show_manual())
    panel.container.children = (*panel.container.children, review)
    return panel


def build_icesee_configuration_agent(*, fields, example, mode_tabs, filter_widget,
                                    ensemble, params_snapshot, sync_quick, cloud_validate):
    from cryostack_src.resources.profiles import COMPUTE_PROFILES
    from icesee_jupyter_book.core.example_registry import EXAMPLES, enabled_names
    from icesee_jupyter_book.core.example_discovery import find_params_template
    from icesee_jupyter_book.core.config_io import load_yaml
    from icesee_jupyter_book.core.run_records import da_identity_from_params

    def catalog():
        examples = []
        for name in enabled_names():
            cfg = EXAMPLES[name]
            try:
                identity = da_identity_from_params(load_yaml(find_params_template(cfg)))
                forecast = (identity.forecast_model or cfg["model_name"]).lower()
                canonical = identity.example_name or cfg["base"].name
            except (OSError, ValueError):
                continue
            examples.append(dict(id=name, label=name, model=forecast,
                                 aliases=[name, canonical, cfg["base"].name]))
        return dict(application="icesee", examples=examples, resource_switch_requires_review=True, example_switch_requires_review=True, profiles=list(COMPUTE_PROFILES),
                    modes=["local", "remote", "cloud"], parameters={},
                    filters=[v for _, v in filter_widget.options],
                    current=dict(field_values(fields), example=example.value,
                                 mode=["local", "remote", "cloud"][mode_tabs.selected_index],
                                 ensemble_size=ensemble.value, filter=filter_widget.value,
                                 parameters=params_snapshot()))

    def apply_values(values):
        if values.get("parameters"):
            raise ValueError("Use the selected example's full configuration for additional scientific settings.")
        set_fields({"ensemble_size": values.get("ensemble_size", ensemble.value)}, {"ensemble_size": ensemble})
        example.value = values["example"]
        if "mode" in values:
            mode_tabs.selected_index = ["local", "remote", "cloud"].index(values["mode"])
        if "filter" in values:
            filter_widget.value = values["filter"]
        set_fields(values, fields)
        sync_quick()

    def validate():
        errors = []
        if mode_tabs.selected_index == 1:
            errors.extend(remote_findings(fields))
        if mode_tabs.selected_index == 2:
            errors.extend(cloud_validate())
        return errors

    def snapshot():
        return dict(field_values(fields), example=example.value,
                    mode=["local", "remote", "cloud"][mode_tabs.selected_index],
                    ensemble_size=ensemble.value, filter=filter_widget.value,
                    configuration=params_snapshot())

    def diagnosis_validate():
        if mode_tabs.selected_index == 1:
            return remote_findings(fields)
        if mode_tabs.selected_index == 2:
            return ["Cloud readiness has not been checked here. Use the existing Cloud Review to check account, resources, licensing and runtime support."]
        return []

    panel = build_configuration_agent(catalog=catalog, apply_values=apply_values,
                                      snapshot=snapshot, validate=validate,
                                      diagnosis_validate=diagnosis_validate)
    panel.container.children[1].placeholder = "Prepare Lorenz96 locally with 20 ensemble members and DEnKF."
    panel.container.children += (W.HTML("<div class='cryostack-help'>After applying, continue in the Run settings below.</div>"),)
    return panel

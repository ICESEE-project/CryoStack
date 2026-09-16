"""Agent-Beta review over the host's manual configuration, with no run callback."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import html
import json
import ipywidgets as W

from cryostack_src.agents.intent import infer_request


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


def _messages(title, messages):
    if not messages:
        return ""
    # Validation is authoritative; only remove log prefixes for presentation.
    clean = [str(m).replace("[cloud][ERROR] ", "").replace("by the current workflow runtime", "for this experiment").replace("available example metadata", "available examples") for m in dict.fromkeys(messages)]
    return (f"<div style='margin-top:8px;font-weight:600'>{html.escape(title)}</div>"
            "<ul style='margin:4px 0;padding-left:18px;font-size:12px;line-height:1.45'>"
            + "".join(f"<li>{html.escape(m)}</li>" for m in clean) + "</ul>")


def build_configuration_agent(*, catalog, apply_values, snapshot, validate):
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
    full = W.HTML()
    details = W.Accordion(children=[full], selected_index=None, layout=W.Layout(display="none"))
    details.set_title(0, "Current configuration")
    state = {}

    def refresh_details(data):
        full.value = _configuration_table(data) + (
            "<details style='margin-top:8px'><summary class='cryostack-help'>Full configuration</summary>"
            "<pre style='font-size:11px;max-height:240px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere'>"
            + html.escape(json.dumps(snapshot(), indent=2, default=str)) + "</pre></details>")
        details.layout.display = ""
        details.selected_index = None

    def ask(text):
        if question.value != text:
            question.value = text
        state.clear()
        apply.disabled = True
        apply.layout.display = "none"
        try:
            data = catalog()
            proposal = infer_request(text, data)
            state.update(text=text, catalog=copy.deepcopy(data), snapshot=copy.deepcopy(snapshot()), proposal=proposal)
            if proposal.applicable:
                result.value = ("<div class='cryostack-group-title' style='margin:8px 0 4px'>Proposed configuration</div>"
                                + _configuration_table(data, proposal.values, proposal.retained)
                                + "<div class='cryostack-help' style='margin-top:6px'>Other settings stay as currently configured.</div>"
                                + "<div style='margin-top:8px;font-size:12px;font-weight:600'>Ready to apply</div>")
                apply.layout.display = ""
                apply.disabled = False
            else:
                unsupported = [m for m in proposal.errors if "not supported" in m or "not available" in m]
                invalid = [m for m in proposal.errors if m not in unsupported]
                result.value = (_messages("Unsupported request", unsupported)
                                + _messages("Invalid settings", invalid)
                                + _messages("Please clarify", proposal.unresolved))
            refresh_details(data)
            return proposal
        except Exception:
            state.clear()
            details.layout.display = "none"
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
            fresh = infer_request(state["text"], data)
            if not fresh.applicable or fresh.values != proposal.values:
                raise ValueError("The proposal changed. Create a new plan before applying.")
            apply.disabled = True
            apply.layout.display = "none"
            state.clear()
            apply_values(copy.deepcopy(fresh.values))
            findings = validate()
            data = catalog()
            refresh_details(data)
            result.value = ("<div class='cryostack-group-title' style='margin-top:8px'>Configuration updated</div>"
                            "<div class='cryostack-help'>Continue with the normal configuration and review controls. Nothing has run.</div>"
                            + _messages("Before execution", findings))
            return findings
        except Exception as exc:
            apply.disabled = True
            apply.layout.display = "none"
            state.clear()
            result.value = _messages("Review needed", [str(exc), "No run was started. Check the current controls before continuing."])
            refresh_details(catalog())
            return None

    def request_changed(_):
        state.clear()
        apply.disabled = True
        apply.layout.display = "none"
        result.value = "<div class='cryostack-help'>Request changed. Create a plan to review the new settings.</div>" if question.value.strip() else ""
        details.selected_index = None

    def current_opened(change):
        if change["new"] == 0:
            # A review snapshot must follow manual edits; it never writes back.
            data = catalog()
            full.value = _configuration_table(data) + (
                "<details><summary class='cryostack-help'>Full configuration</summary><pre style='font-size:11px;max-height:240px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere'>"
                + html.escape(json.dumps(snapshot(), indent=2, default=str)) + "</pre></details>")

    create.on_click(lambda _: ask(question.value))
    apply.on_click(lambda _: apply_plan())
    question.observe(request_changed, names="value")
    details.observe(current_opened, names="selected_index")
    return ConfigurationAgent(W.VBox([header, question, create, result, apply, details],
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
    for name, label in (("user", "HPC username"), ("directory", "remote working directory")):
        if not fields[name].value.strip():
            errors.append(f"Enter your {label} in the remote connection controls.")
    errors.append("Remote identity and backend readiness must be verified before execution.")
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
        return dict(application="icesheets", examples=examples,
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

    panel = build_configuration_agent(catalog=catalog, apply_values=apply_values,
                                      snapshot=full_snapshot, validate=validate)
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
        return dict(application="icesee", examples=examples, profiles=list(COMPUTE_PROFILES),
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

    panel = build_configuration_agent(catalog=catalog, apply_values=apply_values,
                                      snapshot=snapshot, validate=validate)
    panel.container.children[1].placeholder = "Prepare Lorenz96 locally with 20 ensemble members and DEnKF."
    panel.container.children += (W.HTML("<div class='cryostack-help'>After applying, continue in the Run settings below.</div>"),)
    return panel

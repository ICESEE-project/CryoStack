"""Metadata-driven, inert configuration proposals. No execution or approval API."""
from __future__ import annotations

from dataclasses import dataclass, field
import re


def normalized(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def mentioned(text, value):
    value = normalized(value)
    return bool(value) and f" {value} " in f" {normalized(text)} "


@dataclass
class Proposal:
    values: dict = field(default_factory=dict)
    inferred: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    retained: list[str] = field(default_factory=list)

    @property
    def applicable(self):
        return bool(self.values) and not self.errors and not self.unresolved


def infer_request(text, catalog):
    """Resolve names from supplied metadata; never invent a model/example/default.

    catalog contains application, examples, modes, profiles, current, parameters.
    Values are a delta over the host's current configuration, not an executable plan.
    """
    p = Proposal()
    if not text.strip():
        p.unresolved.append("Describe the experiment you want to prepare.")
        return p
    recognized = []
    examples = catalog["examples"]
    models = sorted({e["model"] for e in examples})
    model_hits = [m for m in models if mentioned(text, m)]
    hits = [e for e in examples if any(mentioned(text, a) for a in e["aliases"])]
    # A model-only label must not outweigh a specifically named example.
    specific = [e for e in hits if any(mentioned(text, a) and normalized(a) not in models
                                     for a in e["aliases"])]
    hits = specific or hits
    if len(model_hits) > 1:
        p.unresolved.append("Choose one forecast model and example; combined workflows need manual configuration.")
    if len(hits) > 1:
        p.unresolved.append("Choose an example: " + ", ".join(e["label"] for e in hits))
    chosen = hits[0] if len(hits) == 1 else None
    if chosen and model_hits and chosen["model"] not in model_hits:
        p.errors.append(f"{chosen['label']} uses {chosen['model']}; it does not match the requested model.")
    if chosen is None and not hits and len(model_hits) <= 1:
        current_example = next((e for e in examples if e["id"] == catalog["current"].get("example")), None)
        if current_example and (not model_hits or current_example["model"] == model_hits[0]):
            chosen = current_example
            p.retained.append("example")
            if not model_hits:
                p.retained.append("model")
    if chosen is None and len(model_hits) == 1:
        candidates = [e for e in examples if e["model"] == model_hits[0]]
        if len(candidates) == 1:
            chosen = candidates[0]
        elif re.search(r"\bdefault\w*\b", text, re.I):
            chosen = next((e for e in candidates if e["id"] == catalog["current"].get("example")), None)
        if chosen is None and not hits:
            p.unresolved.append("Choose a supported example: " + ", ".join(e["label"] for e in candidates[:12]))
    if chosen is None and not p.unresolved:
        p.unresolved.append("Name a supported model and example. Available: " + ", ".join(e["label"] for e in examples[:12]))
    if chosen:
        recognized.extend(a for a in chosen["aliases"] if mentioned(text, a))
        p.values.update(model=chosen["model"], example=chosen["id"])
        p.inferred.append(f"{chosen['label']} — {chosen['model']}" +
                          (" forecast model" if catalog["application"] == "icesee" else ""))
    modes = []
    for mode, pattern in (("local", r"\b(local\w*|laptop|this computer)\b"),
                          ("remote", r"\b(remote\w*|hpc|slurm|cluster)\b"),
                          ("cloud", r"\b(cloud|aws|batch|fargate|ec2)\b")):
        if re.search(pattern, text, re.I):
            modes.append(mode)
    profiles = [name for name in catalog["profiles"] if mentioned(text, name)]
    if profiles and "remote" not in modes:
        modes.append("remote")
    if len(modes) > 1:
        p.unresolved.append("Choose one execution location: " + ", ".join(modes))
    mode = modes[0] if len(modes) == 1 else catalog["current"].get("mode")
    allowed_modes = chosen.get("modes", catalog["modes"]) if chosen else catalog["modes"]
    if mode not in allowed_modes:
        p.errors.append(f"{mode} execution is not available in this application. Supported: " + ", ".join(allowed_modes))
    elif modes:
        p.values["mode"] = mode
        p.inferred.append(f"Execution: {mode}")
    if len(profiles) > 1:
        p.unresolved.append("Choose one compute profile: " + ", ".join(profiles))
    elif profiles:
        p.values["profile"] = profiles[0]
    for name in catalog.get("backends", []):
        if mentioned(text, name):
            if "backend" in p.values:
                p.unresolved.append("Choose one software backend.")
            p.values["backend"] = name
    if re.search(r"\b(gpu\w*|cuda)\b", text, re.I):
        from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities
        cap = resolve_workflow_capabilities(model=("icesee" if catalog["application"] == "icesee" else p.values.get("model", "")), forecast_model=p.values.get("model", ""))
        if not cap.supports_gpu:
            p.errors.append("GPU execution is not supported by the current workflow runtime.")
        else:
            p.unresolved.append("Configure the GPU resources manually before review.")
    patterns = {
        "cpus": r"(?<![-\w.])(\d+)\s*(?:cpus?|cores?|processors?|processes|tasks?)\b(?!\s*per\s*node)",
        "nodes": r"(?<![-\w.])(\d+)\s*nodes?\b",
        "tasks_per_node": r"\b(\d+)\s*(?:tasks?|processes)\s*per\s*node\b",
        "ensemble_size": r"\b(?:ensemble(?: size)?\s*(?:of|=|:)?\s*)(\d+)\b|\b(\d+)\s*(?:ensemble members|members)\b",
    }
    for key, pattern in patterns.items():
        matches = list(re.finditer(pattern, text, re.I))
        recognized.extend(m[0] for m in matches)
        vals = {int(next(g for g in m.groups() if g is not None)) for m in matches}
        if len(vals) > 1:
            p.unresolved.append(f"Conflicting values for {key.replace('_', ' ')}.")
        elif vals:
            value = vals.pop()
            if value < 1:
                p.errors.append(f"{key.replace('_', ' ')} must be positive.")
            elif key == "ensemble_size" and catalog["application"] != "icesee":
                p.errors.append("Ensemble assimilation belongs in the ICESEE application.")
            elif mode == "cloud" and key in ("cpus", "nodes", "tasks_per_node"):
                if key == "nodes" and value > 1:
                    from cryostack_src.models.workflow_capabilities import resolve_workflow_capabilities
                    cap = resolve_workflow_capabilities(model=catalog["application"], forecast_model=p.values.get("model", ""))
                    if not cap.supports_multinode:
                        p.errors.append("Multi-node cloud execution is not supported by the current runtime.")
                p.unresolved.append("Cloud CPU and node requests must be reviewed against the application's cloud resource configuration; no HPC value will be substituted.")
            elif mode == "local" and key != "ensemble_size":
                p.unresolved.append("This local workflow has no exposed CPU/node control; configure its runtime manually.")
            else:
                p.values[key] = value
    if "cpus" in p.values and "tasks_per_node" not in p.values:
        nodes = p.values.get("nodes", catalog["current"].get("nodes", 1))
        if p.values["cpus"] % nodes:
            p.unresolved.append("Specify tasks per node; the CPU count does not divide evenly across the selected nodes.")
        else:
            p.values["tasks_per_node"] = p.values["cpus"] // nodes
    for key, pattern in (("account", r"\b(?:account|allocation)\s*[=:]?\s*([\w-]+)"),
                         ("wall_time", r"\b(?:wall(?:[ -]?time)?|time limit)\s*[=:]?\s*(\d+:\d{2}:\d{2})"),
                         ("memory", r"\b(\d+(?:\.\d+)?\s*[GM]B?)\s*(?:memory|ram)\b")):
        match = re.search(pattern, text, re.I)
        if match:
            recognized.append(match[0])
            if mode != "remote":
                p.unresolved.append(f"Set {key.replace('_', ' ')} in the selected execution environment.")
            else:
                p.values[key] = match[1].replace(" ", "").upper().removesuffix("B") if key == "memory" else match[1]
    # Scientific values are accepted only through metadata supplied by the host.
    params = chosen.get("parameters", catalog.get("parameters", {}).get(p.values.get("model"), [])) if chosen else []
    consumed = set()
    for spec in params:
        aliases = sorted(set([spec["key"], spec["label"], *spec.get("aliases", [])]), key=len, reverse=True)
        for alias in aliases:
            pattern = r"(?<![\w.])" + re.escape(alias).replace(r"\ ", r"[ _-]+") + r"\s*(?:=|:|of|to|is)?\s*([-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?|true|false|on|off)\b"
            match = re.search(pattern, text, re.I)
            if not match:
                continue
            recognized.append(match[0])
            raw = match[1].lower()
            try:
                value = {"true": True, "on": True, "false": False, "off": False}[raw] if raw in ("true", "false", "on", "off") else float(raw)
                if spec["kind"] == "int":
                    if isinstance(value, bool) or not float(value).is_integer():
                        raise ValueError()
                    value = int(value)
                if spec["kind"] == "bool" and not isinstance(value, bool):
                    raise ValueError()
                if spec.get("min") is not None and value < spec["min"] or spec.get("max") is not None and value > spec["max"]:
                    raise ValueError()
                p.values.setdefault("parameters", {})[spec["key"]] = value
                consumed.add(normalized(alias))
            except (ValueError, TypeError):
                p.errors.append(f"Invalid value for {spec['label']}; use the range shown in manual configuration.")
            break
    for match in re.finditer(r"\b([a-zA-Z_][\w.]*)\s*=\s*([^\s,;]+)", text):
        if normalized(match[1]) not in consumed and match[1] not in ("account", "allocation"):
            p.unresolved.append(f"Unrecognized setting {match[1]!r}. Use a supported configuration field.")
    filter_hits = [choice for choice in catalog.get("filters", []) if mentioned(text, choice)]
    if len(filter_hits) > 1:
        p.unresolved.append("Choose one assimilation filter.")
    for choice in catalog.get("filters", []):
        if mentioned(text, choice):
            p.values["filter"] = choice
    if re.search(r"\b(ec2|fargate|spot)\b", text, re.I):
        p.unresolved.append("Choose the requested cloud compute option in Advanced, then review its resource checks.")
    explicit_model = re.search(r"\b(?:forecast model|model)\s*(?:=|:)?\s+([a-zA-Z][\w-]*)", text, re.I)
    if explicit_model and normalized(explicit_model[1]) not in {normalized(m) for m in models}:
        p.unresolved.append("The named model could not be matched to the available example metadata.")
    remaining = text
    for fragment in sorted(recognized, key=len, reverse=True):
        remaining = re.sub(re.escape(fragment), " ", remaining, flags=re.I)
    if re.search(r"\d", remaining):
        p.unresolved.append("Some numbers or settings were not understood: " + remaining.strip() + ". Use the exact configuration label and a value.")
    for name in [*models, *catalog["profiles"], *catalog.get("backends", []), *catalog.get("filters", [])]:
        remaining = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", remaining, flags=re.I)
    # A bounded grammar must expose unhandled scientific intent, not silently
    # drop it after successfully recognizing just the example name.
    grammar_words = set("run prepare set up configure create plan an a the experiment simulation example tutorial with using use on in at for and please default defaults configuration settings locally local remote remotely hpc slurm cluster cloud aws batch fargate ec2 spot gpu gpus cuda laptop this computer forecast model icesee cryolauncher ensemble data assimilation execution cpu cpus core cores task tasks nodes node processor processors processes memory ram k kelvin".split())
    unknown = sorted(set(normalized(remaining).split()) - grammar_words)
    if unknown:
        p.unresolved.append("Could not interpret these parts of the request: " + ", ".join(unknown) + ". Use the available example and configuration labels.")
    # Never silently interpret negation, alternatives, or an arbitrary script.
    if re.search(r"\b(?:instead of|not|without|either|or)\b|[;`]|\$\(", text, re.I):
        p.unresolved.append("This description contains alternatives, exclusions, or commands. State one experiment with explicit settings.")
    if re.search(r"-\d+\s*(?:cpus?|cores?|nodes?|tasks?)\b", text, re.I):
        p.errors.append("CPU, task and node counts must be positive integers.")
    if catalog["application"] == "icesee" and "cpus" in p.values:
        p.values["parallel_processes"] = p.values["cpus"]
    p.inferred.extend(f"{k.replace('_', ' ')}: {v}" for k, v in p.values.items() if k not in ("model", "example", "mode"))
    return p

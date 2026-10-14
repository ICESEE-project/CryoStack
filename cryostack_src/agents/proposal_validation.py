"""Pure proposal checks over host metadata; execution readiness stays in Review."""
import math


def proposal_findings(proposal, data):
    values = proposal.values
    current = data["current"]
    merged = dict(current, **values)
    errors = []
    example = next((e for e in data["examples"] if e["id"] == merged.get("example")), None)
    if example is None or merged.get("model") != example["model"]:
        return ["Select a supported, matching model and example."]
    modes = set(data["modes"]) & set(example.get("modes", data["modes"]))
    if merged.get("mode") not in modes:
        errors.append("The selected execution location is not supported for this example.")
    for key, choices in (("profile", data.get("profiles")), ("backend", data.get("backends")),
                         ("filter", data.get("filters"))):
        if key in values and choices is not None and values[key] not in choices:
            errors.append(f"Choose a supported {key.replace('_', ' ')}.")
    for key, bounds in data.get("control_bounds", {}).items():
        if key not in values:
            continue
        value = values[key]
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or value < bounds[0] or value > bounds[1]):
            errors.append(f"{key.replace('_', ' ')} is outside the manual control's supported range.")
    specs = {p["key"]: p for p in example.get("parameters", data.get("parameters", {}).get(example["model"], []))}
    for key, value in values.get("parameters", {}).items():
        spec = specs.get(key)
        if spec is None:
            errors.append("A requested scientific setting is not supported for this example.")
            continue
        kind = spec["kind"]
        valid = isinstance(value, bool) if kind == "bool" else (
            not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value))
        if valid and kind == "int":
            valid = float(value).is_integer()
        if valid:
            valid = ((spec.get("min") is None or value >= spec["min"])
                     and (spec.get("max") is None or value <= spec["max"]))
        if not valid:
            errors.append(f"Invalid value for {spec['label']}; use the range shown in manual configuration.")
    # Reuse the model validators, including solver-specific rules, without
    # changing widgets. The host supplies solver metadata only for real examples.
    overrides = dict(current.get("overrides", {}), **values.get("parameters", {}))
    if data.get("validate_scientific") and overrides:
        if example["model"] == "issm":
            from cryostack_src.models.issm.md_config import validate_md_config
            errors.extend(validate_md_config(overrides, solvers=example.get("solvers", ())).errors)
        elif example["model"] == "icepack":
            from cryostack_src.models.icepack.parameters import validate_icepack_config
            errors.extend(validate_icepack_config(overrides)["errors"])
    # Check new scheduler conflicts, not unrelated incomplete identity/readiness.
    if merged.get("mode") == "remote" and data.get("validate_resources"):
        from cryostack_src.resources.profiles import get_compute_profile
        from icesee_jupyter_book.ui.shared_validation import validate_slurm_resources
        def findings(settings):
            profile = get_compute_profile(settings.get("profile"))
            return validate_slurm_resources(nodes=settings.get("nodes"), tasks=settings.get("cpus"),
                tasks_per_node=settings.get("tasks_per_node"), wall_time=settings.get("wall_time", ""),
                memory=settings.get("memory", ""), account=settings.get("account", ""),
                account_required=profile.account_required)
        baseline = findings(current)
        errors.extend(e for e in findings(merged) if e not in baseline)
    return list(dict.fromkeys(errors))

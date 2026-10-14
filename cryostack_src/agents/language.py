"""Bounded lexical rewrites into existing configuration slots; no execution."""
import math
import re
from decimal import Decimal, InvalidOperation

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?"
COUNT_NAMES = {
    "cpus": r"(?:cpus?|cores?|processors?|processes|tasks?)",
    "nodes": r"nodes?",
    "tasks_per_node": r"(?:tasks?|processes) per node",
    "ensemble_size": r"ensemble(?: size| members)?",
}
COUNT_LABELS = dict(cpus="CPUs", nodes="nodes", tasks_per_node="tasks per node", ensemble_size="ensemble members")


def contextual_request(text, catalog, proposal):
    """Resolve explicit relative operations from current controls, never history."""
    constraints = set()
    current = catalog["current"]
    text = text.replace("’", "'")
    for pattern, constraint in (
        (r"\bkeep (?:my |the )?current model\b", "model"),
        (r"\bkeep (?:my |the )?current solver\b", "solver"),
        (r"\b(?:without changing|keep) (?:my |the )?scientific parameters\b", "science"),
        (r"\bkeep (?:the )?rest of (?:my |the )?configuration\b", "rest"),
        (r"\bkeep everything else\b", "rest"),
    ):
        if re.search(pattern, text, re.I):
            constraints.add(constraint)
            text = re.sub(pattern, " ", text, flags=re.I)
    # A mode replacement is not a request for both locations. Verify its premise.
    def switch(match):
        old, new = match.group(1).lower(), match.group(2).lower()
        if current.get("mode") != old:
            proposal.unresolved.append(f"The current execution location is not {old}. Confirm the intended change.")
        return new + " execution"
    text = re.sub(r"\bswitch from (local|remote|cloud) to (local|remote|cloud)(?: execution)?\b", switch, text, flags=re.I)
    text = re.sub(r"\b(?:use )?(?:the )?same configuration(?: but)?\b", "use", text, flags=re.I)
    words = {"one": "1", "two": "2", "three": "3", "four": "4"}
    text = re.sub(r"\b(one|two|three|four)(?=\s+nodes?\b)", lambda m: words[m[1].lower()], text, flags=re.I)
    for key in ("tasks_per_node", "ensemble_size", "cpus", "nodes"):
        alias = COUNT_NAMES[key]
        # Long phrases first, so 'tasks per node' never becomes a total-task count.
        label = COUNT_LABELS[key]
        def relative(match):
            value = current.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 1 or not float(value).is_integer():
                proposal.unresolved.append(f"Set a valid current {label} value before doubling it.")
                return " "
            proposal.reasons[key] = f"You requested twice the current value ({value})."
            return f"{value * 2:g} {label}"
        text = re.sub(r"\bdouble (?:the )?(?:number of )?" + alias + r"\b", relative, text, flags=re.I)
        def change(match):
            old, new = float(match[1]), float(match[2])
            if current.get(key) != old:
                proposal.unresolved.append(f"The stated previous {label} value does not match the current controls.")
            if match[0].lower().startswith("increase") and new <= old or match[0].lower().startswith("decrease") and new >= old:
                proposal.unresolved.append(f"The requested direction conflicts with the new {label} value.")
            return f"{new:g} {label}"
        text = re.sub(r"\b(?:increase|decrease|change|set) (?:the )?" + alias + r" from (" + NUMBER + r") to (" + NUMBER + r")\b", change, text, flags=re.I)
        def assign(match):
            target, baseline = float(match[1]), current.get(key)
            if isinstance(baseline, (int, float)) and not isinstance(baseline, bool):
                if match[0].lower().startswith("increase") and target <= baseline or match[0].lower().startswith("decrease") and target >= baseline:
                    proposal.unresolved.append(f"The requested direction conflicts with the new {label} value.")
            return f"{match[1]} {label}"
        text = re.sub(r"\b(?:increase|decrease|change|set) (?:the )?" + alias + r" to (" + NUMBER + r")\b", assign, text, flags=re.I)
    # Default values must be supplied by the host's registered metadata.
    for key, alias in {**COUNT_NAMES, "wall_time": r"(?:wall[ -]?time|time limit)"}.items():
        def reset(_match):
            value = catalog.get("defaults", {}).get(key)
            if value is None or value == "":
                proposal.unresolved.append(f"No registered default is available for {key.replace('_', ' ')}. Specify a value.")
                return " "
            proposal.suggested.append(key)
            proposal.reasons[key] = "You requested the default supplied by the selected resource."
            return f"walltime {value}" if key == "wall_time" else f"{value} {COUNT_LABELS[key]}"
        text = re.sub(r"\breset (?:the )?" + alias + r" to (?:the )?default\b", reset, text, flags=re.I)
    return text, constraints


def duration_request(text, proposal):
    """Normalize explicit durations to scheduler HH:MM:SS (no unit guessing)."""
    def duration(match):
        try:
            seconds = Decimal(match[1]) * (3600 if match[2].lower().startswith('hour') else 60)
            if not seconds.is_finite() or seconds <= 0 or seconds != seconds.to_integral_value() or seconds > 10**9:
                raise ValueError()
            seconds = int(seconds)
            return f"walltime {seconds // 3600:02}:{seconds % 3600 // 60:02}:{seconds % 60:02}"
        except (ValueError, InvalidOperation):
            proposal.errors.append("Use a positive duration expressed in whole seconds.")
            return " "
    return re.sub(r"(?<![\w.])(?:(?:wall[ -]?time|time limit)\s*(?:to|=|:)?\s*)?(" + NUMBER + r")\s*(hours?|minutes?)\b", duration, text, flags=re.I)


def scientific_assignments(text, specs, current, proposal):
    """Extract bounded scalar assignments and detect alias/value conflicts."""
    recognized, consumed = [], set()
    matches = []
    for spec in specs:
        for alias in sorted(set([spec['key'], spec['label'], *spec.get('aliases', [])]), key=len, reverse=True):
            name = re.escape(alias).replace(r'\ ', r'[ _-]+')
            value = r'(' + NUMBER + r'|true|false|on|off)'
            pattern = (r'(?<![\w.])(?:(?:set|increase|decrease|change)\s+(?:the\s+)?)?' + name
                       + r'\s*(?:from\s+' + value + r'\s+to\s+|(?:=|:|of|to|is)?\s*)' + value + r'\b')
            for match in re.finditer(pattern, text, re.I):
                matches.append((match, spec, alias))
    # Prefer the longest match at a position, retaining genuine alias ambiguity.
    selected = []
    for match, spec, alias in sorted(matches, key=lambda item: (item[0].start(), -len(item[0][0]))):
        if any(m.start() <= match.start() and m.end() >= match.end() and m.span() != match.span() for m, _, _ in selected):
            continue
        selected.append((match, spec, alias))
    owners = {}
    values = {}
    def scalar(raw):
        return {'true': True, 'false': False, 'on': True, 'off': False}[raw.lower()] if raw.lower() in ('true','false','on','off') else float(raw)
    for match, spec, alias in selected:
        owners.setdefault(match.span(), set()).add(spec['key'])
        recognized.append(match[0]); consumed.add(alias)
        try:
            old, raw = match.groups()
            value = scalar(raw)
            baseline = current.get(spec['key'])
            if old is not None and baseline != scalar(old):
                proposal.unresolved.append(f"The stated previous value for {spec['label']} is not confirmed by the current controls.")
            if isinstance(baseline, (int, float)) and not isinstance(baseline, bool) and not isinstance(value, bool):
                if match[0].lower().startswith("increase") and value <= baseline or match[0].lower().startswith("decrease") and value >= baseline:
                    proposal.unresolved.append(f"The requested direction conflicts with the new {spec['label']} value.")
            if spec['kind'] == 'bool':
                valid = isinstance(value, bool)
            else:
                valid = not isinstance(value, bool) and math.isfinite(value)
                if valid and spec['kind'] == 'int':
                    valid = value.is_integer()
                    if valid: value = int(value)
            if valid:
                valid = (spec.get('min') is None or value >= spec['min']) and (spec.get('max') is None or value <= spec['max'])
            if not valid: raise ValueError()
            values.setdefault(spec['key'], []).append(value)
        except (TypeError, ValueError, OverflowError):
            proposal.errors.append(f"Invalid value for {spec['label']}; use the range shown in manual configuration.")
    for keys in owners.values():
        if len(keys) > 1:
            proposal.unresolved.append("Ambiguous parameter label; use one exact name: " + ', '.join(sorted(keys)))
    for key, candidates in values.items():
        if len(set(candidates)) != 1:
            proposal.unresolved.append(f"Conflicting values for {key}.")
        else:
            proposal.values.setdefault('parameters', {})[key] = candidates[0]
    return recognized, consumed

"""Icepack Basic-mode parameter architecture.

This is **not** a translation of ISSM's ``md`` controls. Icepack examples are
Firedrake/Python: the canonical scientific knobs are cell-level assignments like
``T = firedrake.Constant(255.15)`` in the upstream tutorial notebooks
(``<ICEPACK_ROOT>/notebooks/tutorials/*.ipynb``). There is no ``params.yaml`` /
solver-argument convention to hook into.

Every candidate parameter is CLASSIFIED (:data:`CATEGORY_*`). Only
``safe_basic`` parameters are exposed for Basic-mode override, and only where a
canonical assignment can be located and replaced *in the per-run working copy*
by an exact, single-match regex substitution -- so:

* the canonical example is never modified (staging copies it first);
* a default run reproduces the canonical example byte-for-byte;
* an example that does not expose the parameter fails **before submission**
  (``IcepackOverrideError``) rather than running with a silently-ignored value;
* provenance records exactly which line changed from what to what.

Evidence for each parameter (the notebooks it appears in, the exact assignment
form) is recorded on the :class:`IcepackParameter` so the classification is
auditable. See ``overnight/AUDIT_icepack_parity.md`` and the tests.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

# ── classification ────────────────────────────────────────────────────
CATEGORY_SAFE = "safe_basic"          #: a scalar, physically bounded, example-independent meaning
CATEGORY_ADVANCED = "advanced_only"   #: meaningful but stability-coupled or example-dependent name
CATEGORY_DERIVED = "derived"          #: computed from another parameter (e.g. A = rate_factor(T))
CATEGORY_UNSAFE = "unsafe_generic"    #: a spatial field / custom constitutive law, not a scalar
CATEGORY_UNKNOWN = "owner_decision"   #: insufficient repository evidence to classify

_ALL_CATEGORIES = (
    CATEGORY_SAFE, CATEGORY_ADVANCED, CATEGORY_DERIVED, CATEGORY_UNSAFE, CATEGORY_UNKNOWN,
)


class IcepackParameterError(ValueError):
    """An override value is invalid (type / bounds / unknown key)."""


class IcepackOverrideError(RuntimeError):
    """A requested Basic-mode override could not be applied to this example
    (the canonical assignment was not found exactly once). Raised *before*
    submission -- the run never starts with an ignored override."""


@dataclass(frozen=True)
class IcepackParameter:
    name: str                    # CryoStack override key -- never an ISSM name
    label: str
    category: str
    kind: str                    # "float" | "int"
    units: str | None
    source_variable: str         # the notebook variable this maps to
    rationale: str
    minimum: float | None = None
    maximum: float | None = None
    #: regex (MULTILINE) that matches the canonical assignment line; group
    #: "indent" is preserved, group "value" is the number to replace. Only set
    #: for ``safe_basic`` parameters.
    assignment_pattern: str | None = None
    #: tutorial notebooks (by stem) where this assignment form was observed
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def compiled(self) -> re.Pattern | None:
        return re.compile(self.assignment_pattern, re.MULTILINE) if self.assignment_pattern else None


# ── the curated set ───────────────────────────────────────────────────
# Only entries with an assignment_pattern are Basic-mode-overridable. The rest
# are catalogued for transparency / the UI's "advanced" and "not exposed" notes.
CURATED_ICEPACK_PARAMETERS: tuple[IcepackParameter, ...] = (
    IcepackParameter(
        name="ice_temperature",
        label="Ice temperature",
        category=CATEGORY_SAFE,
        kind="float",
        units="K",
        source_variable="T",
        minimum=200.0,
        maximum=273.15,
        rationale=(
            "Every flow tutorial sets a single depth-averaged ice temperature "
            "T = Constant(<K>) and derives the fluidity A = icepack.rate_factor(T). "
            "It is a scalar with an unambiguous physical meaning and hard "
            "thermodynamic bounds (200 K .. the pressure-melting point)."
        ),
        assignment_pattern=(
            r"^(?P<indent>[ \t]*)T\s*=\s*(?:firedrake\.)?Constant\(\s*"
            r"(?P<value>[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*\)\s*$"
        ),
        evidence=("01-synthetic-ice-sheet", "02-synthetic-ice-shelf",
                  "04-synthetic-ice-stream-xy"),
    ),
    IcepackParameter(
        name="num_timesteps",
        label="Number of timesteps",
        category=CATEGORY_SAFE,
        kind="int",
        units=None,
        source_variable="num_timesteps",
        minimum=1,
        maximum=100000,
        rationale=(
            "Where an example uses a literal `num_timesteps = <int>` (01, 02) "
            "this only sets the length of the time loop -- it does not change "
            "the physics or the timestep size. Examples that derive the step "
            "count differently (e.g. num_years * timesteps_per_year in 04) do "
            "not match the pattern and the override is rejected pre-submission."
        ),
        assignment_pattern=r"^(?P<indent>[ \t]*)num_timesteps\s*=\s*(?P<value>[0-9]+)\s*$",
        evidence=("01-synthetic-ice-sheet", "02-synthetic-ice-shelf"),
    ),
    # ---- catalogued, NOT Basic-mode overridable -------------------------
    IcepackParameter(
        name="fluidity_A", label="Ice fluidity (A)", category=CATEGORY_DERIVED,
        kind="float", units="MPa^-3 a^-1", source_variable="A",
        rationale="A = icepack.rate_factor(T); overriding it directly would "
                  "desynchronise it from the ice temperature. Expose T instead.",
    ),
    IcepackParameter(
        name="accumulation", label="Accumulation rate", category=CATEGORY_UNSAFE,
        kind="float", units="m/a", source_variable="a",
        rationale="In the tutorials `a` is variously a Constant, a spatial "
                  "expression (a_in + delta_a * x/Lx), or a mass-balance "
                  "function. There is no single scalar to override generically.",
    ),
    IcepackParameter(
        name="friction_C", label="Basal friction coefficient (C)", category=CATEGORY_UNSAFE,
        kind="float", units="MPa m^-1/m a^1/m", source_variable="C",
        rationale="`C` is a spatial Function built from a custom sliding law "
                  "(Weertman / Schoof) per example; not a generic scalar.",
    ),
    IcepackParameter(
        name="timestep_size", label="Timestep size (dt)", category=CATEGORY_ADVANCED,
        kind="float", units="a", source_variable="dt",
        rationale="Directly affects numerical stability of the prognostic "
                  "solve; unsafe to expose without a per-example CFL check.",
    ),
    IcepackParameter(
        name="mesh_resolution", label="Mesh resolution", category=CATEGORY_UNKNOWN,
        kind="float", units="m", source_variable="(varies: delta_x / nx,ny / .msh)",
        rationale="Mesh generation differs per example (gmsh script vs "
                  "RectangleMesh vs a shipped .msh). Changing it safely needs "
                  "an owner decision on how CryoStack curates Icepack meshes.",
    ),
)

BASIC_MODE_PARAMETERS: tuple[IcepackParameter, ...] = tuple(
    p for p in CURATED_ICEPACK_PARAMETERS
    if p.category == CATEGORY_SAFE and p.assignment_pattern
)

_BY_NAME = {p.name: p for p in CURATED_ICEPACK_PARAMETERS}


def parameter(name: str) -> IcepackParameter:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise IcepackParameterError(f"unknown Icepack parameter: {name!r}") from None


def classify(name: str) -> str:
    return parameter(name).category


# ── validation (before submission) ───────────────────────────────────
def validate_icepack_config(overrides: dict | None) -> dict:
    """Type + bounds check a Basic-mode override dict. Returns
    ``{"ok": bool, "errors": [...], "normalized": {name: value}}``. Never
    raises. Unknown keys and non-``safe_basic`` keys are errors."""
    errors: list[str] = []
    normalized: dict[str, float | int] = {}
    for key, raw in (overrides or {}).items():
        spec = _BY_NAME.get(key)
        if spec is None:
            errors.append(f"{key}: not a recognised Icepack parameter")
            continue
        if spec.category != CATEGORY_SAFE or not spec.assignment_pattern:
            errors.append(
                f"{key}: not available for Basic-mode override ({spec.category})"
            )
            continue
        try:
            value: float | int = int(raw) if spec.kind == "int" else float(raw)
        except (TypeError, ValueError):
            errors.append(f"{key}: expected {spec.kind}, got {raw!r}")
            continue
        if not math.isfinite(value):
            errors.append(f"{key}: {raw!r} is not a finite number")
            continue
        if spec.minimum is not None and value < spec.minimum:
            errors.append(f"{key}: {value} below minimum {spec.minimum}")
            continue
        if spec.maximum is not None and value > spec.maximum:
            errors.append(f"{key}: {value} above maximum {spec.maximum}")
            continue
        normalized[key] = value
    return {"ok": not errors, "errors": errors, "normalized": normalized}


# ── applying overrides to the per-run working copy ───────────────────
def _format_value(spec: IcepackParameter, value) -> str:
    if spec.kind == "int":
        return str(int(value))
    v = float(value)
    return f"{v:.1f}" if v.is_integer() else repr(v)


def _sub_in_text(spec: IcepackParameter, value, text: str) -> tuple[str, str | None]:
    """Return (new_text, matched_line) or (text, None) if not found. Raises
    IcepackOverrideError on an ambiguous (>1) match."""
    pat = spec.compiled()
    matches = list(pat.finditer(text))
    if not matches:
        return text, None
    if len(matches) > 1:
        raise IcepackOverrideError(
            f"parameter {spec.name!r} ({spec.source_variable} =) is assigned "
            f"{len(matches)} times in this example; refusing to guess which to "
            "override"
        )
    m = matches[0]
    formatted = _format_value(spec, value)
    if spec.source_variable == "T":
        repl = f"{m.group('indent')}T = firedrake.Constant({formatted})  # CryoStack Basic-mode override"
    else:
        repl = f"{m.group('indent')}{spec.source_variable} = {formatted}  # CryoStack Basic-mode override"
    return text[:m.start()] + repl + text[m.end():], m.group(0)


def apply_overrides(source_text: str, overrides: dict, *, is_notebook: bool | None = None):
    """Apply validated Basic-mode overrides to an example's entrypoint source
    (a ``.ipynb`` JSON document or a ``.py`` script). Returns
    ``(new_source_text, provenance)`` where provenance is a list of
    ``{name, canonical, applied, location}``.

    Fail-closed: if a requested parameter's canonical assignment is not found
    exactly once, raises :class:`IcepackOverrideError` -- the caller must not
    submit the run.
    """
    result = validate_icepack_config(overrides)
    if not result["ok"]:
        raise IcepackParameterError("; ".join(result["errors"]))
    norm = result["normalized"]
    if not norm:
        return source_text, []

    if is_notebook is None:
        is_notebook = source_text.lstrip().startswith("{")

    provenance: list[dict] = []

    if is_notebook:
        nb = json.loads(source_text)
        code_cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        # aggregate ambiguity check across the whole notebook, not per cell
        for name in norm:
            spec = _BY_NAME[name]
            total = sum(len(spec.compiled().findall("".join(c.get("source", []))))
                        for c in code_cells)
            if total > 1:
                raise IcepackOverrideError(
                    f"parameter {name!r} ({spec.source_variable} =) is assigned "
                    f"{total} times in this example; refusing to guess which to "
                    "override"
                )
        remaining = dict(norm)
        for idx, cell in enumerate(nb.get("cells", [])):
            if cell.get("cell_type") != "code" or not remaining:
                continue
            cell_src = "".join(cell.get("source", []))
            changed = False
            for name in list(remaining):
                spec = _BY_NAME[name]
                new_src, matched = _sub_in_text(spec, remaining[name], cell_src)
                if matched is not None:
                    provenance.append({
                        "name": name, "canonical": matched.strip(),
                        "applied": remaining.pop(name),
                        "location": f"cell {idx}",
                    })
                    cell_src = new_src
                    changed = True
            if changed:
                cell["source"] = cell_src.splitlines(keepends=True)
        if remaining:
            raise IcepackOverrideError(
                "this example does not expose "
                + ", ".join(f"{n} ({_BY_NAME[n].source_variable} =)" for n in remaining)
                + " for Basic-mode override"
            )
        return json.dumps(nb, indent=1), provenance

    # plain .py
    text = source_text
    for name, value in norm.items():
        spec = _BY_NAME[name]
        text, matched = _sub_in_text(spec, value, text)
        if matched is None:
            raise IcepackOverrideError(
                f"this example does not expose {name} "
                f"({spec.source_variable} =) for Basic-mode override"
            )
        provenance.append({"name": name, "canonical": matched.strip(),
                           "applied": value, "location": "script"})
    return text, provenance


def entrypoint_transform_for(overrides: dict):
    """A ``str -> str`` callable for ``WorkspaceManager.stage_example_for_run``'s
    ``entrypoint_transform``. Applies :func:`apply_overrides`; discards the
    provenance (the caller records it separately from
    :func:`describe_overrides`)."""
    def _transform(text: str) -> str:
        return apply_overrides(text, overrides)[0]
    return _transform


def describe_overrides(source_text: str, overrides: dict) -> list[dict]:
    """The provenance :func:`apply_overrides` would record, without keeping the
    rewritten source. Use to populate the run manifest."""
    return apply_overrides(source_text, overrides)[1]

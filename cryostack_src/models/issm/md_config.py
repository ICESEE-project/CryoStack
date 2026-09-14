"""Basic-mode ISSM ``md`` configuration: a small curated, validated layer.

Basic mode is a *guided* configuration surface, never a raw MATLAB editor:

* only the parameters in :data:`CURATED_MD_PARAMETERS` can be touched;
* every value is range- and type-checked before submission
  (:func:`validate_md_config`);
* spatial fields are *transformed* (multiplied by a factor), never replaced by a
  scalar;
* a parameter is only offered when it is relevant to the solver(s) the selected
  example actually runs (:func:`detect_solvers`);
* the generated MATLAB (:func:`build_md_override_script`) is assembled from fixed
  templates with validated numeric/boolean values, so it is always syntactically
  valid and cannot carry an arbitrary expression;
* the override step is injected into a *user-owned working copy* of the example
  immediately before its first ``solve(...)`` (:func:`inject_override_step`) --
  the canonical example is never modified.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# ── solver detection ────────────────────────────────────────────────────────
# Mirrors the accepted strings in ISSM ``src/m/solve/solve.m`` (abbreviation
# and full name both map to the same normalised key). Keep this in lock-step
# with ISSM -- a name ISSM rejects must not appear here.
_SOLVER_ALIASES = {
    "sb": "stressbalance", "stressbalance": "stressbalance",
    "mt": "masstransport", "masstransport": "masstransport",
    "oceant": "oceantransport", "oceantransport": "oceantransport",
    "th": "thermal", "thermal": "thermal",
    "ss": "steadystate", "steadystate": "steadystate",
    "tr": "transient", "transient": "transient",
    "mc": "balancethickness", "balancethickness": "balancethickness",
    "balancethickness2": "balancethickness2",
    "mcsoft": "balancethicknesssoft", "balancethicknesssoft": "balancethicknesssoft",
    "bv": "balancevelocity", "balancevelocity": "balancevelocity",
    "bsl": "bedslope", "bedslope": "bedslope",
    "ssl": "surfaceslope", "surfaceslope": "surfaceslope",
    "hy": "hydrology", "hydrology": "hydrology",
    "da": "damageevolution", "damageevolution": "damageevolution",
    "gia": "gia",
    "lv": "love", "love": "love",
    "esa": "esa",
    "smp": "sampling", "sampling": "sampling",
}
_SOLVE_RE = re.compile(r"""solve\s*\(\s*[A-Za-z_]\w*\s*,\s*['"]([A-Za-z0-9]+)['"]""")


def detect_solvers(runme_text: str) -> tuple[str, ...]:
    """Normalised solver names invoked by an ISSM ``runme.m``, in first-seen order."""
    seen: list[str] = []
    for m in _SOLVE_RE.finditer(runme_text or ""):
        key = _SOLVER_ALIASES.get(m.group(1).strip().lower())
        if key and key not in seen:
            seen.append(key)
    return tuple(seen)


# ── curated parameter registry ─────────────────────────────────────────────
@dataclass(frozen=True)
class CuratedParam:
    key: str                       # e.g. "stressbalance.restol"
    label: str
    kind: str                      # "float" | "int" | "bool" | "multiplier" | "outputs"
    solvers: frozenset[str]        # detected solvers that make this relevant
    help: str = ""
    min: float | None = None
    max: float | None = None
    default: float | bool | None = None
    output_solver: str | None = None
    output_choices: tuple[str, ...] = ()

    def applies_to(self, solvers: Iterable[str]) -> bool:
        return bool(self.solvers.intersection(set(solvers or ())))


CURATED_MD_PARAMETERS: tuple[CuratedParam, ...] = (
    CuratedParam("stressbalance.restol", "Stressbalance residual tol", "float",
                 frozenset({"stressbalance", "transient"}),
                 help="Nonlinear stressbalance convergence (mechanical equilibrium residual).",
                 min=1e-10, max=1.0, default=1e-4),
    CuratedParam("stressbalance.reltol", "Stressbalance relative tol", "float",
                 frozenset({"stressbalance", "transient"}),
                 min=1e-10, max=1.0, default=1e-4),
    CuratedParam("stressbalance.abstol", "Stressbalance absolute tol", "float",
                 frozenset({"stressbalance", "transient"}),
                 help="Absolute velocity tolerance (m/yr). NaN in the example disables it.",
                 min=1e-10, max=1e6, default=1e-4),
    CuratedParam("stressbalance.maxiter", "Stressbalance max iterations", "int",
                 frozenset({"stressbalance", "transient"}),
                 min=1, max=1000, default=100),

    CuratedParam("timestepping.time_step", "Time step (yr)", "float",
                 frozenset({"transient"}),
                 help="Transient time step. Enable only to override the example value.",
                 min=1e-6, max=1e4, default=None),
    CuratedParam("timestepping.final_time", "Final time (yr)", "float",
                 frozenset({"transient"}),
                 min=1e-6, max=1e6, default=None),

    CuratedParam("transient.isstressbalance", "Transient: stress balance", "bool",
                 frozenset({"transient"})),
    CuratedParam("transient.ismasstransport", "Transient: mass transport", "bool",
                 frozenset({"transient"})),
    CuratedParam("transient.isthermal", "Transient: thermal", "bool",
                 frozenset({"transient"})),
    CuratedParam("transient.isgroundingline", "Transient: grounding line", "bool",
                 frozenset({"transient"})),
    CuratedParam("transient.ismovingfront", "Transient: moving front", "bool",
                 frozenset({"transient"})),
    CuratedParam("transient.issmb", "Transient: surface mass balance", "bool",
                 frozenset({"transient"})),

    CuratedParam("friction.coefficient", "Friction coefficient ×", "multiplier",
                 frozenset({"stressbalance", "transient"}),
                 help="Scale the whole friction-coefficient field by a factor.",
                 min=0.1, max=10.0, default=1.0),
    CuratedParam("materials.rheology_B", "Ice rigidity (rheology B) ×", "multiplier",
                 frozenset({"stressbalance", "transient", "thermal", "steadystate"}),
                 help="Scale the whole rheology-B field by a factor (softer < 1 < stiffer).",
                 min=0.5, max=2.0, default=1.0),

    CuratedParam("stressbalance.requested_outputs", "Extra stressbalance outputs", "outputs",
                 frozenset({"stressbalance"}), output_solver="stressbalance",
                 output_choices=(
                     "FrictionCoefficient", "MaterialsRheologyBbar",
                     "DeviatoricStressxx", "DeviatoricStressyy", "DeviatoricStressxy",
                     "StrainRatexx", "StrainRateyy", "StrainRatexy",
                 )),
    CuratedParam("transient.requested_outputs", "Extra transient outputs", "outputs",
                 frozenset({"transient"}), output_solver="transient",
                 output_choices=(
                     "IceVolume", "IceVolumeAboveFloatation", "GroundedArea",
                     "FloatingArea", "IceMass", "TotalSmb", "SmbMassBalance",
                 )),
)

_PARAM_BY_KEY: dict[str, CuratedParam] = {p.key: p for p in CURATED_MD_PARAMETERS}


def curated_parameters_for(solvers: Iterable[str]) -> tuple[CuratedParam, ...]:
    s = set(solvers or ())
    return tuple(p for p in CURATED_MD_PARAMETERS if p.applies_to(s))


# ── validation ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MdConfigValidation:
    ok: bool
    errors: tuple[str, ...] = ()
    normalized: dict = field(default_factory=dict)


def _as_number(raw) -> float:
    if isinstance(raw, bool):
        raise ValueError("expected a number")
    v = float(raw)
    if not math.isfinite(v):
        raise ValueError("must be a finite number (not NaN / Inf)")
    return v


def validate_md_config(overrides: dict, *, solvers: Iterable[str]) -> MdConfigValidation:
    """Type/range check curated overrides against the example's solver(s)."""
    s = set(solvers or ())
    errors: list[str] = []
    normalized: dict = {}

    for key, raw in (overrides or {}).items():
        param = _PARAM_BY_KEY.get(key)
        if param is None:
            errors.append(f"{key}: not a curated Basic-mode parameter")
            continue
        if not param.applies_to(s):
            errors.append(
                f"{param.label}: not applicable to this example "
                f"(solvers: {', '.join(sorted(s)) or 'none detected'})"
            )
            continue

        try:
            if param.kind in {"float", "multiplier"}:
                val = _as_number(raw)
                if param.min is not None and val < param.min:
                    raise ValueError(f"below minimum {param.min}")
                if param.max is not None and val > param.max:
                    raise ValueError(f"above maximum {param.max}")
                if param.kind == "multiplier" and val == 1.0:
                    continue  # no-op factor
                normalized[key] = val
            elif param.kind == "int":
                fv = _as_number(raw)
                if fv != int(fv):
                    raise ValueError("must be a whole number")
                val = int(fv)
                if param.min is not None and val < param.min:
                    raise ValueError(f"below minimum {int(param.min)}")
                if param.max is not None and val > param.max:
                    raise ValueError(f"above maximum {int(param.max)}")
                normalized[key] = val
            elif param.kind == "bool":
                if isinstance(raw, bool):
                    normalized[key] = raw
                elif str(raw).strip().lower() in {"1", "true", "on", "yes"}:
                    normalized[key] = True
                elif str(raw).strip().lower() in {"0", "false", "off", "no"}:
                    normalized[key] = False
                else:
                    raise ValueError("expected on/off")
            elif param.kind == "outputs":
                names = [str(n).strip() for n in (raw or []) if str(n).strip()]
                bad = [n for n in names if n not in param.output_choices]
                if bad:
                    raise ValueError(f"unknown output(s): {', '.join(bad)}")
                if names:
                    normalized[key] = sorted(set(names))
            else:  # pragma: no cover - registry guards this
                raise ValueError(f"unsupported kind {param.kind!r}")
        except (TypeError, ValueError) as err:
            errors.append(f"{param.label}: {err}")

    return MdConfigValidation(ok=not errors, errors=tuple(errors), normalized=normalized)


# ── MATLAB generation ──────────────────────────────────────────────────────
def _fmt_number(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return repr(float(value))  # e.g. "0.0001", "1e-10", "1.5" -- all valid MATLAB


def build_md_override_script(normalized: dict) -> str:
    """MATLAB applied to ``md`` right before the first ``solve(...)``.

    Every line comes from a fixed template with a validated value; there is no
    path for a user string to reach MATLAB verbatim.
    """
    lines = [
        "% ---------------------------------------------------------------",
        "% CryoStack Basic-mode md overrides  (auto-generated -- do not edit)",
        "% ---------------------------------------------------------------",
        "disp('[cryostack] applying validated Basic-mode md overrides');",
        "if ~exist('md','var'); error('[cryostack] md is not defined yet'); end",
    ]
    for key, value in (normalized or {}).items():
        param = _PARAM_BY_KEY[key]
        target = f"md.{key}"
        if param.kind in {"float", "int", "bool"}:
            v = _fmt_number(value)
            lines += [f"{target} = {v};",
                      f"disp('[cryostack]   set {target} = {v}');"]
        elif param.kind == "multiplier":
            v = _fmt_number(value)
            lines += [f"{target} = {target} .* {v};",
                      f"disp('[cryostack]   scaled {target} by {v}');"]
        elif param.kind == "outputs":
            cells = ", ".join(f"'{n}'" for n in value)  # names from a fixed whitelist
            lines += [
                f"if ~iscell({target}); {target} = {{'default'}}; end",
                f"{target} = unique([reshape({target}, 1, []), {{{cells}}}], 'stable');",
                f"disp('[cryostack]   added {param.output_solver} outputs: {' '.join(value)}');",
            ]
    return "\n".join(lines) + "\n"


# ── injection into the example entrypoint ──────────────────────────────────
OVERRIDE_SCRIPT_NAME = "cryostack_md_overrides.m"

_SOLVE_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?:[A-Za-z_]\w*\s*=\s*)?solve\s*\(", re.M
)


def inject_override_step(runme_text: str, *, script_name: str = OVERRIDE_SCRIPT_NAME) -> str:
    """Insert ``run('<script_name>');`` immediately before the first ``solve(...)``.

    Idempotent: a runme that already calls the override script is returned
    unchanged. When no ``solve(...)`` is present the call is appended (harmless).
    """
    text = runme_text or ""
    if script_name in text:
        return text
    call = f"run('{script_name}');"
    m = _SOLVE_LINE_RE.search(text)
    if m is None:
        return (text.rstrip("\n") + f"\n{call}\n") if text.strip() else f"{call}\n"
    line_start = text.rfind("\n", 0, m.start()) + 1
    indent = m.group("indent")
    return f"{text[:line_start]}{indent}{call}\n{text[line_start:]}"

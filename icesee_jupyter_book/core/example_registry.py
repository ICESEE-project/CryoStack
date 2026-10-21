# ============================================================
#  Example registry: every example ICESEE already couples, per application
# ============================================================

# icesee_jupyter_book/core/example_registry.py
"""ICESEE's examples, discovered from the ICESEE repository.

Each forecast-model application in ``ICESEE/applications/<app>_model/``
ships several examples under ``examples/<name>/``. An example is *coupled*
-- runnable by ICESEE -- when it has a ``params.yaml`` and the application's
data-assimilation driver ``run_da_<model>.py``; notebook-only folders are
not listed. Every coupled example is offered, keyed ``"<Application> ·
<example>"`` (e.g. ``"ISSM · ISMIP_Choi"``); a new example dropped into the
ICESEE repository appears without changing this file.

The keys used before discovery (``"ISSM (fully runable in Remote)"`` ...)
stay valid as aliases, so run records and saved configurations that name
them still resolve.
"""
from __future__ import annotations

from pathlib import Path

from .paths import EXT

#: application folder -> (display name, ICESEE model_name, driver script, default example)
APPLICATIONS = {
    "lorenz_model": ("Lorenz-96", "lorenz", "run_da_lorenz96.py", "lorenz96"),
    "issm_model": ("ISSM", "issm", "run_da_issm.py", "ISMIP_Choi"),
    "icepack_model": ("Icepack", "icepack", "run_da_icepack.py", "synthetic_ice_stream"),
    "flowline_model": ("Flowline", "flowline", "run_da_flowline.py", "flowline_1d"),
}
#: report each application's examples come with
_REPORT = {"issm": "read_results.m"}
#: the batch script Remote submissions of an application use, when the example has it
_REMOTE_SBATCH = {"issm": "run_job_spack.sbatch"}

LEGACY_KEYS = {
    "Lorenz-96 (fully runnable locally)": ("lorenz_model", "lorenz96"),
    "ISSM (fully runable in Remote)": ("issm_model", "ISMIP_Choi"),
    "Flowline (under development)": ("flowline_model", "flowline_1d"),
    "Icepack (under development)": ("icepack_model", "synthetic_ice_stream"),
    # the unlabelled keys a 2026-10-19 hotfix gave the same four examples
    "Lorenz-96": ("lorenz_model", "lorenz96"),
    "ISSM": ("issm_model", "ISMIP_Choi"),
    "Flowline": ("flowline_model", "flowline_1d"),
    "Icepack": ("icepack_model", "synthetic_ice_stream"),
}


def example_key(application: str, example: str) -> str:
    return f"{application} · {example}"


def _driver(base: Path, preferred: str) -> str | None:
    if (base / preferred).is_file():
        return preferred
    found = sorted(p.name for p in base.glob("run_da_*.py") if p.is_file())
    return found[0] if found else None


def discover(applications_root: Path | None = None) -> dict:
    """``{key: config}`` for every coupled example, applications in the order
    of :data:`APPLICATIONS`, each application's default example first."""
    root = Path(applications_root or EXT / "applications")
    out: dict = {}
    for folder, (label, model, driver, default) in APPLICATIONS.items():
        examples_dir = root / folder / "examples"
        if not examples_dir.is_dir():
            continue
        names = sorted((p.name for p in examples_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))),
                       key=lambda n: (n != default, n.lower()))
        for name in names:
            base = examples_dir / name
            script = _driver(base, driver)
            if script is None or not (base / "params.yaml").is_file():
                continue                       # not coupled to ICESEE (e.g. a notebook-only folder)
            sbatch = _REMOTE_SBATCH.get(model)
            out[example_key(label, name)] = dict(
                enabled=True,
                application=label,
                example=name,
                base=base,
                run_script=script,
                params="params.yaml",
                report_nb=_REPORT.get(model, "read_results.ipynb"),
                assets=["_modelrun_datasets"],
                model_name=model,
                figures_dir="figures",
                remote_rel=f"ICESEE/applications/{folder}/examples/{name}",
                remote_sbatch=sbatch if sbatch and (base / sbatch).is_file() else None,
                default=(name == default),
            )
    return out


class ExampleRegistry(dict):
    """The discovered examples; legacy keys resolve to their example."""

    def __init__(self, examples: dict):
        super().__init__(examples)
        self.aliases = {}
        for old, (folder, name) in LEGACY_KEYS.items():
            new = example_key(APPLICATIONS[folder][0], name)
            if new in self:
                self.aliases[old] = new

    def canonical(self, key):
        return self.aliases.get(key, key)

    def __getitem__(self, key):
        return super().__getitem__(self.canonical(key))

    def __contains__(self, key):
        return super().__contains__(self.canonical(key))

    def get(self, key, default=None):
        return super().get(self.canonical(key), default)


EXAMPLES = ExampleRegistry(discover())


def enabled_names() -> list[str]:
    return [k for k, v in EXAMPLES.items() if v.get("enabled", False)]


def canonical(key):
    """The example a key names (legacy keys resolve to their example)."""
    resolve = getattr(EXAMPLES, "canonical", None)
    return resolve(key) if resolve else key


def application_of(cfg: dict) -> str:
    """The application an example belongs to (an entry registered by hand
    without one is grouped by its model)."""
    return cfg.get("application") or str(cfg.get("model_name") or "Other").capitalize()


def applications() -> list[str]:
    """Application names that have at least one coupled example, in order."""
    return list(dict.fromkeys(application_of(v) for v in EXAMPLES.values() if v.get("enabled", False)))


def examples_of(application: str) -> list[str]:
    return [k for k, v in EXAMPLES.items() if v.get("enabled", False) and application_of(v) == application]


def selector_options() -> list[str]:
    """Every value the gateway's example selector accepts: the examples, then
    the legacy keys (resolved to their example as soon as they are chosen)."""
    aliases = getattr(EXAMPLES, "aliases", {})
    return enabled_names() + [k for k in aliases if k not in EXAMPLES.keys()]


def get_example(name: str) -> dict:
    if name not in EXAMPLES:
        raise KeyError(f"Unknown example: {name}")
    return EXAMPLES[name]

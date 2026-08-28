"""Declarative registry of the scientific components inside the ICESEE combined
container, and which runtime version-selection modes are technically valid for
each.

Facts here are taken from the ICESEE-Containers build scripts
(`spack-managed/combined-container/scripts/*`) and from inspection of the proven
`combined-env.sif` on PACE. Unknown values are recorded as ``None`` and MUST NOT
be inferred (e.g. a commit SHA is never guessed from a build date).
"""
from __future__ import annotations

from dataclasses import dataclass

# ── update classes ──────────────────────────────────────────────────────────
SOURCE_OVERRIDABLE = "source-overridable"      # pure source; a checkout swap is valid
ENVIRONMENT_SENSITIVE = "environment-sensitive"  # tied to a compiled env (PETSc/MPI)
COMPILED = "compiled"                            # a rebuilt binary is required

# ── runtime override mechanism ──────────────────────────────────────────────
OVERRIDE_BIND = "bind"   # bind a resolved checkout over baked_path (read-only SIF safe)
OVERRIDE_NONE = "none"   # cannot change at runtime; needs another container image

# ── selection modes ─────────────────────────────────────────────────────────
MODE_IMAGE = "image"     # exactly what the image validated; no network resolution
MODE_MAIN = "main"       # resolve the default branch to an exact SHA at submission
MODE_REF = "ref"         # resolve a user tag/branch/SHA to an exact SHA at submission
MODE_LATEST = "latest"   # resolve the newest release tag to an exact SHA


@dataclass(frozen=True)
class Component:
    key: str
    label: str
    repository: str | None          # None => not distributed via git (e.g. PyPI)
    baked_path: str                 # path inside the container
    update_class: str
    override: str
    modes: tuple[str, ...]          # modes this component *could* support
    baked_version: str | None = None   # human string; None if unknown
    baked_commit: str | None = None    # exact SHA; None => UNKNOWN (never inferred)
    baked_source_ref: str | None = None  # e.g. "main snapshot", "2025.10.2 (PyPI release)"
    default_branch: str = "main"
    gated_by: str | None = None     # component whose version constrains this one
    lock_note: str | None = None    # shown in the UI for image-only components

    @property
    def locked(self) -> bool:
        return self.modes == (MODE_IMAGE,)


COMPONENTS: dict[str, Component] = {
    # Compiled: issm.exe + *.mexa64 are linked against PETSc 3.22.3 / MPICH 4.2.3 /
    # MATLAB R2024b. A source checkout does not rebuild the solver. e70338d8 is a
    # `main` snapshot that self-reports "2026.1" — it is NOT the tag 2026.1.
    "issm": Component(
        key="issm",
        label="ISSM",
        repository="https://github.com/ISSMteam/ISSM.git",
        baked_path="/opt/ISSM",
        update_class=COMPILED,
        override=OVERRIDE_NONE,
        modes=(MODE_IMAGE,),
        baked_version="2026.1 (self-reported)",
        baked_commit="e70338d8685f8582b61958211e8f5fce2ea686ff",
        baked_source_ref="main snapshot",
        default_branch="main",
        lock_note=(
            "Compiled against PETSc 3.22.3 / MPICH 4.2.3 / MATLAB R2024b. "
            "Changing ISSM requires another container image."
        ),
    ),
    # Source-overridable: git checkout at /opt/ICESEE, `pip install -e`, imported
    # via PYTHONPATH=/opt. ICESEE-Containers documents overriding it with
    # `apptainer exec -B <checkout>:/opt/ICESEE`. No releases/tags upstream yet,
    # so no "latest release" mode.
    "icesee": Component(
        key="icesee",
        label="ICESEE",
        repository="https://github.com/ICESEE-project/ICESEE.git",
        baked_path="/opt/ICESEE",
        update_class=SOURCE_OVERRIDABLE,
        override=OVERRIDE_BIND,
        modes=(MODE_IMAGE, MODE_MAIN, MODE_REF),
        baked_version="0.1.9",
        baked_commit=None,              # UNKNOWN until the image is inspected
        baked_source_ref="main snapshot",
        default_branch="main",
    ),
    # Source-overridable but Firedrake-coupled: git checkout at /opt/icepack,
    # `pip install --no-deps -e` into an overlay venv on /opt/venv-firedrake.
    # A non-image version is only valid when validated against the image's
    # Firedrake (see stack.compat.ICEPACK_FIREDRAKE_COMPAT).
    "icepack": Component(
        key="icepack",
        label="Icepack",
        repository="https://github.com/icepack/icepack.git",
        baked_path="/opt/icepack",
        update_class=SOURCE_OVERRIDABLE,
        override=OVERRIDE_BIND,
        modes=(MODE_IMAGE, MODE_REF, MODE_LATEST),
        baked_version=None,             # master@<unknown>
        baked_commit=None,              # UNKNOWN until the image is inspected
        baked_source_ref="master snapshot",
        default_branch="master",
        gated_by="firedrake",
        lock_note=(
            "Depends directly on Firedrake; a non-image version is offered only "
            "when it is validated against the image's Firedrake."
        ),
    ),
    # Environment-sensitive: installed from PyPI (firedrake==2025.10.2) against
    # Spack PETSc 3.24.0 / petsc4py 3.24.0 / OpenMPI 5.0.10. No git checkout in
    # the image. A newer release generally needs a newer PETSc.
    "firedrake": Component(
        key="firedrake",
        label="Firedrake",
        repository="https://github.com/firedrakeproject/firedrake.git",
        baked_path="/opt/venv-firedrake/lib/python3.12/site-packages/firedrake",
        update_class=ENVIRONMENT_SENSITIVE,
        override=OVERRIDE_NONE,
        modes=(MODE_IMAGE,),
        baked_version="2025.10.2",
        baked_commit=None,             # PyPI release; no git checkout in the image
        baked_source_ref="2025.10.2 (PyPI release)",
        default_branch="main",
        lock_note=(
            "Built against PETSc 3.24.0 / petsc4py 3.24.0 / OpenMPI 5.0.10. "
            "Changing Firedrake requires another container image."
        ),
    ),
}

# Which components' versions are relevant to each model, in display order.
MODEL_COMPONENTS: dict[str, tuple[str, ...]] = {
    "issm": ("issm", "icesee"),
    "icepack": ("icepack", "firedrake", "icesee"),
}


def component(key: str) -> Component:
    try:
        return COMPONENTS[key]
    except KeyError:
        raise KeyError(f"Unknown stack component: {key!r}") from None


def components_for_model(model: str) -> tuple[Component, ...]:
    keys = MODEL_COMPONENTS.get((model or "").strip().lower(), ())
    return tuple(COMPONENTS[k] for k in keys)

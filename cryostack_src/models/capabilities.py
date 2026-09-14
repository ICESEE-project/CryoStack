"""One authoritative statement of *what CryoStack can actually do* with each
model (P1).

Before this, the answer was spread across the model adapters, the cloud
runtime, the visualization dispatch, and hard-coded ``_MODELS`` tuples in the
agent layer. :data:`MODEL_CAPABILITIES` collects it so a caller — the gateway,
an agent tool, a test — asks one place and gets a consistent answer.

Every field is grounded in code that already exists; nothing here enables a
feature, it only *describes* one. The module-level asserts at import time keep
the registry honest against the adapters it summarises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ModelCapabilities:
    name: str
    display_name: str
    language: str                       # "matlab" | "python"
    entrypoint_kind: str                # "matlab-script" | "notebook"

    #: a curated, validated Basic-mode parameter set exists
    basic_mode_config: bool = False
    #: name of the module-level validator, for discoverability
    basic_mode_validator: str = ""

    #: run outputs are exported to a transport-neutral structured package
    structured_results: bool = False
    result_contract: str = ""
    #: the structured package can be read without the model's runtime
    offline_result_reader: bool = False

    #: deterministic field / timeseries rendering on the neutral package
    visualization: bool = False

    requires_matlab: bool = False
    execution_modes: tuple[str, ...] = ("remote",)
    backends: tuple[str, ...] = ("spack", "container")
    cloud_supported: bool = False

    notes: str = ""

    # -- convenience --------------------------------------------------
    def supports_mode(self, mode: str) -> bool:
        return (mode or "").strip().lower() in self.execution_modes

    def supports_backend(self, backend: str) -> bool:
        return (backend or "").strip().lower() in self.backends

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "language": self.language,
            "entrypoint_kind": self.entrypoint_kind,
            "basic_mode_config": self.basic_mode_config,
            "basic_mode_validator": self.basic_mode_validator,
            "structured_results": self.structured_results,
            "result_contract": self.result_contract,
            "offline_result_reader": self.offline_result_reader,
            "visualization": self.visualization,
            "requires_matlab": self.requires_matlab,
            "execution_modes": list(self.execution_modes),
            "backends": list(self.backends),
            "cloud_supported": self.cloud_supported,
            "notes": self.notes,
        }


_ISSM = ModelCapabilities(
    name="issm",
    display_name="Ice-sheet & Sea-level System Model",
    language="matlab",
    entrypoint_kind="matlab-script",
    basic_mode_config=True,
    basic_mode_validator="cryostack_src.models.issm.validate_md_config",
    structured_results=True,
    result_contract="cryostack.issm.results",
    offline_result_reader=True,
    visualization=True,
    requires_matlab=True,
    execution_modes=("remote", "cloud"),
    backends=("spack", "container"),
    cloud_supported=True,
    notes="Solver-aware curated md.* parameters. MATLAB-free result reader "
          "(models/issm/results.py). Cloud is Fargate-only (no multi-node MPI).",
)

_ICEPACK = ModelCapabilities(
    name="icepack",
    display_name="icepack (Firedrake glacier flow)",
    language="python",
    entrypoint_kind="notebook",
    basic_mode_config=True,
    basic_mode_validator="cryostack_src.models.icepack.validate_icepack_config",
    structured_results=True,
    result_contract="cryostack.icepack.results",
    offline_result_reader=True,
    visualization=True,
    requires_matlab=False,
    execution_modes=("remote", "cloud"),
    backends=("spack", "container"),
    cloud_supported=True,
    notes="Basic-mode ice temperature / timestep count. Container-side "
          "Firedrake exporter; figures-only packages degrade gracefully. "
          "Cloud (AWS Batch, Fargate) uses the same tested combined image "
          "as ISSM, mirrored into its own cryostack-icepack ECR repository; "
          "no MATLAB license needed.",
)

MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    _ISSM.name: _ISSM,
    _ICEPACK.name: _ICEPACK,
}

#: the models CryoStack ships an adapter for, in display order
SUPPORTED_MODELS: tuple[str, ...] = tuple(MODEL_CAPABILITIES)


def get_model_capabilities(name: str) -> ModelCapabilities:
    key = (name or "").strip().lower()
    try:
        return MODEL_CAPABILITIES[key]
    except KeyError:
        raise ValueError(
            f"unknown model {name!r}; known: {', '.join(MODEL_CAPABILITIES)}"
        ) from None


def _verify_against_adapters() -> None:
    """Fail import if the registry drifts from the code it summarises."""
    from cryostack_src.cloud.runtime import SUPPORTED_CLOUD_MODELS

    for cap in MODEL_CAPABILITIES.values():
        assert cap.cloud_supported == (cap.name in SUPPORTED_CLOUD_MODELS), (
            f"{cap.name}: cloud_supported disagrees with "
            f"cloud.runtime.SUPPORTED_CLOUD_MODELS")
        assert ("cloud" in cap.execution_modes) == cap.cloud_supported, (
            f"{cap.name}: execution_modes / cloud_supported inconsistent")

    from cryostack_src.models.icepack import HAS_BASIC_CONFIG
    assert _ICEPACK.basic_mode_config == HAS_BASIC_CONFIG

    from cryostack_src.models.issm import CURATED_MD_PARAMETERS
    assert _ISSM.basic_mode_config == bool(CURATED_MD_PARAMETERS)


_verify_against_adapters()

from .configuration import build_environment_check, validate_configuration
from .execution import (
    EXAMPLE_ENTRYPOINTS, build_activation_check, build_run_command,
    choose_run_target, example_runnable, example_template, order_run_targets,
)
from .parameters import (
    BASIC_MODE_PARAMETERS,
    CURATED_ICEPACK_PARAMETERS,
    IcepackOverrideError,
    IcepackParameter,
    IcepackParameterError,
    apply_overrides,
    classify,
    describe_overrides,
    entrypoint_transform_for,
    validate_icepack_config,
)
from .postprocess import SCHEMA, build_postprocess
from .results import IcepackResultPackage, discover_results
from .slurm import build_container_fragment, build_slurm_script

#: the Icepack adapter has curated Basic-mode parameters (unlike the ISSM
#: adapter's `md`-based ones); the gateway can key its panel off this.
HAS_BASIC_CONFIG = bool(BASIC_MODE_PARAMETERS)

__all__ = [
    "build_run_command", "build_slurm_script", "build_postprocess", "SCHEMA",
    "validate_configuration", "build_environment_check", "build_activation_check",
    "build_container_fragment", "choose_run_target", "order_run_targets",
    "example_runnable", "example_template", "EXAMPLE_ENTRYPOINTS",
    "discover_results", "IcepackResultPackage",
    "CURATED_ICEPACK_PARAMETERS", "BASIC_MODE_PARAMETERS", "IcepackParameter",
    "IcepackParameterError", "IcepackOverrideError", "validate_icepack_config",
    "apply_overrides", "describe_overrides", "entrypoint_transform_for",
    "classify", "HAS_BASIC_CONFIG",
]

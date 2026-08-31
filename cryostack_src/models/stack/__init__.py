"""Component-aware runtime stack selection for CryoStack container runs.

One declarative registry (:mod:`components`), one resolver that normalises a
version choice to an immutable commit SHA (:mod:`resolver`), one compatibility
authority (:mod:`compat`), one container-identity resolver (:mod:`container`),
a curated tested-image registry (:mod:`images`), and the provenance combiner
(:mod:`provenance`).
"""
from __future__ import annotations

from .compat import (
    ICEPACK_FIREDRAKE_COMPAT,
    STACK_PROFILE_CUSTOM,
    STACK_PROFILE_TESTED,
    STACK_PROFILES,
    ComponentOption,
    ComponentSelection,
    ComponentVerdict,
    StackCompatError,
    StackValidation,
    offered_options,
    validate_stack,
)
from .components import (
    COMPILED,
    COMPONENTS,
    ENVIRONMENT_SENSITIVE,
    MODE_IMAGE,
    MODE_LATEST,
    MODE_MAIN,
    MODE_REF,
    MODEL_COMPONENTS,
    OVERRIDE_BIND,
    OVERRIDE_NONE,
    SOURCE_OVERRIDABLE,
    Component,
    component,
    components_for_model,
)
from .container import (
    BASE_IMAGE_DIGEST,
    BASE_IMAGE_REF,
    ContainerIdentity,
    ContainerIdentityError,
    resolve_container,
)
from .images import (
    TESTED_IMAGES,
    TestedImage,
    all_tested_images,
    default_tested_image_for_model,
    find_tested_image,
    get_tested_image,
    tested_images_for_model,
)
from .provenance import resolve_stack, stack_log_line
from .resolver import (
    ComponentChoice,
    ComponentResolutionError,
    ResolvedComponent,
    resolve_component,
)
from .runtime import (
    ComponentCheckout,
    StackRuntimeError,
    checkout_bind_suffix,
    checkout_setup_block,
    component_checkout_plan,
)

__all__ = [
    # components
    "Component", "COMPONENTS", "MODEL_COMPONENTS", "component", "components_for_model",
    "MODE_IMAGE", "MODE_MAIN", "MODE_REF", "MODE_LATEST",
    "SOURCE_OVERRIDABLE", "ENVIRONMENT_SENSITIVE", "COMPILED",
    "OVERRIDE_BIND", "OVERRIDE_NONE",
    # resolver
    "ComponentChoice", "ResolvedComponent", "resolve_component", "ComponentResolutionError",
    # container
    "ContainerIdentity", "ContainerIdentityError", "resolve_container",
    "BASE_IMAGE_REF", "BASE_IMAGE_DIGEST",
    # tested-image registry
    "TESTED_IMAGES", "TestedImage", "all_tested_images", "get_tested_image",
    "tested_images_for_model", "default_tested_image_for_model", "find_tested_image",
    # compat
    "STACK_PROFILES", "STACK_PROFILE_TESTED", "STACK_PROFILE_CUSTOM",
    "ComponentSelection", "ComponentOption", "ComponentVerdict", "StackValidation",
    "StackCompatError", "validate_stack", "offered_options", "ICEPACK_FIREDRAKE_COMPAT",
    # provenance
    "resolve_stack", "stack_log_line",
    # runtime checkout
    "ComponentCheckout", "StackRuntimeError", "component_checkout_plan",
    "checkout_setup_block", "checkout_bind_suffix",
]

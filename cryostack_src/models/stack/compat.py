"""Stack compatibility layer.

Component versions are not independent. This module is the single authority for:

* which selection modes / refs a component may actually be given for a model,
  taking the rest of the (image-locked) stack into account, and
* whether a proposed set of selections is a trusted, submittable combination.

v1 policy: build the trusted path first. ``tested`` runs the image's validated
stack verbatim with no network resolution. ``custom`` permits only
technically-valid overrides:

* ISSM, Firedrake      -> image version only (compiled / env-sensitive)
* ICESEE               -> image / main / specific ref (pure source)
* Icepack              -> image, plus a ref/release ONLY when
  ``ICEPACK_FIREDRAKE_COMPAT`` says it is validated against the image's
  Firedrake. Firedrake is never upgraded automatically.
"""
from __future__ import annotations

from dataclasses import dataclass

from .components import (
    COMPONENTS,
    MODEL_COMPONENTS,
    MODE_IMAGE,
    MODE_MAIN,
    MODE_REF,
    Component,
)

STACK_PROFILE_TESTED = "tested"
STACK_PROFILE_CUSTOM = "custom"
STACK_PROFILES = (STACK_PROFILE_TESTED, STACK_PROFILE_CUSTOM)

# Known-good Icepack refs/releases, keyed by the image's Firedrake version.
# Today only the image's own baked combination is validated; every other Icepack
# ref needs a purpose-built container image. An empty set => "image only".
ICEPACK_FIREDRAKE_COMPAT: dict[str, frozenset[str]] = {
    "2025.10.2": frozenset(),
}


@dataclass(frozen=True)
class ComponentSelection:
    key: str
    mode: str = MODE_IMAGE
    ref: str | None = None


@dataclass(frozen=True)
class ComponentOption:
    """One selectable choice offered for a component in the UI."""
    mode: str
    label: str
    ref: str | None = None


@dataclass(frozen=True)
class ComponentVerdict:
    key: str
    ok: bool
    locked: bool
    reason: str = ""


@dataclass(frozen=True)
class StackValidation:
    ok: bool
    profile: str
    verdicts: tuple[ComponentVerdict, ...]

    def blocking(self) -> tuple[ComponentVerdict, ...]:
        return tuple(v for v in self.verdicts if not v.ok)


class StackCompatError(RuntimeError):
    def __init__(self, validation: StackValidation) -> None:
        self.validation = validation
        msgs = "; ".join(f"{v.key}: {v.reason}" for v in validation.blocking())
        super().__init__(msgs or "stack combination is not valid")


_MODE_LABELS = {
    MODE_IMAGE: "Image version",
    MODE_MAIN: "Main branch",
    MODE_REF: "Specific ref",
}


def firedrake_image_version() -> str:
    return COMPONENTS["firedrake"].baked_version or ""


def offered_options(
    component_key: str,
    *,
    firedrake_version: str | None = None,
) -> tuple[ComponentOption, ...]:
    """The choices the UI may present for a component under the Custom profile."""
    comp = COMPONENTS[component_key]
    image_label = f"Image version ({comp.baked_version})" if comp.baked_version else "Image version"
    image_opt = ComponentOption(MODE_IMAGE, image_label)

    if comp.locked:
        return (image_opt,)

    if comp.key == "icesee":
        return (
            image_opt,
            ComponentOption(MODE_MAIN, _MODE_LABELS[MODE_MAIN]),
            ComponentOption(MODE_REF, _MODE_LABELS[MODE_REF]),
        )

    if comp.key == "icepack":
        fv = firedrake_version or firedrake_image_version()
        validated = sorted(ICEPACK_FIREDRAKE_COMPAT.get(fv, frozenset()))
        return (image_opt, *[
            ComponentOption(MODE_REF, f"{ref} (validated)", ref=ref) for ref in validated
        ])

    return (image_opt,)


def _verdict(comp: Component, sel: ComponentSelection, *, fv: str) -> ComponentVerdict:
    if sel.mode == MODE_IMAGE:
        return ComponentVerdict(comp.key, ok=True, locked=comp.locked)

    if comp.locked:
        return ComponentVerdict(
            comp.key, ok=False, locked=True,
            reason=(
                f"{comp.label} {comp.baked_version or ''} is locked to the image "
                f"version. Changing it requires another container image."
            ).replace("  ", " ").strip(),
        )

    if sel.mode not in comp.modes:
        return ComponentVerdict(
            comp.key, ok=False, locked=False,
            reason=f"{comp.label} does not support {sel.mode!r}.",
        )

    if comp.key == "icepack":
        validated = ICEPACK_FIREDRAKE_COMPAT.get(fv, frozenset())
        token = (sel.ref or "").strip()
        if token and token in validated:
            return ComponentVerdict(comp.key, ok=True, locked=False)
        return ComponentVerdict(
            comp.key, ok=False, locked=False,
            reason=(
                f"This Icepack version is not validated with Firedrake {fv}. "
                f"A compatible container image is required."
            ),
        )

    # icesee: pure source, no dependency chain
    if sel.mode == MODE_REF and not (sel.ref or "").strip():
        return ComponentVerdict(
            comp.key, ok=False, locked=False,
            reason=f"{comp.label}: a specific ref is required.",
        )
    return ComponentVerdict(comp.key, ok=True, locked=False)


def validate_stack(
    *,
    model: str,
    profile: str,
    selections: dict[str, ComponentSelection] | None = None,
    firedrake_version: str | None = None,
) -> StackValidation:
    model = (model or "").strip().lower()
    profile = (profile or STACK_PROFILE_TESTED).strip().lower()
    keys = MODEL_COMPONENTS.get(model)
    if keys is None:
        raise KeyError(f"Unknown model: {model!r}")

    fv = firedrake_version or firedrake_image_version()
    selections = selections or {}
    verdicts: list[ComponentVerdict] = []

    for key in keys:
        comp = COMPONENTS[key]
        if profile == STACK_PROFILE_TESTED:
            # tested == exactly the image stack; any stray selection is ignored
            verdicts.append(ComponentVerdict(key, ok=True, locked=comp.locked))
            continue
        sel = selections.get(key) or ComponentSelection(key, MODE_IMAGE)
        verdicts.append(_verdict(comp, sel, fv=fv))

    return StackValidation(
        ok=all(v.ok for v in verdicts),
        profile=profile,
        verdicts=tuple(verdicts),
    )

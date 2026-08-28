"""Combine container identity + per-component resolution into the authoritative
structured provenance for a run (the manifest ``software`` / ``container``
blocks). This records *what will actually execute*, not what was requested.
"""
from __future__ import annotations

from .compat import (
    ComponentSelection,
    StackCompatError,
    STACK_PROFILE_TESTED,
    validate_stack,
)
from .components import COMPONENTS, MODEL_COMPONENTS
from .container import resolve_container
from .resolver import ComponentChoice, resolve_component


def resolve_stack(
    *,
    model: str,
    profile: str,
    selections: dict[str, ComponentSelection] | None = None,
    container_source: str | None,
    image_uri: str | None,
    ls_remote=None,
    digest_resolver=None,
) -> dict:
    """Validate the requested stack and resolve it to immutable provenance.

    Raises :class:`StackCompatError` if the combination is not a trusted,
    submittable stack. On success returns::

        {
          "profile": "tested" | "custom",
          "container": {"source", "reference", "digest", "build_provenance"?},
          "software": {"<component>": {"source", "requested_ref",
                                       "resolved_commit", "version"?, ...}},
        }
    """
    model = (model or "").strip().lower()
    profile = (profile or STACK_PROFILE_TESTED).strip().lower()
    selections = selections or {}

    validation = validate_stack(model=model, profile=profile, selections=selections)
    if not validation.ok:
        raise StackCompatError(validation)

    container = resolve_container(
        container_source=container_source,
        image_uri=image_uri,
        digest_resolver=digest_resolver,
    )

    resolve_kwargs = {} if ls_remote is None else {"ls_remote": ls_remote}
    software: dict[str, dict] = {}
    for key in MODEL_COMPONENTS[model]:
        comp = COMPONENTS[key]
        if profile == STACK_PROFILE_TESTED:
            choice = ComponentChoice(key)  # image
        else:
            sel = selections.get(key) or ComponentSelection(key)
            choice = ComponentChoice(key, mode=sel.mode, ref=sel.ref)
        software[key] = resolve_component(comp, choice, **resolve_kwargs).as_provenance()

    return {
        "profile": profile,
        "container": container.as_provenance(),
        "software": software,
    }


def stack_log_line(resolved: dict) -> str:
    """A single immutable, human-readable line for the execution log, e.g.::

        [stack] tested | container=docker://…@sha256:… | issm=image 2026.1 (self-reported)
                @e70338d8 | icesee=image 0.1.9 @unknown
    """
    parts = [f"[stack] {resolved.get('profile', '?')}"]
    c = resolved.get("container", {})
    cref = c.get("digest") or c.get("reference") or c.get("source", "?")
    parts.append(f"container={cref}")
    for key, sw in resolved.get("software", {}).items():
        commit = sw.get("resolved_commit") or "unknown"
        short = commit[:12] if commit != "unknown" else "unknown"
        ver = sw.get("version")
        tag = f"{sw.get('source', '?')}"
        if ver:
            tag += f" {ver}"
        if sw.get("requested_ref"):
            tag += f" ({sw['requested_ref']})"
        parts.append(f"{key}={tag} @{short}")
    return " | ".join(parts)

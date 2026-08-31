"""Turn resolved component provenance into a run-local source checkout plan.

A component override is materialised as a *run-local* git checkout under
``<run_dir>/.stack/<component>/`` which is then bind-mounted over the baked path
inside the container. The image's ``/opt/ICESEE`` / ``/opt/icepack`` / ``/opt/ISSM``
/ ``/opt/venv-firedrake`` are never modified.

Only the registry repository URL and a locally-validated 40-hex commit SHA are
ever placed in the generated job script — a user-supplied ref is resolved to a
SHA *before* submission (see :mod:`resolver`) and never interpolated here.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from .components import COMPONENTS, OVERRIDE_BIND

_SHA40 = re.compile(r"\A[0-9a-f]{40}\Z")
_COMPONENT_KEY = re.compile(r"\A[a-z][a-z0-9_-]{0,31}\Z")


class StackRuntimeError(ValueError):
    pass


@dataclass(frozen=True)
class ComponentCheckout:
    key: str
    repository: str      # from the component registry (trusted)
    commit: str          # validated ^[0-9a-f]{40}$
    dest: str            # <run_dir>/.stack/<key>
    bind_target: str     # baked path in the image

    def bind_spec(self) -> str:
        """The ``-B`` fragment, e.g. ``"<dest>":"/opt/ICESEE"``."""
        return f'"{self.dest}":"{self.bind_target}"'

    def setup_script(self) -> str:
        """Shell that guarantees *this exact commit* is fetched and checked out.

        A shallow/default-branch clone does not guarantee an arbitrary commit is
        present, so we fetch the commit directly and fall back to a full
        branch+tag fetch. The branch/tag is never re-resolved here. Any failure
        aborts the job loudly — there is no silent fall-back to the image copy.
        """
        d = shlex.quote(self.dest)
        repo = shlex.quote(self.repository)
        sha = self.commit  # already ^[0-9a-f]{40}$
        key = self.key
        return "\n".join([
            f'echo "[stack] {key}: preparing run-local checkout @ {sha}"',
            f'rm -rf {d}',
            f'mkdir -p {d}',
            f'if ! git -C {d} init -q; then echo "[stack][ERROR] {key}: git init failed"; exit 3; fi',
            f'git -C {d} config advice.detachedHead false',
            f'if ! git -C {d} remote add origin {repo}; then echo "[stack][ERROR] {key}: git remote add failed"; exit 3; fi',
            f'if git -C {d} fetch --no-tags --depth 1 origin {sha} 2>/dev/null; then',
            f'    git -C {d} checkout -q --detach FETCH_HEAD',
            f'else',
            f'    echo "[stack] {key}: direct commit fetch unavailable, fetching branches and tags"',
            f"    if ! git -C {d} fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*' '+refs/tags/*:refs/tags/*'; then",
            f'        echo "[stack][ERROR] {key}: could not fetch from {self.repository} (network or repository unavailable)"; exit 3',
            f'    fi',
            f'    if ! git -C {d} checkout -q --detach {sha}; then',
            f'        echo "[stack][ERROR] {key}: resolved commit {sha} not found in repository"; exit 3',
            f'    fi',
            f'fi',
            f'_have="$(git -C {d} rev-parse HEAD 2>/dev/null || true)"',
            f'if [ "$_have" != "{sha}" ]; then',
            f'    echo "[stack][ERROR] {key}: checked out $_have but the run requires {sha}"; exit 3',
            f'fi',
            f'echo "[stack] {key}: checked out {sha}"',
        ])


def component_checkout_plan(software: dict | None, run_dir: str) -> list[ComponentCheckout]:
    """Build the checkout plan for the components whose ``source`` is ``git``.

    ``software`` is the resolved provenance block (from ``resolve_stack``).
    Raises :class:`StackRuntimeError` on any malformed entry so a bad selection
    fails *before* the run is registered.
    """
    if not run_dir:
        raise StackRuntimeError("run_dir is required for a source override")
    base = run_dir.rstrip("/")
    plan: list[ComponentCheckout] = []

    for key, entry in sorted((software or {}).items()):
        if not _COMPONENT_KEY.match(key) or key not in COMPONENTS:
            raise StackRuntimeError(f"unknown stack component: {key!r}")
        if not isinstance(entry, dict):
            raise StackRuntimeError(f"{key}: malformed provenance entry")
        if entry.get("source") != "git":
            continue

        comp = COMPONENTS[key]
        if comp.override != OVERRIDE_BIND or not comp.repository:
            raise StackRuntimeError(f"{comp.label} cannot be source-overridden at runtime")

        commit = str(entry.get("resolved_commit") or "")
        if not _SHA40.match(commit):
            raise StackRuntimeError(
                f"{key}: resolved_commit must be a 40-hex commit SHA, got {commit!r}"
            )

        plan.append(ComponentCheckout(
            key=key,
            repository=comp.repository,
            commit=commit,
            dest=f"{base}/.stack/{key}",
            bind_target=comp.baked_path,
        ))
    return plan


def checkout_setup_block(plan: list[ComponentCheckout]) -> str:
    """All setup scripts joined; empty string when there is nothing to check out."""
    if not plan:
        return ""
    return (
        'echo "[stack] materialising run-local source overrides"\n'
        + "\n".join(c.setup_script() for c in plan)
    )


def checkout_bind_suffix(plan: list[ComponentCheckout]) -> str:
    """``,"<dest>":"<target>"`` fragments to append to an existing ``-B`` list."""
    return "".join(f",{c.bind_spec()}" for c in plan)

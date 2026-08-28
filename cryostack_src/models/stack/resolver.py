"""Normalise a component version *choice* to an immutable commit SHA.

Rules:
* ``image`` never touches the network — it returns the baked identity as-is
  (which may have an unknown commit; that is recorded honestly, not guessed).
* ``main`` / ``ref`` / ``latest`` are resolved to an exact SHA *at submission
  time*. The resolved SHA is what a job must use; a job must never re-resolve a
  branch/tag later (``main`` advancing must not change a queued job).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from .components import (
    MODE_IMAGE,
    MODE_LATEST,
    MODE_MAIN,
    MODE_REF,
    Component,
)

_FULL_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
_SHORT_SHA = re.compile(r"\A[0-9a-f]{7,40}\Z")
_SEMVERISH = re.compile(r"(\d+)(?:[._-](\d+))?(?:[._-](\d+))?")


class ComponentResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComponentChoice:
    key: str
    mode: str = MODE_IMAGE
    ref: str | None = None      # required for MODE_REF


@dataclass(frozen=True)
class ResolvedComponent:
    key: str
    source: str                 # "image" | "git"
    requested_ref: str | None   # None for image; "main" / "<tag>" / "<sha>"
    resolved_commit: str | None  # exact SHA; None only when genuinely unknown
    version: str | None = None
    source_ref: str | None = None
    commit_known: bool = True
    repository: str | None = None
    resolved_via: str | None = None   # "image" | "ls-remote" | "user-sha"

    def as_provenance(self) -> dict:
        out: dict = {
            "source": self.source,
            "requested_ref": self.requested_ref,
            "resolved_commit": self.resolved_commit if self.commit_known else None,
        }
        if self.version is not None:
            out["version"] = self.version
        if self.source_ref is not None:
            out["source_ref"] = self.source_ref
        if not self.commit_known:
            out["commit_status"] = "unknown-until-image-inspected"
        if self.repository is not None:
            out["repository"] = self.repository
        if self.resolved_via is not None:
            out["resolved_via"] = self.resolved_via
        return out


def _git_ls_remote(repository: str, *patterns: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "ls-remote", repository, *patterns],
            capture_output=True, text=True, timeout=45,
        )
    except (OSError, subprocess.SubprocessError) as err:
        raise ComponentResolutionError(f"git ls-remote {repository}: {err}") from err
    if proc.returncode != 0:
        raise ComponentResolutionError(
            f"git ls-remote {repository} {' '.join(patterns)} failed: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc.stdout


def _parse_ls_remote(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and _FULL_SHA.match(parts[0]):
            rows.append((parts[0], parts[1].strip()))
    return rows


def _pick_newest_tag(rows: list[tuple[str, str]]) -> tuple[str, str]:
    """From ls-remote --tags rows pick the newest semver-ish tag."""
    best: tuple[tuple[int, int, int], str, str] | None = None
    for sha, ref in rows:
        name = ref.rsplit("/", 1)[-1]
        if name.endswith("^{}"):
            name = name[:-3]
        m = _SEMVERISH.search(name)
        if not m:
            continue
        key = tuple(int(g) if g else 0 for g in m.groups())  # (a, b, c)
        if best is None or key > best[0]:
            best = (key, name, sha)
    if best is None:
        raise ComponentResolutionError("no version-like tags found upstream")
    return best[2], best[1]


def resolve_component(
    comp: Component,
    choice: ComponentChoice,
    *,
    ls_remote=_git_ls_remote,
) -> ResolvedComponent:
    mode = (choice.mode or MODE_IMAGE).strip().lower()

    if mode == MODE_IMAGE:
        return ResolvedComponent(
            key=comp.key,
            source="image",
            requested_ref=None,
            resolved_commit=comp.baked_commit,
            version=comp.baked_version,
            source_ref=comp.baked_source_ref,
            commit_known=comp.baked_commit is not None,
            repository=comp.repository,
            resolved_via="image",
        )

    if comp.locked or mode not in comp.modes:
        raise ComponentResolutionError(
            f"{comp.label} does not support mode {mode!r}; supported: {comp.modes}"
        )
    if comp.repository is None:
        raise ComponentResolutionError(f"{comp.label} has no git repository to resolve")

    if mode == MODE_MAIN:
        branch = comp.default_branch
        rows = _parse_ls_remote(ls_remote(comp.repository, f"refs/heads/{branch}"))
        if not rows:
            raise ComponentResolutionError(
                f"{comp.label}: branch {branch!r} not found upstream"
            )
        return ResolvedComponent(
            key=comp.key, source="git", requested_ref="main",
            resolved_commit=rows[0][0], repository=comp.repository,
            source_ref=f"{branch} branch", resolved_via="ls-remote",
        )

    if mode == MODE_LATEST:
        rows = _parse_ls_remote(ls_remote(comp.repository, "--tags", "--refs"))
        sha, name = _pick_newest_tag(rows)
        return ResolvedComponent(
            key=comp.key, source="git", requested_ref=name,
            resolved_commit=sha, version=name, repository=comp.repository,
            source_ref=f"{name} (release tag)", resolved_via="ls-remote",
        )

    # MODE_REF: user tag / branch / SHA
    ref = (choice.ref or "").strip()
    if not ref:
        raise ComponentResolutionError(f"{comp.label}: a specific ref is required")

    if _FULL_SHA.match(ref):
        # A full SHA is already immutable; ls-remote cannot verify an arbitrary
        # commit, so pass it through and let the job's fetch fail loudly if bad.
        return ResolvedComponent(
            key=comp.key, source="git", requested_ref=ref, resolved_commit=ref,
            repository=comp.repository, source_ref="commit", resolved_via="user-sha",
        )

    rows = _parse_ls_remote(
        ls_remote(comp.repository, f"refs/tags/{ref}", f"refs/heads/{ref}", ref)
    )
    # prefer an exact tag, then branch, then any match
    def _first(kind: str) -> tuple[str, str] | None:
        for sha, r in rows:
            if r == f"refs/{kind}/{ref}" or r == f"refs/{kind}/{ref}^{{}}":
                return sha, r
        return None

    match = _first("tags") or _first("heads") or (rows[0] if rows else None)
    if match is None:
        if _SHORT_SHA.match(ref):
            return ResolvedComponent(
                key=comp.key, source="git", requested_ref=ref, resolved_commit=ref,
                repository=comp.repository, source_ref="abbreviated commit",
                resolved_via="user-sha",
            )
        raise ComponentResolutionError(f"{comp.label}: ref {ref!r} not found upstream")

    sha, r = match
    kind = "tag" if "/tags/" in r else "branch" if "/heads/" in r else "ref"
    return ResolvedComponent(
        key=comp.key, source="git", requested_ref=ref, resolved_commit=sha,
        version=ref if kind == "tag" else None, repository=comp.repository,
        source_ref=kind, resolved_via="ls-remote",
    )

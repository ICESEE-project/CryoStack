"""ICESEE-Spack environment lifecycle for the Remote backend.

One authority for: where the ICESEE-Spack checkout lives on a resource, a *fast*
readiness probe per model, a *deep* verification step, the clone/update script,
and the durable Slurm setup job that actually builds the environment.

This module is pure text + classification -- it performs no I/O. Transport
(direct SSH / connector) is the caller's job (see
:class:`cryostack_src.remote.bridge.RemoteBridge`).

Lifecycle:  Check -> (not ready) -> Prepare -> sbatch setup job -> Verify -> Ready

Markers are *not* authoritative: readiness is always decided by re-probing the
real environment, never by a cached flag or a ``.installed`` file.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum

DEFAULT_SPACK_REPO = "https://github.com/ICESEE-project/ICESEE-Spack.git"
DEFAULT_SPACK_DIRNAME = "ICESEE-Spack"

_INSTALL_FLAG = {"issm": "--with-issm", "icepack": "--with-icepack"}
_MODELS = tuple(_INSTALL_FLAG)


class EnvStatus(str, Enum):
    NOT_INSTALLED = "not_installed"   # no ICESEE-Spack checkout on the resource
    REPO_ONLY = "repo_only"           # checkout present, environment not usable
    INSTALLING = "installing"         # a setup job is currently running
    READY = "ready"                   # probe passed for the selected model
    FAILED = "failed"                 # setup job failed / environment broken

    @property
    def label(self) -> str:
        return {
            EnvStatus.NOT_INSTALLED: "Not installed",
            EnvStatus.REPO_ONLY: "Not built",
            EnvStatus.INSTALLING: "Installing",
            EnvStatus.READY: "Ready",
            EnvStatus.FAILED: "Failed",
        }[self]

    @property
    def badge_state(self) -> str:
        return {
            EnvStatus.NOT_INSTALLED: "idle",
            EnvStatus.REPO_ONLY: "warning",
            EnvStatus.INSTALLING: "running",
            EnvStatus.READY: "ready",
            EnvStatus.FAILED: "error",
        }[self]

    @property
    def is_ready(self) -> bool:
        return self is EnvStatus.READY


@dataclass(frozen=True)
class SpackPaths:
    base: str                 # resolved remote base dir (absolute)
    dirname: str
    repo: str                 # {base}/{dirname}
    activate: str             # {repo}/scripts/activate.sh

    def marker(self, model: str) -> str:
        return f"{self.repo}/.icesee_spack_{model}_ready"


def spack_paths(remote_base_abs: str, dirname: str = DEFAULT_SPACK_DIRNAME) -> SpackPaths:
    base = remote_base_abs.rstrip("/")
    name = (dirname or DEFAULT_SPACK_DIRNAME).strip("/") or DEFAULT_SPACK_DIRNAME
    repo = f"{base}/{name}"
    return SpackPaths(base=base, dirname=name, repo=repo, activate=f"{repo}/scripts/activate.sh")


def spack_paths_from_repo(repo_abs: str) -> SpackPaths:
    repo = repo_abs.rstrip("/")
    base, _, name = repo.rpartition("/")
    return SpackPaths(
        base=base or "/", dirname=name or DEFAULT_SPACK_DIRNAME, repo=repo,
        activate=f"{repo}/scripts/activate.sh",
    )


def _require_model(model: str) -> str:
    m = (model or "").strip().lower()
    if m not in _MODELS:
        raise ValueError(f"Unsupported model for ICESEE-Spack: {model!r}")
    return m


@dataclass(frozen=True)
class EnvReport:
    status: EnvStatus
    model: str
    messages: tuple[str, ...] = ()
    markers: dict = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.status.is_ready


# ── model-specific fragments (assume ICESEE-Spack activate.sh already sourced) ──
def _model_probe_fragment(model: str) -> str:
    """Fast, no-MATLAB readiness check. Emits CRYOSTACK_ENV_MODEL=ok|fail:<why>."""
    if model == "issm":
        return (
            'if [ -z "${ISSM_DIR:-}" ]; then echo "CRYOSTACK_ENV_MODEL=fail:issm_dir_unset";\n'
            'elif [ ! -d "${ISSM_DIR}" ]; then echo "CRYOSTACK_ENV_MODEL=fail:issm_dir_missing";\n'
            'elif [ ! -x "${ISSM_DIR}/bin/issm.exe" ] && ! command -v issm.exe >/dev/null 2>&1; then\n'
            '  echo "CRYOSTACK_ENV_MODEL=fail:issm_exe_missing";\n'
            'else echo "CRYOSTACK_ENV_MODEL=ok"; fi'
        )
    # icepack: the required check is the firedrake + icepack import (seconds).
    return (
        'if python -c "import firedrake, icepack" >/dev/null 2>&1; then\n'
        '  echo "CRYOSTACK_ENV_MODEL=ok";\n'
        'else echo "CRYOSTACK_ENV_MODEL=fail:import_failed"; fi'
    )


def _model_deep_verify_fragment(model: str, *, matlab_license: dict | None) -> str:
    """Deep verification, run once on a compute node after install.

    ISSM  -> matlab -batch "addpath(ISSM bin/lib); issmversion"
    Icepack -> python -c "import firedrake; import icepack"
    Emits CRYOSTACK_ENV_DEEP=ok|fail.
    """
    if model == "issm":
        lic = matlab_license or {}
        env_var = str(lic.get("env_var") or "MLM_LICENSE_FILE").strip() or "MLM_LICENSE_FILE"
        value = str(lic.get("value") or "").strip()
        export = f'export {env_var}={shlex.quote(value)}\n' if value else ""
        return (
            f'{export}'
            'if matlab -batch '
            '"addpath([getenv(\'ISSM_DIR\') \'/bin\'],[getenv(\'ISSM_DIR\') \'/lib\']); '
            'issmversion; exit" ; then\n'
            '  echo "CRYOSTACK_ENV_DEEP=ok";\n'
            'else echo "CRYOSTACK_ENV_DEEP=fail"; exit 21; fi'
        )
    return (
        'if python -c "import firedrake; import icepack; print(\'[verify] firedrake+icepack ok\')" ; then\n'
        '  echo "CRYOSTACK_ENV_DEEP=ok";\n'
        'else echo "CRYOSTACK_ENV_DEEP=fail"; exit 21; fi'
    )


# ── scripts ──────────────────────────────────────────────────────────────────
def probe_script(*, model: str, paths: SpackPaths) -> str:
    """Fast environment probe. Always exits 0; state is read from the markers."""
    model = _require_model(model)
    repo = shlex.quote(paths.repo)
    activate = shlex.quote(paths.activate)
    marker = shlex.quote(paths.marker(model))
    return f"""set +e
if [ ! -d {repo} ]; then
  echo "CRYOSTACK_ENV_REPO=absent"
  echo "CRYOSTACK_ENV_ACTIVATE=skip"
  echo "CRYOSTACK_ENV_MODEL=skip"
  echo "CRYOSTACK_ENV_MARKER=absent"
  exit 0
fi
echo "CRYOSTACK_ENV_REPO=present"
[ -f {marker} ] && echo "CRYOSTACK_ENV_MARKER=present" || echo "CRYOSTACK_ENV_MARKER=absent"
if [ ! -f {activate} ]; then
  echo "CRYOSTACK_ENV_ACTIVATE=fail:no_activate_script"
  echo "CRYOSTACK_ENV_MODEL=skip"
  exit 0
fi
if ! source {activate} >/dev/null 2>&1; then
  echo "CRYOSTACK_ENV_ACTIVATE=fail:source_error"
  echo "CRYOSTACK_ENV_MODEL=skip"
  exit 0
fi
echo "CRYOSTACK_ENV_ACTIVATE=ok"
{_model_probe_fragment(model)}
exit 0
"""


def ensure_repo_script(
    *,
    paths: SpackPaths,
    repo_url: str = DEFAULT_SPACK_REPO,
    update: bool = True,
) -> str:
    """Clone ICESEE-Spack if absent; otherwise a safe fast-forward-only pull."""
    base = shlex.quote(paths.base)
    repo = shlex.quote(paths.repo)
    name = shlex.quote(paths.dirname)
    url = shlex.quote(repo_url or DEFAULT_SPACK_REPO)
    pull = (
        f'  echo "[spack-setup] updating {paths.repo}"\n'
        f'  git -C {repo} pull --ff-only || echo "[spack-setup] pull skipped (non-ff or offline)"\n'
        if update else '  echo "[spack-setup] repo present, leaving as-is"\n'
    )
    return f"""mkdir -p {base}
if [ ! -d {repo}/.git ]; then
  echo "[spack-setup] cloning {repo_url} -> {paths.repo}"
  rm -rf {repo}
  git clone {url} {base}/{name}
else
{pull}fi
test -f {shlex.quote(paths.activate)} || {{ echo "[spack-setup][ERROR] missing scripts/activate.sh"; exit 3; }}
"""


@dataclass(frozen=True)
class SetupSlurmOpts:
    partition: str = "cpu-small"
    time: str = "08:00:00"
    nodes: int = 1
    ntasks: int = 8
    mem: str = "32G"
    account: str = ""
    mail: str = ""


def install_sbatch_text(
    *,
    model: str,
    paths: SpackPaths,
    setup_dir: str,
    repo_url: str = DEFAULT_SPACK_REPO,
    slurm: SetupSlurmOpts | None = None,
    matlab_license: dict | None = None,
) -> str:
    """The durable ICESEE-Spack setup job: clone/update, install.sh, deep verify.

    Runs on a compute node (never a synchronous SSH call). Writes the readiness
    marker only after deep verification passes.
    """
    model = _require_model(model)
    slurm = slurm or SetupSlurmOpts()
    flag = _INSTALL_FLAG[model]
    repo = shlex.quote(paths.repo)
    activate = shlex.quote(paths.activate)
    marker = shlex.quote(paths.marker(model))
    outfile = f"{setup_dir.rstrip('/')}/spack-setup-%j.out"

    account_line = f"#SBATCH -A {slurm.account.strip()}" if slurm.account.strip() else ""
    mail_lines = (
        "#SBATCH --mail-type=BEGIN,END,FAIL\n#SBATCH --mail-user=" + slurm.mail.strip()
        if slurm.mail.strip() else ""
    )

    return f"""#!/bin/bash
#SBATCH -J ICESEE-Spack-setup
#SBATCH -t {slurm.time}
#SBATCH -N {int(slurm.nodes)}
#SBATCH --ntasks={int(slurm.ntasks)}
#SBATCH -p {slurm.partition}
#SBATCH --mem={slurm.mem}
{account_line}
{mail_lines}
#SBATCH -o {outfile}

set -euo pipefail

echo "[spack-setup] host=$(hostname) date=$(date)"
echo "[spack-setup] model={model} repo={paths.repo}"

{ensure_repo_script(paths=paths, repo_url=repo_url, update=True)}

echo "[spack-setup] running scripts/install.sh {flag}"
cd {repo}
./scripts/install.sh {flag}
echo "[spack-setup] install.sh finished"

echo "[spack-setup] deep verification ({model})"
source {activate}
{_model_deep_verify_fragment(model, matlab_license=matlab_license)}

date -u +%Y-%m-%dT%H:%M:%SZ > {marker}
echo "deep-verified model={model}" >> {marker}
echo "[spack-setup] READY model={model}"
"""


# ── classification ───────────────────────────────────────────────────────────
_MARKER_RE = re.compile(r"CRYOSTACK_ENV_([A-Z_]+)=(\S+)")


def parse_probe(stdout: str) -> dict:
    return {k.lower(): v for k, v in _MARKER_RE.findall(stdout or "")}


def classify_probe(stdout: str, *, model: str, ok: bool = True) -> EnvReport:
    model = _require_model(model)
    m = parse_probe(stdout)
    msgs: list[str] = []

    if m.get("repo") != "present":
        return EnvReport(EnvStatus.NOT_INSTALLED, model,
                         ("ICESEE-Spack is not installed on this resource.",), m)

    activate = m.get("activate", "")
    if not activate.startswith("ok"):
        why = activate.split(":", 1)[1] if ":" in activate else "activation failed"
        return EnvReport(EnvStatus.REPO_ONLY, model,
                         (f"ICESEE-Spack checkout present but not usable ({why}).",), m)

    model_state = m.get("model", "")
    if model_state != "ok":
        why = model_state.split(":", 1)[1] if ":" in model_state else "not built"
        return EnvReport(EnvStatus.REPO_ONLY, model,
                         (f"ICESEE-Spack is not built for {model.upper()} ({why}).",), m)

    if not ok:
        msgs.append("[warn] probe transport reported a non-zero result")
    return EnvReport(EnvStatus.READY, model,
                     tuple(msgs) + (f"ICESEE-Spack is ready for {model.upper()}.",), m)


def deep_verify_ok(setup_log_text: str) -> bool:
    return "CRYOSTACK_ENV_DEEP=ok" in (setup_log_text or "")

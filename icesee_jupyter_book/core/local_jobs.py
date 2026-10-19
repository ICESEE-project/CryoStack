"""Local ICESEE runs as background jobs.

A local run used to execute inside the browser session's kernel and block it
until the model finished. Here a run is a detached process group (its own
session), writing ``run.log`` in the run directory and its exit status to
``.icesee-exit-code`` when it ends, so

* the page stays responsive and can poll the job,
* a page reload or a new kernel can find the job again (``.icesee-job.json``
  records pid, process start time and container name), and
* the final state never depends on the launcher having watched the process.

Two environments run the same ``run_da_<model>.py -F params.yaml``:

* ``native``    -- the launcher's own Python (as before), for examples whose
  model runs in pure Python (Lorenz);
* ``container`` -- the ICESEE runtime image on this host's Docker (the image
  Remote and Cloud runs use), with the launcher's ICESEE checkout mounted
  read-only, no network, and only the run directory writable. Needed for
  Firedrake/Icepack.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .paths import EXT

JOB_FILE = ".icesee-job.json"
EXIT_FILE = ".icesee-exit-code"
CANCEL_FILE = ".icesee-cancel-requested"
STALLED_FILE = ".icesee-stalled"
#: ICESEE's parallel modes can leave one MPI rank waiting forever after another
#: failed; a run whose output reported an error and then stays silent this
#: long is stopped and failed rather than shown as running indefinitely
STALL_AFTER_ERROR_S = 90
LOG_FILE = "run.log"
DEFAULT_IMAGE = "bkyanjo/icesee-combined:v1.0.2"
IMAGE_ENV = "CRYOSTACK_ICESEE_LOCAL_IMAGE"
CONTAINER_ENV = "CRYOSTACK_ICESEE_LOCAL_CONTAINER"      # "0" disables the container environment
CONTAINER_MEMORY_ENV = "CRYOSTACK_ICESEE_LOCAL_MEMORY"  # e.g. "8g"
#: container venv per model (the image keeps Firedrake out of venv-icesee)
CONTAINER_VENV = {"icepack": "/opt/venv-icepack", "firedrake": "/opt/venv-firedrake"}
#: how ICESEE's driver reports a failure it then swallows ("Error in serial /
#: partial / full parallel run mode: ...")
_FAIL_MARKER = re.compile(r"Error in [\w ]*?run mode")
_PROGRESS = re.compile(r"Assimilation progress \((\d+) ranks?\):\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)")
_STAGES = (
    ("Generating true state", "Generating the true state"),
    ("Generating nurged state", "Generating the background (wrong) state"),
    ("Generating synthetic observations", "Generating synthetic observations"),
    ("Assimilation progress", "Assimilating observations"),
    ("Writing data to", "Writing outputs"),
    ("icepack_mesh", "Post-processing"),
)


# ─────────────────────────────────────────────────────────────────────────────
# environments
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Environment:
    kind: str                # "native" | "container"
    label: str
    available: bool
    reason: str = ""
    image: str = ""


_docker_cache: dict = {}


def container_image() -> str:
    return (os.environ.get(IMAGE_ENV) or DEFAULT_IMAGE).strip()


def _docker_status(image: str) -> tuple[bool, str]:
    now = time.monotonic()
    cached = _docker_cache.get(image)
    if cached and now - cached[0] < 120:
        return cached[1]
    if (os.environ.get(CONTAINER_ENV) or "1").strip() in ("0", "false", "no", "off"):
        result = (False, "local container runs are disabled on this server")
    elif not shutil.which("docker"):
        result = (False, "Docker is not installed on this server")
    else:
        try:
            p = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                               capture_output=True, text=True, timeout=15)
            result = (True, "") if p.returncode == 0 else (False, f"the ICESEE image {image} is not on this server")
        except (OSError, subprocess.SubprocessError) as exc:
            result = (False, f"Docker is not reachable ({type(exc).__name__})")
    _docker_cache[image] = (now, result)
    return result


def _native_supports(model: str) -> tuple[bool, str]:
    import importlib.util

    if model == "icepack" and importlib.util.find_spec("firedrake") is None:
        return False, "Icepack needs Firedrake, which the launcher's Python does not have"
    if model == "issm" and importlib.util.find_spec("matlab") is None:
        return False, "ISSM needs ISSM and a MATLAB licence, which this server does not have"
    return True, ""


def environments(model: str) -> list[Environment]:
    """The local environments this server offers for ``model``."""
    ok, why = _native_supports(model)
    native = Environment("native", "Launcher Python (native)", ok, why)
    image = container_image()
    c_ok, c_why = _docker_status(image)
    if c_ok and model == "issm":
        c_ok, c_why = False, "ISSM runs need a MATLAB licence, which local containers do not have"
    container = Environment("container", f"ICESEE container ({image.split('/')[-1]})", c_ok, c_why, image)
    return [native, container]


# ─────────────────────────────────────────────────────────────────────────────
# commands
# ─────────────────────────────────────────────────────────────────────────────
def native_command(run_script: Path, params_file: Path) -> tuple[list[str], dict]:
    """``python run_da_<model>.py -F params.yaml`` with the launcher's ICESEE
    first on the path (local_runner.force_external_icesee_env)."""
    from .local_runner import force_external_icesee_env

    env, _ = force_external_icesee_env()
    # local runs never need AWS; keep the server's AWS identity away from them
    env = {k: v for k, v in env.items() if not k.startswith("AWS_")}
    env["MPLBACKEND"] = "Agg"
    env["PYTHONUNBUFFERED"] = "1"
    return [sys.executable, str(run_script), "-F", str(params_file)], env


def container_command(*, run_dir: Path, staged_example: Path, run_script: Path, model: str,
                      run_id: str, np: int = 1, nens: int | None = None, model_nprocs: int = 0,
                      image: str | None = None, post_mesh: bool = False) -> tuple[list[str], dict, str]:
    """``docker run`` of the ICESEE image: the run directory is the only
    writable mount, ICESEE comes read-only from this launcher's checkout,
    there is no network. Returns (argv, env, container name)."""
    image = image or container_image()
    name = f"icesee-{re.sub(r'[^a-zA-Z0-9_.-]', '-', run_id)}"[:63]
    mount = "/icesee-run"
    rel_example = staged_example.relative_to(run_dir)
    venv = CONTAINER_VENV.get(model)
    activate = f"export PATH={venv}/bin:$PATH; " if venv else ""
    args = ["-F", f"{mount}/params.yaml"]
    if nens:
        args.append(f"--Nens={int(nens)}")
    args += [f"--model_nprocs={int(model_nprocs)}", "--verbose"]
    inner = (
        ". /opt/set_persistent_dir.sh; . /opt/runtime-env/icesee-env.sh; " + activate
        + f"mpirun --allow-run-as-root -np {int(np)} python {shlex.quote(run_script.name)} "
        + " ".join(shlex.quote(a) for a in args) + "; rc=$?; "
    )
    if post_mesh:
        data = f"{mount}/{rel_example}/_modelrun_datasets"
        inner += (f"if [ $rc -eq 0 ]; then echo '[launcher] post-processing: icepack_mesh'; "
                  f"(cd /opt && python -m ICESEE.src.postprocessing.icepack_mesh {mount}/params.yaml {data}) "
                  f"|| echo '[launcher] WARNING: mesh coordinates were not exported; maps will be unavailable'; fi; ")
    inner += "exit $rc"
    argv = ["docker", "run", "--rm", "--name", name, "--network", "none",
            "--security-opt", "no-new-privileges",
            "-e", "HOME=/tmp", "-e", "OMPI_MCA_rmaps_base_oversubscribe=1", "-e", "PYTHONUNBUFFERED=1",
            "-v", f"{EXT}:/opt/ICESEE:ro", "-v", f"{run_dir}:{mount}",
            "-w", f"{mount}/{rel_example}"]
    memory = (os.environ.get(CONTAINER_MEMORY_ENV) or "").strip()
    if memory:
        argv += ["--memory", memory]
    argv += [image, "bash", "-c", inner]
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    return argv, env, name


# ─────────────────────────────────────────────────────────────────────────────
# jobs
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class JobStatus:
    state: str                        # running | completed | failed | cancelled
    returncode: int | None = None
    detail: str = ""
    progress: float | None = None     # 0..1 of the assimilation loop
    step: tuple | None = None         # (k, n)
    stage: str = ""
    elapsed: float = 0.0
    warnings: list = field(default_factory=list)


def _proc_start_time(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat[stat.rindex(")") + 2:].split()
        if fields[0] == "Z":
            return None
        return fields[19]
    except (OSError, ValueError, IndexError):
        return None


class LocalJob:
    """One local run's process, identified by its run directory."""

    _children: dict = {}               # pid -> Popen, so the kernel reaps its children

    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir)
        self.meta = self._read_meta()

    def _read_meta(self) -> dict:
        try:
            return json.loads((self.run_dir / JOB_FILE).read_text())
        except (OSError, ValueError):
            return {}

    @property
    def exists(self) -> bool:
        return bool(self.meta.get("pid"))

    @classmethod
    def start(cls, *, run_dir: Path, command: list[str], cwd: Path, env: dict, backend: str,
              container: str = "", post: list[str] | None = None) -> "LocalJob":
        run_dir = Path(run_dir)
        log = run_dir / LOG_FILE
        exit_file = run_dir / EXIT_FILE
        for stale in (exit_file, run_dir / CANCEL_FILE, run_dir / STALLED_FILE):
            stale.unlink(missing_ok=True)
        script = f"{shlex.join(command)} >> {shlex.quote(str(log))} 2>&1; rc=$?; "
        if post:
            script += (f"if [ $rc -eq 0 ]; then {shlex.join(post)} >> {shlex.quote(str(run_dir / 'postprocess.log'))}"
                       " 2>&1 || true; fi; ")
        script += (f"printf '%s' $rc > {shlex.quote(str(exit_file))}.tmp && "
                   f"mv {shlex.quote(str(exit_file))}.tmp {shlex.quote(str(exit_file))}")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"[launcher] {datetime.now().isoformat(timespec='seconds')} start ({backend})\n"
                    f"[launcher] command: {shlex.join(command)}\n")
        proc = subprocess.Popen(["bash", "-c", script], cwd=str(cwd), env=env, start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls._children[proc.pid] = proc
        meta = {"pid": proc.pid, "pgid": proc.pid, "proc_start": _proc_start_time(proc.pid),
                "started": time.time(), "started_iso": datetime.now().isoformat(timespec="seconds"),
                "backend": backend, "container": container, "command": command}
        tmp = run_dir / (JOB_FILE + ".tmp")
        tmp.write_text(json.dumps(meta))
        os.replace(tmp, run_dir / JOB_FILE)
        job = cls(run_dir)
        return job

    # ── state ─────────────────────────────────────────────────────────────
    def _alive(self) -> bool:
        pid = self.meta.get("pid")
        if not pid:
            return False
        child = self._children.get(pid)
        if child is not None and child.poll() is not None:
            self._children.pop(pid, None)
            return False
        start = _proc_start_time(pid)
        return start is not None and start == self.meta.get("proc_start")

    def returncode(self) -> int | None:
        try:
            return int((self.run_dir / EXIT_FILE).read_text().strip())
        except (OSError, ValueError):
            return None

    def poll(self, *, model_name: str = "") -> JobStatus:
        elapsed = time.time() - float(self.meta.get("started") or time.time())
        rc = self.returncode()
        tail = self.tail(96 * 1024)
        progress = parse_progress(tail)
        stalled = self.run_dir / STALLED_FILE
        if rc is None and self._alive():
            if not stalled.is_file() and self._stalled_after_error(tail):
                stalled.write_text(self._error_line(tail))
                self._stop_processes()
            else:
                return JobStatus("running", elapsed=elapsed, **progress)
        if stalled.is_file():
            return JobStatus("failed", rc, "the model reported an error and then stopped making progress; the "
                             f"run was stopped ({stalled.read_text().strip()[:200]})", elapsed=elapsed, **progress)
        cancelled = (self.run_dir / CANCEL_FILE).is_file()
        if cancelled:
            return JobStatus("cancelled", rc, "cancelled by the user", elapsed=elapsed, **progress)
        if rc is None:
            return JobStatus("failed", None, "the run's process ended without reporting an exit status "
                             "(the server may have restarted)", elapsed=elapsed, **progress)
        if rc != 0:
            return JobStatus("failed", rc, f"the model exited with status {rc}", elapsed=elapsed, **progress)
        return self._judge_success(rc, elapsed, model_name, progress)

    def _stalled_after_error(self, tail: str) -> bool:
        if not _FAIL_MARKER.search(tail):
            return False
        try:
            quiet = time.time() - (self.run_dir / LOG_FILE).stat().st_mtime
        except OSError:
            return False
        return quiet > STALL_AFTER_ERROR_S

    @staticmethod
    def _error_line(text: str) -> str:
        return next((ln.strip() for ln in reversed(text.splitlines())
                     if re.search(r"(Error|Exception)\b", ln) and "Traceback" not in ln), "")

    def _judge_success(self, rc, elapsed, model_name, progress) -> JobStatus:
        """Exit status 0 is not proof of success: ICESEE's driver catches
        errors and returns normally. Errors in the log fail the run unless
        the run's outputs were written after it started (Firedrake/MPI may
        print a traceback while shutting down)."""
        text = self.full_log()
        found = _FAIL_MARKER.search(text)
        hard = found.group(0) if found else None
        trace = "Traceback (most recent call last)" in text
        if not hard and not trace:
            return JobStatus("completed", rc, "", elapsed=elapsed, **progress)
        started = float(self.meta.get("started") or 0)
        written = [p for p in self.run_dir.rglob(f"true-wrong-{model_name or '*'}.h5")
                   if p.stat().st_mtime >= started]
        if written and not hard:
            return JobStatus("completed", rc, "", elapsed=elapsed,
                             warnings=["the model printed an error while shutting down; its outputs were written"],
                             **progress)
        line = next((ln for ln in reversed(text.splitlines()) if "Error" in ln or "Exception" in ln), hard or "")
        return JobStatus("failed", rc, f"the model reported an error: {line.strip()[:240]}", elapsed=elapsed,
                         **progress)

    # ── control ───────────────────────────────────────────────────────────
    def cancel(self) -> bool:
        if not self.exists or self.returncode() is not None:
            return False
        (self.run_dir / CANCEL_FILE).write_text(datetime.now().isoformat(timespec="seconds"))
        self._stop_processes()
        return True

    def _stop_processes(self) -> None:
        """Stop the job's container (if any) and its process group."""
        container = self.meta.get("container")
        if container:
            try:
                subprocess.run(["docker", "stop", "-t", "10", container], capture_output=True, timeout=40)
            except (OSError, subprocess.SubprocessError):
                pass
        pgid = self.meta.get("pgid")
        if pgid and self._alive():
            try:
                os.killpg(int(pgid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.time() + 10
            while time.time() < deadline and self._alive():
                time.sleep(0.2)
            if self._alive():
                try:
                    os.killpg(int(pgid), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    # ── logs ──────────────────────────────────────────────────────────────
    def tail(self, nbytes: int = 64 * 1024) -> str:
        path = self.run_dir / LOG_FILE
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - nbytes))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def full_log(self, limit: int = 8 * 1024 * 1024) -> str:
        return self.tail(limit)


def parse_progress(text: str) -> dict:
    """The latest assimilation step and stage from ICESEE's console output
    (tqdm rewrites its line with carriage returns)."""
    out = {"progress": None, "step": None, "stage": ""}
    matches = list(_PROGRESS.finditer(text))
    if matches:
        m = matches[-1]
        k, n = int(m.group(3)), int(m.group(4))
        out["progress"] = (k / n) if n else None
        out["step"] = (k, n)
    best = -1
    for needle, label in _STAGES:
        pos = text.rfind(needle)
        if pos > best:
            best, out["stage"] = pos, label
    return out


def clean_log(text: str) -> str:
    """Log text for display: progress-bar redraws collapsed to their last
    state, ANSI colour codes removed."""
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    lines = []
    for raw in text.split("\n"):
        parts = [p for p in raw.split("\r") if p.strip()]
        lines.append(parts[-1] if parts else "")
    return "\n".join(lines)


class JobMonitor:
    """Polls a job on a background thread and reports changes; stops at the
    end of the run (calling ``on_finish`` once)."""

    def __init__(self, job: LocalJob, *, on_update, on_finish, interval: float = 1.0, model_name: str = ""):
        self.job, self.on_update, self.on_finish = job, on_update, on_finish
        self.interval, self.model_name = interval, model_name
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"icesee-job-{job.run_dir.name}", daemon=True)

    def start(self) -> "JobMonitor":
        self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                status = self.job.poll(model_name=self.model_name)
            except Exception as exc:  # noqa: BLE001 -- a monitor must never die silently
                status = JobStatus("running", detail=f"status unavailable: {exc}")
            try:
                if status.state == "running":
                    self.on_update(status)
                else:
                    self.on_finish(status)
                    return
            except Exception:  # noqa: BLE001 -- a UI callback error must not stop monitoring
                pass
            self._stop.wait(self.interval)

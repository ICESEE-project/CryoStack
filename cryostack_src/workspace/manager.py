from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from IPython.display import HTML, Image, display

from .files import list_editable_files
from .identity import WorkspaceUser, resolve_workspace_user
from .manifest import MANIFEST_NAME, read_manifest, write_manifest
from .models import RunInfo

_SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_EXAMPLE_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
#: optional deploy-time pin for the workspace root, independent of process cwd
WORKSPACE_ROOT_ENV = "CRYOSTACK_WORKSPACE_ROOT"


class WorkspacePermissionError(RuntimeError):
    """A file operation was attempted outside the caller's managed workspace."""


class StagedExample:
    """A user-owned working copy of an example, staged for a run.

    The canonical example is never touched: when ``source`` is a bundled
    (canonical) example a fresh copy is made under the authenticated user's
    workspace; when ``source`` is already user-owned it is used in place.
    """

    __slots__ = ("path", "source", "from_canonical", "provenance")

    def __init__(self, *, path: Path, source: str, from_canonical: bool, provenance: dict) -> None:
        self.path = path
        self.source = source
        self.from_canonical = from_canonical
        self.provenance = provenance


class WorkspaceManager:
    """Own CryoLauncher workspace and result filesystem operations."""

    def __init__(
        self,
        *,
        status,
        session,
        example_dir,
        model,
        backend,
        file_picker,
        file_editor,
        log_output,
        results_output,
        cluster_host,
        cluster_user,
        cluster_port,
        access_mode,
        normalize_remote_path,
        connector_fetch_archive,
        should_use_connector,
        connector_ssh,
        ssh_run,
        cluster_name,
        owner: WorkspaceUser | None = None,
        workspace_root: str | Path | None = None,
        require_authenticated: bool = True,
    ) -> None:
        self.status = status
        self.session = session
        self.example_dir = example_dir
        self.model = model
        self.backend = backend
        self.file_picker = file_picker
        self.file_editor = file_editor
        self.log_output = log_output
        self.results_output = results_output
        self.cluster_host = cluster_host
        self.cluster_user = cluster_user
        self.cluster_port = cluster_port
        self.access_mode = access_mode
        self.normalize_remote_path = normalize_remote_path
        self.connector_fetch_archive = connector_fetch_archive
        self.should_use_connector = should_use_connector
        self.connector_ssh = connector_ssh
        self.ssh_run = ssh_run
        self.cluster_name = cluster_name

        # ---- per-user Workspace isolation -------------------------------
        # The run history is confined to <workspace-root>/users/<safe-id>/...
        # for exactly one authenticated CryoStack user. All discovery and all
        # per-run operations stay inside this subtree; a run id owned by
        # another user is simply absent from self._runs and every method
        # short-circuits.
        self.owner: WorkspaceUser = (
            owner
            if owner is not None
            else resolve_workspace_user(require_authenticated=require_authenticated)
        )
        if workspace_root is not None:
            root = Path(workspace_root).resolve()
        else:
            env_root = (os.environ.get(WORKSPACE_ROOT_ENV) or "").strip()
            root = Path(env_root).resolve() if env_root else Path.cwd().resolve()
        self._workspace_root = root
        self._owner_root = (root / "users" / self.owner.safe_id).resolve()
        self.manifest_root = (self._owner_root / ".cryostack" / "runs").resolve()
        #: derived, rebuildable working copies of examples staged for a run
        self._working_root = (self._owner_root / ".cryostack" / "working").resolve()
        #: user-owned example checkouts:  <owner>/examples/<model>/<name>
        self._examples_root = (self._owner_root / "examples").resolve()
        #: user-owned reusable datasets:  <owner>/datasets/...
        self._datasets_root = (self._owner_root / "datasets").resolve()
        if not self.manifest_root.is_relative_to(self._owner_root):
            raise RuntimeError("Workspace namespace escaped its user root.")

        self._runs: dict[str, RunInfo] = {}
        self._selected_run_id: str | None = None
        self._tail_handler = None
        self._status_resolver = None

    def _owns(self, path: Path | None) -> bool:
        """True when ``path`` resolves inside this user's managed run root."""
        if path is None:
            return False
        try:
            return path.resolve().is_relative_to(self.manifest_root)
        except (OSError, ValueError):
            return False

    def set_tail_handler(self, handler) -> None:
        self._tail_handler = handler

    def set_status_resolver(self, resolver) -> None:
        self._status_resolver = resolver

    def reconcile_run(self, run_id: str) -> RunInfo | None:
        run = self._runs.get(run_id)
        if not run or not run.jobid or self._status_resolver is None:
            return run
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        try:
            state = self._status_resolver(run)
        except Exception:
            return run
        return self.update_run_status(run_id, state)

    def update_run_status(self, run_id: str, state: str | None) -> RunInfo | None:
        run = self._runs.get(run_id)
        normalized = str(state or "").strip().lower()
        if not run or normalized not in {"submitted", "queued", "running", "completed", "failed", "cancelled"}:
            return run
        if run.status != normalized:
            run.status = normalized
            run.finished = datetime.now() if normalized in {"completed", "failed", "cancelled"} else None
            if run.workspace_directory:
                write_manifest(run, run.workspace_directory)
        return run

    def update_run_status_by_job(self, job_id: str, state: str | None) -> RunInfo | None:
        run = next((item for item in self._runs.values() if str(item.jobid) == str(job_id)), None)
        return self.update_run_status(run.id, state) if run else None

    def tail(self, run_id: str):
        run = self.select_run(run_id)
        if not run:
            return None
        if self._tail_handler is None:
            raise RuntimeError("Workspace log routing is not configured.")
        return self._tail_handler()

    def list_editable_files(self, example_path: str) -> list[tuple[str, str]]:
        return list_editable_files(example_path)

    # ------------------------------------------------------------------
    # Generic, model-neutral file operations (containment enforced here)
    # ------------------------------------------------------------------
    _SAFE_SEGMENT = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")

    def _safe_segment(self, name: str) -> str:
        name = (name or "").strip()
        if name in {".", ".."} or "/" in name or "\\" in name \
                or not self._SAFE_SEGMENT.match(name):
            raise ValueError(f"Unsafe name: {name!r}")
        return name

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            return path.resolve().is_relative_to(root.resolve())
        except (OSError, ValueError, RuntimeError):
            return False

    def is_user_owned(self, path: str | Path | None) -> bool:
        """True when ``path`` resolves inside this authenticated user's workspace."""
        return self._is_user_owned_path(Path(path)) if path not in (None, "") else False

    def resolve_user_file(self, path: str | Path, *, must_exist: bool = False) -> Path:
        """Resolve ``path`` and require it to sit inside this user's workspace."""
        try:
            rp = Path(path).expanduser().resolve()
        except (OSError, RuntimeError):
            raise WorkspacePermissionError(f"Cannot resolve path: {path!r}")
        if not rp.is_relative_to(self._owner_root):
            raise WorkspacePermissionError(
                "This file is outside your workspace and cannot be modified. "
                "Clone the example to your workspace first."
            )
        if must_exist and not rp.is_file():
            raise FileNotFoundError(f"No such file: {rp}")
        return rp

    #: files larger than this are not loaded into the editor buffer
    MAX_EDITABLE_BYTES = 2 * 1024 * 1024

    def read_text_file(self, path: str | Path) -> str:
        """Read a text file the user is allowed to view (their workspace or the
        currently selected example tree). Never leaves those trees."""
        p = Path(path).expanduser().resolve()
        roots = [self._owner_root]
        example = self.example_root()
        if example is not None:
            roots.append(example.resolve())
        if not any(self._within(p, r) for r in roots):
            raise WorkspacePermissionError("File is outside the current workspace/example.")
        if not p.is_file():
            raise FileNotFoundError(str(p))
        if p.stat().st_size > self.MAX_EDITABLE_BYTES:
            raise WorkspacePermissionError(
                f"File is too large to edit here ({p.stat().st_size // 1024} KB)."
            )
        return p.read_text(encoding="utf-8")

    def save_text_file(self, path: str | Path, text: str) -> Path:
        rp = self.resolve_user_file(path)
        if rp.exists() and not rp.is_file():
            raise WorkspacePermissionError("Target is not a regular file.")
        if not rp.parent.is_dir():
            raise FileNotFoundError(f"Directory does not exist: {rp.parent}")
        rp.write_text(text, encoding="utf-8")
        return rp

    def create_text_file(self, directory: str | Path, name: str, text: str = "") -> Path:
        d = self.resolve_user_file(directory)
        if not d.is_dir():
            raise FileNotFoundError(f"Directory does not exist: {d}")
        target = self.resolve_user_file(d / self._safe_segment(name))
        if target.exists():
            raise FileExistsError(f"Already exists: {target.name}")
        target.write_text(text, encoding="utf-8")
        return target

    def delete_user_file(self, path: str | Path) -> Path:
        rp = self.resolve_user_file(path, must_exist=True)
        if not rp.is_file():
            raise WorkspacePermissionError("Only regular files can be deleted here.")
        rp.unlink()
        return rp

    def user_examples_root(self, model: str | None = None) -> Path:
        root = self._examples_root
        if model:
            root = (root / self._safe_segment(str(model).strip().lower())).resolve()
        return root

    def clone_example_to_workspace(
        self, *, source: str | Path, model: str | None, name: str | None = None
    ) -> Path:
        """Copy an example (canonical or otherwise) into this user's workspace.

        Result: ``<owner>/examples/<model>/<name>`` -- fully user-owned and
        editable. The source is never modified.
        """
        try:
            src = Path(source).expanduser().resolve()
        except (OSError, RuntimeError):
            raise ValueError(f"Cannot resolve example path: {source!r}")
        if not src.is_dir():
            raise ValueError(f"Not an example directory: {src}")

        dest_root = self.user_examples_root(model)
        dest = (dest_root / self._safe_example_name(name or src.name)).resolve()
        if not dest.is_relative_to(self._examples_root):
            raise WorkspacePermissionError("Clone target escaped the workspace.")
        if dest.exists():
            raise FileExistsError(
                f"A workspace example named {dest.name!r} already exists."
            )
        dest_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        (dest / ".cryostack-example.json").write_text(
            json.dumps(
                {
                    "kind": "cryostack-user-example",
                    "source": str(src),
                    "source_name": src.name,
                    "model": (str(model).strip().lower() or None) if model else None,
                    "owner": self.owner.safe_id,
                    "created": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2, sort_keys=True,
            ),
            encoding="utf-8",
        )
        return dest

    def example_root(self) -> Path | None:
        path = Path(self.example_dir.value).expanduser()
        if path.exists():
            return path if path.is_dir() else path.parent
        return None

    # ------------------------------------------------------------------
    # Per-user example staging (canonical examples are read-only)
    # ------------------------------------------------------------------
    def _is_user_owned_path(self, path: Path | None) -> bool:
        """True when ``path`` resolves inside this authenticated user's workspace."""
        if path is None:
            return False
        try:
            return path.resolve().is_relative_to(self._owner_root)
        except (OSError, ValueError):
            return False

    @staticmethod
    def _safe_example_name(name: str) -> str:
        name = (name or "").strip()
        if name in {".", ".."} or not _SAFE_EXAMPLE_NAME.match(name):
            raise ValueError(f"Unsafe example name: {name!r}")
        return name

    def stage_example_for_md_overrides(
        self,
        *,
        source_example: str | Path,
        override_script: str,
        overrides: dict,
        entrypoint: str = "runme.m",
        entrypoint_transform=None,
    ) -> StagedExample:
        """Return a user-owned working copy of ``source_example`` with the
        Basic-mode override step injected before its first ``solve(...)``.

        * canonical example  -> a fresh copy is built under
          ``<owner_root>/.cryostack/working/<name>`` (rebuilt each run, so the
          injection is deterministic and never doubled);
        * user-owned example -> operated on in place.

        The canonical example is never modified. Provenance is written to
        ``.cryostack-example.json`` inside the working copy.
        """
        src = Path(source_example).expanduser().resolve()
        if not src.exists() or not src.is_dir():
            raise ValueError(f"Example directory not found: {src}")

        if self._is_user_owned_path(src):
            target = src
            from_canonical = False
        else:
            name = self._safe_example_name(src.name)
            self._working_root.mkdir(parents=True, exist_ok=True)
            target = (self._working_root / name).resolve()
            if not target.is_relative_to(self._working_root):
                raise ValueError("Working copy escaped the user workspace.")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
            from_canonical = True

        (target / "cryostack_md_overrides.m").write_text(override_script, encoding="utf-8")

        entry = target / entrypoint
        if entrypoint_transform is not None and entry.is_file():
            entry.write_text(
                entrypoint_transform(entry.read_text(encoding="utf-8")), encoding="utf-8"
            )

        provenance = {
            "kind": "cryostack-working-copy",
            "source": str(src),
            "source_name": src.name,
            "from_canonical": from_canonical,
            "owner": self.owner.safe_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "entrypoint": entrypoint,
            "md_overrides": dict(overrides or {}),
        }
        (target / ".cryostack-example.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True), encoding="utf-8"
        )
        return StagedExample(
            path=target, source=str(src), from_canonical=from_canonical, provenance=provenance
        )

    def delete(self, path: Path) -> None:
        """Delete one explicitly resolved workspace path."""
        path = Path(path)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def register_run(self, run: RunInfo) -> RunInfo:
        if not _SAFE_RUN_ID.match(run.id or ""):
            raise ValueError(f"Unsafe run id: {run.id!r}")
        workspace = (self.manifest_root / run.id).resolve()
        if not workspace.is_relative_to(self.manifest_root):
            raise ValueError(f"Run id escapes the managed workspace: {run.id!r}")
        run.workspace_directory = workspace
        write_manifest(run, workspace)
        self._runs[run.id] = run
        return run

    def refresh(self) -> list[RunInfo]:
        discovered: dict[str, RunInfo] = {}
        if self.manifest_root.exists():
            for path in sorted(self.manifest_root.glob(f"*/{MANIFEST_NAME}")):
                try:
                    run = read_manifest(path)
                    if run.id not in discovered or run.created > discovered[run.id].created:
                        discovered[run.id] = run
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        self._runs = discovered
        if self._selected_run_id not in discovered:
            self._selected_run_id = None
        for run in tuple(discovered.values()):
            self.reconcile_run(run.id)
        return self.list_runs()

    def list_runs(self) -> list[RunInfo]:
        return sorted(self._runs.values(), key=lambda run: run.created, reverse=True)

    def select_run(self, run_id: str) -> RunInfo | None:
        run = self._runs.get(run_id)
        self._selected_run_id = run.id if run else None
        if run:
            self.status.update(
                jobid=run.jobid,
                remote_dir=str(run.remote_directory) if run.remote_directory else None,
                log_file=str(run.log_file) if run.log_file else None,
                batch_job_id=run.jobid if run.execution_mode == "cloud" else self.status.get("batch_job_id"),
                cloud_run=run.metadata.get("cloud_run"),
            )
            for widget, key in (
                (self.cluster_host, "host"),
                (self.cluster_user, "user"),
                (self.cluster_port, "port"),
                (self.access_mode, "access_mode"),
                (self.cluster_name, "cluster_name"),
            ):
                if run.metadata.get(key) not in (None, ""):
                    widget.value = run.metadata[key]
            model_values = [item[1] if isinstance(item, tuple) else item for item in self.model.options]
            backend_values = [item[1] if isinstance(item, tuple) else item for item in self.backend.options]
            if run.model in model_values:
                self.model.value = run.model
            if run.backend in backend_values:
                self.backend.value = run.backend
        return run

    def selected_run(self) -> RunInfo | None:
        return self._runs.get(self._selected_run_id or "")

    def files(self, run_id: str) -> list[Path]:
        run = self._runs.get(run_id)
        if not run or not self._owns(run.workspace_directory) or not run.workspace_directory.exists():
            return []
        return sorted(path for path in run.workspace_directory.rglob("*") if path.is_file())

    def delete_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory:
            return False
        workspace = run.workspace_directory.resolve()
        if not self._owns(workspace):
            return False
        manifest = workspace / MANIFEST_NAME
        try:
            verified = read_manifest(manifest)
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if verified.id != run_id or workspace == self.manifest_root:
            return False
        shutil.rmtree(workspace)
        self._runs.pop(run_id, None)
        if self._selected_run_id == run_id:
            self._selected_run_id = None
        return True

    def preview_results_for_run(self, run_id: str) -> None:
        if self.select_run(run_id):
            self.preview_results()

    def download_results_for_run(self, run_id: str) -> None:
        if self.select_run(run_id):
            self.download_results()

    def download_figures_for_run(self, run_id: str) -> None:
        if self.select_run(run_id):
            self.download_figures()

    def clone_example(self, new_name: str) -> Path | None:
        self.log_output.clear_output()
        source = Path(self.example_dir.value).expanduser()
        if not source.exists():
            with self.log_output:
                print("[advanced][ERROR] Source example path does not exist.")
            return None
        if not new_name:
            with self.log_output:
                print("[advanced][ERROR] Provide a new example name first.")
            return None
        try:
            if source.is_file():
                destination = source.parent / new_name
                if destination.suffix == "":
                    destination = destination.with_suffix(source.suffix)
                destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                destination = source.parent / new_name
                if destination.exists():
                    with self.log_output:
                        print(f"[advanced][ERROR] Target already exists: {destination}")
                    return None
                shutil.copytree(source, destination)
            with self.log_output:
                print(f"[advanced] New example created: {destination}")
            return destination
        except Exception as error:
            with self.log_output:
                print("[advanced][ERROR]", type(error).__name__, error)
            return None

    def save_uploaded_datasets(self, value) -> None:
        self.log_output.clear_output()
        root = self.example_root()
        if root is None:
            with self.log_output:
                print("[upload][ERROR] Example directory is not available.")
            return
        if not value:
            with self.log_output:
                print("[upload] No files selected.")
            return
        target_dir = root / "_uploaded_datasets"
        target_dir.mkdir(parents=True, exist_ok=True)
        saved = 0
        try:
            if isinstance(value, dict):
                items = value.items()
            else:
                items = []
                for item in value:
                    name = item.get("name", "uploaded_file")
                    items.append((name, item))
            for name, metadata in items:
                content = metadata["content"] if isinstance(metadata, dict) else metadata.content
                with open(target_dir / name, "wb") as stream:
                    stream.write(content)
                saved += 1
            with self.log_output:
                print(f"[upload] Saved {saved} file(s) to: {target_dir}")
        except Exception as error:
            with self.log_output:
                print("[upload][ERROR]", type(error).__name__, error)

    def local_run_cache_dir(self) -> Path:
        selected = self.selected_run()
        if selected and selected.workspace_directory:
            cache = selected.workspace_directory / "cache"
            cache.mkdir(parents=True, exist_ok=True)
            return cache
        root = self.example_root()
        return root / "_icesee_remote_runs" / f"{self.model.value}_{self.backend.value}"

    def sync_cloud_results(
        self,
        *,
        s3_uri: str,
        region: str | None = None,
        profile: str | None = None,
    ) -> Path:
        outputs_dir = self.local_run_cache_dir() / "cloud_outputs"
        if outputs_dir.exists():
            self.delete(outputs_dir)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        command = ["aws"]
        if profile:
            command.extend(["--profile", profile])
        if region:
            command.extend(["--region", region])
        command.extend([
            "s3",
            "sync",
            f"{s3_uri.rstrip('/')}/outputs/",
            f"{outputs_dir}/",
        ])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip())
        return outputs_dir

    def remote_outputs_dir(self) -> str:
        remote_dir = self.normalize_remote_path(self.status.get("remote_dir") or "")
        return f"{remote_dir}/outputs"

    def refresh_results(self) -> Path | None:
        remote_dir = self.normalize_remote_path(self.status.get("remote_dir") or "")
        if not remote_dir:
            with self.results_output:
                print("[results] No remote run directory found. Submit a job first.")
            return None
        host = self.cluster_host.value.strip()
        user = self.cluster_user.value.strip()
        port = int(self.cluster_port.value)
        outputs_dir = self.local_run_cache_dir() / "outputs"
        if outputs_dir.exists():
            self.delete(outputs_dir)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        remote_outputs = self.remote_outputs_dir()
        if self.access_mode.value == "connector":
            result = self.connector_fetch_archive(
                self.session["id"], host, user, port,
                f"{remote_outputs.rstrip('/')}/", timeout=600,
            )
            if not result.get("ok"):
                with self.results_output:
                    print("[results][ERROR] Could not fetch remote outputs through connector.")
                    print("Remote source:", remote_outputs)
                    print("FULL RESPONSE:")
                    print(result)
                    print("--- stdout ---")
                    print(result.get("stdout", ""))
                    print("--- stderr ---")
                    print(result.get("stderr", ""))
                return None
            try:
                archive_b64 = result.get("archive_b64")
                if not archive_b64:
                    raise RuntimeError("Connector response did not include archive_b64.")
                with tempfile.TemporaryDirectory() as temp_dir:
                    archive_path = Path(temp_dir) / "outputs.tar.gz"
                    archive_path.write_bytes(base64.b64decode(archive_b64))
                    if outputs_dir.exists():
                        self.delete(outputs_dir)
                    outputs_dir.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(archive_path, "r:gz") as archive:
                        archive.extractall(outputs_dir)
                return outputs_dir
            except Exception as error:
                with self.results_output:
                    print("[results][ERROR] Could not unpack connector archive.")
                    print(type(error).__name__, error)
                return None
        command = [
            "rsync", "-az", "-e", f"ssh -p {port}",
            f"{user}@{host}:{remote_outputs.rstrip('/')}/", f"{outputs_dir}/",
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            with self.results_output:
                print("[results][ERROR] Could not fetch remote outputs.")
                print("Remote source:", remote_outputs)
                print("--- stdout ---")
                print(result.stdout)
                print("--- stderr ---")
                print(result.stderr)
            return None
        return outputs_dir

    @staticmethod
    def _make_zip(source: Path, destination: Path) -> None:
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(source))

    @staticmethod
    def _auto_download(path: Path, filename: str | None = None) -> None:
        path = Path(path).resolve()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        filename = filename or path.name
        stem = Path(filename).stem
        suffix = Path(filename).suffix or ".zip"
        download_name = f"{stem}_{stamp}{suffix}"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        element_id = f"icesee_download_{uuid.uuid4().hex}"
        display(HTML(f'''<div id="{element_id}"></div><script>
        (function() {{ const a = document.createElement("a");
        a.href = "data:application/zip;base64,{data}";
        a.download = "{html.escape(download_name)}"; a.style.display = "none";
        document.body.appendChild(a); setTimeout(() => {{ a.click();
        document.body.removeChild(a); }}, 100); }})();</script>'''))

    def download_results(self, _=None) -> None:
        if isinstance(_, str) and not self.select_run(_):
            return
        self.results_output.clear_output()
        outputs_dir = self.refresh_results()
        if outputs_dir is None:
            return
        zip_path = self.local_run_cache_dir() / "results_bundle.zip"
        try:
            if zip_path.exists():
                self.delete(zip_path)
            self._make_zip(outputs_dir, zip_path)
            if not zipfile.is_zipfile(zip_path):
                raise RuntimeError(f"Created file is not a valid zip: {zip_path}")
            with self.results_output:
                print(f"Preparing download: {zip_path.name}")
                print("If the browser blocks repeated downloads, allow multiple downloads for this page.")
                self._auto_download(zip_path, "results_bundle.zip")
        except Exception as error:
            with self.results_output:
                print("[download][ERROR]", type(error).__name__, error)

    def download_figures(self, _=None) -> None:
        if isinstance(_, str) and not self.select_run(_):
            return
        self.results_output.clear_output()
        outputs_dir = self.refresh_results()
        if outputs_dir is None:
            return
        pngs = sorted(outputs_dir.rglob("*.png"))
        if not pngs:
            with self.results_output:
                print("[download] No PNG figures found.")
                print("Checked recursively under:", outputs_dir)
            return
        figures_dir = self.local_run_cache_dir() / "_figures_only"
        if figures_dir.exists():
            self.delete(figures_dir)
        figures_dir.mkdir(parents=True, exist_ok=True)
        for path in pngs:
            shutil.copy2(path, figures_dir / path.name)
        zip_path = self.local_run_cache_dir() / "figures_bundle.zip"
        try:
            if zip_path.exists():
                self.delete(zip_path)
            self._make_zip(figures_dir, zip_path)
            if not zipfile.is_zipfile(zip_path):
                raise RuntimeError(f"Created file is not a valid zip: {zip_path}")
            with self.results_output:
                print(f"Preparing download: {zip_path.name}")
                print("If the browser blocks repeated downloads, allow multiple downloads for this page.")
                self._auto_download(zip_path, "figures_bundle.zip")
        except Exception as error:
            with self.results_output:
                print("[download][ERROR]", type(error).__name__, error)

    def preview_results(self, _=None) -> None:
        if isinstance(_, str) and not self.select_run(_):
            return
        self.results_output.clear_output()
        remote_check = self.inspect_remote_results()
        outputs_dir = self.refresh_results()
        if outputs_dir is None:
            return
        pngs = sorted(outputs_dir.rglob("*.png"))
        mats = sorted(outputs_dir.rglob("*.mat"))
        h5s = sorted(outputs_dir.rglob("*.h5"))
        all_files = sorted(path for path in outputs_dir.rglob("*") if path.is_file())
        with self.results_output:
            print("Fetched outputs:", outputs_dir)
            print(f"Figures: {len(pngs)}")
            print(f"Model files: {len(mats)}")
            print(f"H5 files: {len(h5s)}\n")
            if all_files:
                print("Output tree:")
                for path in all_files[:40]:
                    print(" -", path.relative_to(outputs_dir))
                print()
            if pngs:
                print("Found figures at:")
                for path in pngs[:10]:
                    print(" -", path)
            if pngs:
                print("Preview figures:")
                for path in pngs:
                    print("\n", path.name)
                    display(Image(filename=str(path)))
            else:
                print("No PNG figures found locally after fetch.\n")
                print("--- Remote inspection ---")
                print((remote_check.stdout or "").strip())
                if (remote_check.stderr or "").strip():
                    print("--- stderr ---")
                    print(remote_check.stderr.strip())

    def inspect_remote_results(self):
        remote_dir = self.normalize_remote_path(self.status.get("remote_dir") or "")
        outputs = f"{remote_dir}/outputs"
        host = self.cluster_host.value.strip()
        user = self.cluster_user.value.strip()
        port = int(self.cluster_port.value)
        command = f'''
        set -e
        echo "[remote] run dir : {remote_dir}"
        echo "[remote] outputs : {outputs}"
        echo

        echo "[remote] output tree:"
        find "{outputs}" -maxdepth 5 -print || true

        echo
        echo "[remote] png/mat/h5 files:"
        find "{outputs}" -maxdepth 6 -type f \\( -name "*.png" -o -name "*.mat" -o -name "*.h5" \\) -print || true
        '''
        if self.should_use_connector():
            payload = self.connector_ssh(
                self.session["id"], host, user, port, command,
                timeout=300,
                cluster_name=self.cluster_name.value or "pace",
            )

            class Result:
                returncode = 0 if payload.get("ok") else 1
                stdout = payload.get("stdout", "")
                stderr = payload.get("stderr", "")

            return Result()
        return self.ssh_run(host, user, port, command, timeout=30)

from __future__ import annotations

import base64
import html
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from IPython.display import HTML, Image, display

from cryostack_src.frontend.cryolauncher.workspace.file_browser import (
    load_selected_file,
    refresh_file_picker,
    save_selected_file,
)
from cryostack_src.frontend.cryolauncher.workspace.tree import list_editable_files
from .manifest import MANIFEST_NAME, read_manifest, write_manifest
from .models import RunInfo


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
        manifest_root: Path | None = None,
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
        self.manifest_root = (manifest_root or (Path.cwd() / ".cryostack" / "runs")).resolve()
        self._runs: dict[str, RunInfo] = {}
        self._selected_run_id: str | None = None
        self._tail_handler = None

    def set_tail_handler(self, handler) -> None:
        self._tail_handler = handler

    def tail(self, run_id: str):
        run = self.select_run(run_id)
        if not run:
            return None
        if self._tail_handler is None:
            raise RuntimeError("Workspace log routing is not configured.")
        return self._tail_handler()

    def list_editable_files(self, example_path: str) -> list[tuple[str, str]]:
        return list_editable_files(example_path)

    def refresh_files(self) -> None:
        refresh_file_picker(
            example_dir=self.example_dir,
            file_picker=self.file_picker,
            file_editor=self.file_editor,
        )

    def load_file(self) -> None:
        load_selected_file(file_picker=self.file_picker, file_editor=self.file_editor)

    def save_file(self) -> None:
        save_selected_file(
            file_picker=self.file_picker,
            file_editor=self.file_editor,
            log_output=self.log_output,
        )

    def example_root(self) -> Path | None:
        path = Path(self.example_dir.value).expanduser()
        if path.exists():
            return path if path.is_dir() else path.parent
        return None

    def delete(self, path: Path) -> None:
        """Delete one explicitly resolved workspace path."""
        path = Path(path)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def register_run(self, run: RunInfo) -> RunInfo:
        workspace = self.manifest_root / run.id
        run.workspace_directory = workspace.resolve()
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
        if not run or not run.workspace_directory or not run.workspace_directory.exists():
            return []
        return sorted(path for path in run.workspace_directory.rglob("*") if path.is_file())

    def delete_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run or not run.workspace_directory:
            return False
        workspace = run.workspace_directory.resolve()
        try:
            workspace.relative_to(self.manifest_root)
        except ValueError:
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

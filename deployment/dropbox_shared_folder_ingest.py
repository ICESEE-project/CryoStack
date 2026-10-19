#!/usr/bin/env python3
"""Resumably copy a Dropbox shared folder into a protected intake directory.

The OAuth credential stays in rclone's user configuration.  Files are written
as ``.part`` and renamed only after their size and Dropbox content hash match.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath
from typing import Any

API = "https://api.dropboxapi.com/2"
CONTENT_API = "https://content.dropboxapi.com/2"
DROPBOX_HASH_BLOCK = 4 * 1024 * 1024


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def dropbox_content_hash(path: Path) -> str:
    aggregate = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(DROPBOX_HASH_BLOCK):
            aggregate.update(hashlib.sha256(block).digest())
    return aggregate.hexdigest()


def safe_relative_path(display_path: str) -> Path:
    relative = PurePosixPath(display_path.lstrip("/"))
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe Dropbox path: {display_path!r}")
    return Path(*relative.parts)


class DropboxSharedFolder:
    def __init__(self, *, remote: str, shared_url: str, rclone: Path) -> None:
        self.remote = remote
        self.shared_url = shared_url
        self.rclone = rclone
        config_output = subprocess.check_output(
            [str(rclone), "config", "file"], text=True, stderr=subprocess.DEVNULL
        )
        self.config_path = Path(
            next(line.strip() for line in reversed(config_output.splitlines()) if line.strip())
        )
        self._refresh_lock = threading.Lock()

    def _access_token(self) -> str:
        parser = configparser.RawConfigParser()
        parser.read(self.config_path)
        token = json.loads(parser[self.remote]["token"])
        return str(token["access_token"])

    def refresh(self) -> None:
        with self._refresh_lock:
            subprocess.run(
                [str(self.rclone), "lsf", f"{self.remote}:", "--max-depth", "1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )

    def request_json(self, route: str, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(2):
            request = urllib.request.Request(
                f"{API}/{route}",
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": f"Bearer {self._access_token()}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self.refresh()
                    continue
                detail = exc.read().decode("utf-8", "replace")[:1000]
                raise RuntimeError(f"Dropbox {route} failed ({exc.code}): {detail}") from exc
        raise RuntimeError(f"Dropbox {route} authorization failed")

    def inventory(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        pending = [""]
        while pending:
            folder = pending.pop(0)
            page = self.request_json(
                "files/list_folder",
                {
                    "path": folder,
                    "recursive": False,
                    "include_deleted": False,
                    "shared_link": {"url": self.shared_url},
                },
            )
            while True:
                for entry in page.get("entries", []):
                    tag = entry.get(".tag")
                    child_path = f"{folder.rstrip('/')}/{entry['name']}"
                    entry.setdefault("path_display", child_path)
                    if tag == "file":
                        files.append(entry)
                    elif tag == "folder":
                        pending.append(child_path)
                if not page.get("has_more"):
                    break
                page = self.request_json(
                    "files/list_folder/continue", {"cursor": page["cursor"]}
                )
        return files

    def download(self, entry: dict[str, Any], destination: Path) -> dict[str, Any]:
        expected_size = int(entry["size"])
        expected_hash = str(entry["content_hash"])
        final = destination / safe_relative_path(str(entry["path_display"]))
        partial = final.with_name(f".{final.name}.part")
        final.parent.mkdir(parents=True, exist_ok=True)

        if final.is_file() and final.stat().st_size == expected_size:
            actual_hash = dropbox_content_hash(final)
            if actual_hash == expected_hash:
                return {"path": str(final.relative_to(destination)), "status": "present", "size": expected_size, "content_hash": actual_hash}
            final.replace(partial)

        for attempt in range(12):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset > expected_size:
                partial.unlink()
                offset = 0
            headers = {
                "Authorization": f"Bearer {self._access_token()}",
                "Dropbox-API-Arg": json.dumps(
                    {"url": self.shared_url, "path": str(entry["path_display"])}
                ),
            }
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(
                f"{CONTENT_API}/sharing/get_shared_link_file",
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=300) as response:
                    if offset and response.status != 206:
                        partial.unlink(missing_ok=True)
                        continue
                    mode = "ab" if offset else "wb"
                    with partial.open(mode) as stream:
                        while block := response.read(8 * 1024 * 1024):
                            stream.write(block)
                        stream.flush()
                        os.fsync(stream.fileno())
            except urllib.error.HTTPError as exc:
                if exc.code == 401:
                    self.refresh()
                if attempt == 11:
                    raise
                time.sleep(min(60, 2 ** min(attempt, 5)))
                continue
            except (OSError, TimeoutError):
                if attempt == 11:
                    raise
                time.sleep(min(60, 2 ** min(attempt, 5)))
                continue

            if partial.stat().st_size != expected_size:
                time.sleep(min(60, 2 ** min(attempt, 5)))
                continue
            actual_hash = dropbox_content_hash(partial)
            if actual_hash != expected_hash:
                partial.unlink()
                raise RuntimeError(f"Dropbox hash mismatch for {entry['path_display']}")
            os.replace(partial, final)
            return {"path": str(final.relative_to(destination)), "status": "downloaded", "size": expected_size, "content_hash": actual_hash}
        raise RuntimeError(f"download retries exhausted for {entry['path_display']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared-url", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--remote", default="cryostack-dropbox")
    parser.add_argument("--rclone", type=Path, default=Path.home() / ".local/bin/rclone")
    parser.add_argument("--transfers", type=int, default=4)
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--include-prefix", action="append", default=[],
                        help="Copy only paths beneath this prefix; repeatable.")
    parser.add_argument("--minimum-free-gib", type=float, default=20.0,
                        help="Refuse a tranche that would cross this free-space reserve.")
    args = parser.parse_args()
    if args.transfers < 1 or args.transfers > 16:
        parser.error("--transfers must be between 1 and 16")

    client = DropboxSharedFolder(remote=args.remote, shared_url=args.shared_url, rclone=args.rclone)
    files = client.inventory()
    if args.include_prefix:
        prefixes = tuple(prefix.strip("/") + "/" for prefix in args.include_prefix)
        files = [entry for entry in files
                 if str(entry["path_display"]).lstrip("/").startswith(prefixes)]
    selected_bytes = sum(int(entry["size"]) for entry in files)
    free_bytes = shutil.disk_usage(args.destination.parent).free
    reserve_bytes = int(args.minimum_free_gib * 1024**3)
    if not args.inventory_only and selected_bytes > free_bytes - reserve_bytes:
        raise SystemExit(
            f"selected tranche needs {selected_bytes} bytes but the local reserve allows "
            f"only {max(0, free_bytes - reserve_bytes)} bytes"
        )
    manifest: dict[str, Any] = {
        "schema": "cryostack.dropbox-shared-folder-intake",
        "version": 1,
        "source": "Dropbox shared folder",
        "created_at": int(time.time()),
        "file_count": len(files),
        "total_bytes": selected_bytes,
        "include_prefixes": args.include_prefix,
        "minimum_free_bytes": reserve_bytes,
        "files": [
            {
                "path": str(entry["path_display"]).lstrip("/"),
                "size": int(entry["size"]),
                "content_hash": str(entry["content_hash"]),
                "status": "pending",
            }
            for entry in files
        ],
    }
    atomic_json(args.manifest, manifest)
    print(json.dumps({"file_count": manifest["file_count"], "total_bytes": manifest["total_bytes"]}))
    if args.inventory_only:
        return 0

    args.destination.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    by_path = {item["path"]: item for item in manifest["files"]}
    with ThreadPoolExecutor(max_workers=args.transfers) as executor:
        futures = {executor.submit(client.download, entry, args.destination): entry for entry in files}
        for future in as_completed(futures):
            entry = futures[future]
            key = str(entry["path_display"]).lstrip("/")
            try:
                result = future.result()
                with lock:
                    by_path[key].update(result)
                    atomic_json(args.manifest, manifest)
                print(json.dumps({"completed": result["path"], "size": result["size"]}), flush=True)
            except Exception as exc:
                with lock:
                    by_path[key]["status"] = "failed"
                    by_path[key]["error"] = str(exc)
                    atomic_json(args.manifest, manifest)
                print(json.dumps({"failed": key, "error": str(exc)}), flush=True)
    failed = [item for item in manifest["files"] if item["status"] == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""The isolated LIVIST environment: health checks and the job environment.

Every check is a fixed, structured probe of the environment that
``environment/build_env.sh`` builds (no command comes from a request). A
missing or broken tool is reported as such; nothing is substituted.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from pathlib import Path

from . import settings

PROBE_TIMEOUT_S = 20
_CACHE_TTL_S = 60.0
_cache: dict = {}
_cache_lock = threading.Lock()


def paths(env: Path | None = None) -> dict[str, Path]:
    env = env or settings.env_dir()
    tools = env / "toolchain" / "bin"
    return {
        "env": env,
        "record": env / "env.json",
        "toolchain": env / "toolchain",
        "gdal": tools / "gdal",
        "ogrinfo": tools / "ogrinfo",
        "tippecanoe": tools / "tippecanoe",
        "uv": tools / "uv",
        "venv": env / "venv",
        "python": env / "venv" / "bin" / "python",
        "livist": env / "venv" / "bin" / "livist",
        "gdal_data": env / "toolchain" / "share" / "gdal",
        "gdal_plugins": env / "toolchain" / "lib" / "gdalplugins",
        "uv_cache": env / "uv-cache",
    }


def _run(argv: list, **env) -> tuple[int, str]:
    try:
        done = subprocess.run([str(a) for a in argv], capture_output=True, text=True,
                              timeout=PROBE_TIMEOUT_S, stdin=subprocess.DEVNULL,
                              env={"PATH": "/usr/bin:/bin", **env})
    except (OSError, subprocess.TimeoutExpired) as error:
        return -1, type(error).__name__
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def source_commit(source: Path | None = None) -> str | None:
    """The checked-out LIVIST commit (read-only ``git rev-parse``)."""
    source = source or settings.source_dir()
    code, out = _run(["git", "-C", source, "rev-parse", "HEAD"])
    out = out.strip()
    return out if code == 0 and len(out) == 40 else None


def env_record(env: Path | None = None) -> dict | None:
    try:
        record = json.loads(paths(env)["record"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _check(check_id: str, label: str, ok: bool, detail: str, *, level: str = "error") -> dict:
    return {"id": check_id, "label": label, "ok": bool(ok), "detail": detail,
            "level": "ok" if ok else level}


def _gdal_version(text: str) -> tuple[int, int] | None:
    parts = text.split()
    if len(parts) < 2 or parts[0] != "GDAL":
        return None
    try:
        major, minor = parts[1].rstrip(",").split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        return None


def _probe(env: Path | None, source: Path | None) -> dict:
    p = paths(env)
    source = source or settings.source_dir()
    checks = []
    record = env_record(env)
    checks.append(_check(
        "environment", "Isolated environment built", record is not None,
        "Built " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(record.get("built_at", 0)))
        if record else "No completed build (run environment/build_env.sh)."))

    present = (source / "scripts" / "generate").is_file() and (source / "uv.lock").is_file()
    checks.append(_check("source", "LIVIST source checkout", present,
                         "scripts/generate and uv.lock present" if present
                         else "The LIVIST submodule is not initialized."))
    commit = source_commit(source) if present else None
    if record is not None:
        same = bool(commit) and record.get("livist_commit") == commit
        lock_same = record.get("uv_lock_sha256") == _sha256(source / "uv.lock")
        checks.append(_check(
            "pinned", "Environment matches the LIVIST checkout", same and lock_same,
            f"LIVIST {str(commit or 'unknown')[:12]}" if same and lock_same else
            "The environment was built for LIVIST "
            f"{str(record.get('livist_commit') or 'unknown')[:12]}"
            + ("" if lock_same else " with a different uv.lock") + "; rebuild it.",
            level="warn"))

    if p["gdal"].is_file():
        code, out = _run([p["gdal"], "--version"])
        version = _gdal_version(out) if code == 0 else None
        ok = version is not None and version >= (3, 11)
        checks.append(_check("gdal", "GDAL >= 3.11 (gdal vector convert)", ok,
                             out.strip().splitlines()[0] if ok else
                             (out.strip().splitlines() or ["GDAL did not run."])[0][:200]))
        code, out = _run([p["ogrinfo"], "--formats"], GDAL_DRIVER_PATH=str(p["gdal_plugins"]),
                         GDAL_DATA=str(p["gdal_data"]))
        parquet = code == 0 and "Parquet -vector-" in out
        checks.append(_check("gdal_parquet", "GDAL (Geo)Parquet driver", parquet,
                             "Parquet driver registered" if parquet
                             else "GDAL has no Parquet driver (libgdal-arrow-parquet missing)."))
    else:
        checks.append(_check("gdal", "GDAL >= 3.11 (gdal vector convert)", False,
                             "gdal is not installed in the environment."))
        checks.append(_check("gdal_parquet", "GDAL (Geo)Parquet driver", False,
                             "gdal is not installed in the environment."))

    if p["tippecanoe"].is_file():
        code, out = _run([p["tippecanoe"], "--version"])
        line = (out.strip().splitlines() or [""])[0]
        checks.append(_check("tippecanoe", "tippecanoe", code == 0 and "tippecanoe" in line,
                             line[:200] or "tippecanoe did not run."))
    else:
        checks.append(_check("tippecanoe", "tippecanoe", False,
                             "tippecanoe is not installed in the environment."))

    if p["uv"].is_file():
        code, out = _run([p["uv"], "--version"])
        checks.append(_check("uv", "uv", code == 0, (out.strip().splitlines() or [""])[0][:200]))
    else:
        checks.append(_check("uv", "uv", False, "uv is not installed in the environment."))

    ok = p["livist"].is_file() and p["python"].is_file()
    if ok:
        code, out = _run([p["python"], "-I", "-c",
                          "import importlib.metadata as m; print(m.version('livist'))"])
        ok = code == 0
        detail = f"livist {out.strip()} in the uv environment" if ok else "livist does not import."
    else:
        detail = "The uv environment with LIVIST is missing."
    checks.append(_check("livist", "LIVIST installed from uv.lock", ok, detail))

    blocking = [c for c in checks if not c["ok"] and c["level"] == "error"]
    return {
        "ready": not blocking,
        "checks": checks,
        "record": {k: record.get(k) for k in ("livist_commit", "python", "gdal", "tippecanoe",
                                               "uv", "livist_version", "built_at")}
        if record else None,
        "livist_commit": commit,
        "checked_at": time.time(),
    }


def health(*, env: Path | None = None, source: Path | None = None, refresh: bool = False) -> dict:
    """Structured toolchain health, cached for a minute."""
    key = (str(env or settings.env_dir()), str(source or settings.source_dir()))
    with _cache_lock:
        cached = _cache.get(key)
        if cached and not refresh and time.time() - cached["checked_at"] < _CACHE_TTL_S:
            return cached
    result = _probe(env, source)
    with _cache_lock:
        _cache[key] = result
    return result


def job_environment(workdir: Path, *, env: Path | None = None,
                    source: Path | None = None) -> dict[str, str]:
    """The complete environment of a generation subprocess.

    Built from scratch rather than inherited, so the gateway's OAuth/AWS
    settings never reach LIVIST. ``uv run`` resolves LIVIST from
    ``UV_PROJECT`` and runs it in the prebuilt environment without syncing,
    while ``config.toml`` and ``data/`` are read from the job directory.
    """
    p = paths(env)
    tmp = workdir / "tmp"
    return {
        "PATH": f"{p['toolchain'] / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp),
        "TMPDIR": str(tmp),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "UV_PROJECT": str(source or settings.source_dir()),
        "UV_PROJECT_ENVIRONMENT": str(p["venv"]),
        "UV_CACHE_DIR": str(p["uv_cache"]),
        "UV_NO_SYNC": "1",
        "UV_FROZEN": "1",
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "GDAL": str(p["gdal"]),
        "GDAL_DATA": str(p["gdal_data"]),
        "GDAL_DRIVER_PATH": str(p["gdal_plugins"]),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "TQDM_MININTERVAL": "10",
    }

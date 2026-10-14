#!/usr/bin/env bash
# Build the isolated LIVIST processing environment.
#
#   icesee_jupyter_book/applications/livist/environment/build_env.sh [ENV_DIR]
#
# ENV_DIR defaults to $CRYOSTACK_LIVIST_ENV or ~/.cryostack-envs/livist.
# Layout:
#
#   ENV_DIR/toolchain/        conda-forge prefix: python 3.13, GDAL (+ Parquet
#                             driver), tippecanoe, uv (toolchain.txt)
#   ENV_DIR/venv/             LIVIST and its dependencies, installed from
#                             LIVIST's own uv.lock (--frozen, non-editable)
#   ENV_DIR/uv-cache/         uv's download cache
#   ENV_DIR/conda-pkgs/       conda's package cache (unless CONDA_PKGS_DIRS is set)
#   ENV_DIR/toolchain.lock    the exact conda packages (conda list --explicit)
#   ENV_DIR/env.json          build record; written last, so its presence means
#                             the build finished
#
# Nothing is installed into the CryoStack conda environment or the system
# Python, and the LIVIST submodule is only read. Needs no root; needs network
# access to conda-forge and PyPI. Re-running rebuilds from scratch.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
LIVIST_SRC="${LIVIST_SRC:-$REPO/external/living-ice-sheet-temperature}"
ENV_DIR="${1:-${CRYOSTACK_LIVIST_ENV:-$HOME/.cryostack-envs/livist}}"
CONDA_BIN="${CONDA_BIN:-$(command -v mamba || command -v conda || true)}"
if [ -z "$CONDA_BIN" ] && [ -x "$HOME/miniforge3/bin/mamba" ]; then
    CONDA_BIN="$HOME/miniforge3/bin/mamba"
fi

die() { echo "build_env: $*" >&2; exit 1; }

[ -f "$LIVIST_SRC/uv.lock" ] || die "LIVIST source not found at $LIVIST_SRC (initialize the submodule)."
[ -n "$CONDA_BIN" ] || die "mamba or conda is required (set CONDA_BIN)."
case "$(basename "$ENV_DIR")" in
    livist|livist-*) ;;
    *) die "refusing to build into $ENV_DIR (the directory name must start with 'livist')." ;;
esac

echo "build_env: LIVIST source  $LIVIST_SRC"
echo "build_env: environment    $ENV_DIR"
mkdir -p "$ENV_DIR"
rm -rf "$ENV_DIR/env.json" "$ENV_DIR/toolchain" "$ENV_DIR/venv"

# 1. toolchain (conda-forge only; package cache kept with the environment)
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$ENV_DIR/conda-pkgs}"
"$CONDA_BIN" create --yes --quiet --prefix "$ENV_DIR/toolchain" \
    --override-channels --channel conda-forge --file "$HERE/toolchain.txt"
T="$ENV_DIR/toolchain/bin"

# 2. LIVIST from its lockfile (dev group included, for its test suite)
export UV_CACHE_DIR="$ENV_DIR/uv-cache"
export UV_PYTHON_DOWNLOADS=never
"$T/uv" venv --quiet --python "$T/python3.13" "$ENV_DIR/venv"
UV_PROJECT_ENVIRONMENT="$ENV_DIR/venv" "$T/uv" sync --frozen --no-editable \
    --project "$LIVIST_SRC"

# 3. verify what scripts/generate needs
"$T/gdal" --version
FORMATS="$(GDAL_DRIVER_PATH="$ENV_DIR/toolchain/lib/gdalplugins" "$T/ogrinfo" --formats)"
case "$FORMATS" in
    *"Parquet -vector-"*) echo "build_env: GDAL Parquet driver present" ;;
    *) die "GDAL has no Parquet driver (is libgdal-arrow-parquet installed?)." ;;
esac
"$T/tippecanoe" --version 2>&1 | sed -n 1p
"$ENV_DIR/venv/bin/livist" --help >/dev/null

# 4. build record
"$CONDA_BIN" list --explicit --md5 --prefix "$ENV_DIR/toolchain" > "$ENV_DIR/toolchain.lock"
COMMIT="$(git -C "$LIVIST_SRC" rev-parse HEAD 2>/dev/null || echo unknown)"
"$ENV_DIR/venv/bin/python" - "$ENV_DIR" "$LIVIST_SRC" "$COMMIT" "$HERE/toolchain.txt" <<'PY'
import hashlib, json, subprocess, sys, time
from importlib import metadata
from pathlib import Path

env, src, commit, spec = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
first = lambda cmd: subprocess.run(cmd, capture_output=True, text=True).stdout.strip().splitlines()[:1]
record = {
    "schema": 1,
    "built_at": time.time(),
    "livist_commit": commit,
    "uv_lock_sha256": sha(src / "uv.lock"),
    "toolchain_spec_sha256": sha(spec),
    "toolchain_lock_sha256": sha(env / "toolchain.lock"),
    "python": sys.version.split()[0],
    "livist_version": metadata.version("livist"),
    "gdal": (first([str(env / "toolchain/bin/gdal"), "--version"]) or [""])[0],
    "tippecanoe": (first([str(env / "toolchain/bin/tippecanoe"), "--version"])
                   or subprocess.run([str(env / "toolchain/bin/tippecanoe"), "--version"],
                                     capture_output=True, text=True).stderr.strip().splitlines()[:1]
                   or [""])[0],
    "uv": (first([str(env / "toolchain/bin/uv"), "--version"]) or [""])[0],
}
(env / "env.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
PY
echo "build_env: done"

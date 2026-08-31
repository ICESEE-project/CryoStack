from __future__ import annotations


def validate_configuration(configuration: dict) -> dict:
    return dict(configuration or {})


def build_environment_check(*, spack_path: str, sif_path: str, backend: str) -> str:
    if backend != "spack":
        return _container_check(sif_path)
    return f'''
set -e
test -d "{spack_path}" || {{ echo "[missing] ICESEE-Spack not found: {spack_path}"; exit 2; }}
source "{spack_path}/scripts/activate.sh"
test -n "${{ISSM_DIR:-}}" || {{ echo "[missing] ISSM_DIR is not set"; exit 3; }}
test -d "$ISSM_DIR" || {{ echo "[missing] ISSM_DIR path does not exist: $ISSM_DIR"; exit 4; }}
echo "[ok] ICESEE-Spack found"
echo "[ok] ISSM_DIR=$ISSM_DIR"
'''


def _container_check(sif_path: str) -> str:
    return f'''
set -e
if ! command -v apptainer >/dev/null 2>&1; then
    source /etc/profile >/dev/null 2>&1 || true
    module load apptainer >/dev/null 2>&1 || true
fi
command -v apptainer >/dev/null 2>&1 || {{ echo "[missing] apptainer not found"; exit 2; }}
test -f "{sif_path}" || {{ echo "[missing] container image not found: {sif_path}"; exit 3; }}
echo "[ok] apptainer found: $(command -v apptainer)"
echo "[ok] container image found: {sif_path}"
'''

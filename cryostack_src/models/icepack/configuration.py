from cryostack_src.models.issm.configuration import _container_check


def validate_configuration(configuration: dict) -> dict:
    return dict(configuration or {})


def build_environment_check(*, spack_path: str, sif_path: str, backend: str) -> str:
    if backend != "spack":
        return _container_check(sif_path)
    return f'''set -e
test -d "{spack_path}" || {{ echo "[missing] ICESEE-Spack not found: {spack_path}"; exit 2; }}
source "{spack_path}/scripts/activate.sh"
python - <<'PY'
import icepack
print("[ok] icepack import successful")
try:
    import firedrake
    print("[ok] firedrake import successful")
except Exception as e:
    print("[warn] firedrake import failed:", type(e).__name__, e)
PY
'''

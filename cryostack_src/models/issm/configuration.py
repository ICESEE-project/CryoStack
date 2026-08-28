from __future__ import annotations


def validate_configuration(configuration: dict) -> dict:
    return dict(configuration or {})


def build_configuration_script(configuration: dict) -> str:
    lines = [
        "disp('[ICESEE-GUI] Applying editable md configuration...');",
        "if ~exist('md','var')",
        "    disp('[ICESEE-GUI][WARN] md does not exist yet. Skipping md configuration.');",
        "    return;",
        "end",
    ]
    for key, item in (configuration or {}).items():
        key = str(key).strip()
        if not key:
            continue
        target = key if key.startswith("md.") else f"md.{key}"
        if isinstance(item, dict):
            raw_value = str(item.get("value", "")).strip()
            value_type = item.get("type", "string")
        else:
            raw_value = str(item).strip()
            value_type = "string"
        if value_type == "number":
            matlab_value = raw_value
        elif value_type == "bool":
            matlab_value = "true" if raw_value.lower() in {"true", "1", "yes", "on"} else "false"
        elif value_type == "expr":
            matlab_value = raw_value
        else:
            matlab_value = "'" + raw_value.replace("'", "''") + "'"
        lines.extend([
            "try",
            f"    {target} = {matlab_value};",
            f"    disp('[ICESEE-GUI] set {target} = {raw_value}');",
            "catch ME",
            f"    disp(['[ICESEE-GUI][WARN] could not set {target}: ' ME.message]);",
            "end",
        ])
    return "\n".join(lines) + "\n"


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

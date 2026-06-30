#!/bin/bash -l
set -e

# ============================================================
# create_icesee1_environment_yml_rhel.sh
# RHEL9 / Gatech VM version
# Creates icesee1_environment.yml for go.icesee.rhel9
# ============================================================

version_number="1"
environment="${ICESEE_ENV_NAME:-icesee${version_number}-rhel}"

# Use conda-forge OpenMPI inside the environment.
# Allowed: openmpi | mpich
mpi_impl="${MPI_IMPL:-openmpi}"

conda_root="${ICESEE_CONDA_ROOT:-${HOME}/.icesee_conda}"

conda_list="./icesee${version_number}_conda_list_rhel.txt"
conda_env_yml="./icesee${version_number}_environment.yml"

echo "=================================================="
echo "Creating ICESEE RHEL9 conda YAML"
echo "environment: ${environment}"
echo "conda_root: ${conda_root}"
echo "mpi_impl: ${mpi_impl}"
echo "output YAML: ${conda_env_yml}"
echo "=================================================="

# command -v conda >/dev/null 2>&1 || {
#     echo "ERROR: conda not found in PATH"
#     exit 2
# }
# ------------------------------------------------------------
# Conda bootstrap (install Miniforge if missing)
# ------------------------------------------------------------
if ! command -v conda >/dev/null 2>&1; then
    echo "Conda not found. Installing Miniforge..."

    MINIFORGE_DIR="${HOME}/miniforge3"
    INSTALLER="Miniforge3-Linux-x86_64.sh"

    if [[ ! -d "${MINIFORGE_DIR}" ]]; then
        cd /tmp

        curl -L -o "${INSTALLER}" \
          https://github.com/conda-forge/miniforge/releases/latest/download/${INSTALLER}

        bash "${INSTALLER}" -b -p "${MINIFORGE_DIR}"
    fi

    export PATH="${MINIFORGE_DIR}/bin:${PATH}"

    # Initialize shell
    "${MINIFORGE_DIR}/bin/conda" init bash >/dev/null 2>&1 || true
fi

# Final check
command -v conda >/dev/null 2>&1 || {
    echo "ERROR: conda installation failed."
    exit 2
}

eval "$($(which conda) shell.bash hook)"

eval "$(conda shell.bash hook)"

mkdir -p "${conda_root}/envs" "${conda_root}/pkgs"

conda config --add envs_dirs "${conda_root}/envs" || true
conda config --add pkgs_dirs "${conda_root}/pkgs" || true
conda config --add channels conda-forge || true
conda config --set channel_priority strict || true

start1=$(date +%s)

echo "Removing old env ${environment} if it exists..."
conda remove --name "${environment}" --all -y || true

echo "Creating env ${environment}..."
conda create --name "${environment}" python=3.11 -y

echo "Activating env ${environment}..."
conda activate "${environment}"

echo "which python: $(which python)"
echo "which conda: $(which conda)"

echo "Installing core packages..."
conda install -y \
  pip \
  numpy scipy pandas matplotlib \
  pyyaml psutil tqdm dask zarr "numcodecs<0.13" \
  ipykernel "ipywidgets>=7.6,<8" "notebook<7" \
  jupyterlab nbformat nbclient jupyter_client \
  jupyter_server

echo "Installing MPI/HDF5 stack..."
conda install -y -c conda-forge \
  "mpi=1.0=${mpi_impl}" \
  "${mpi_impl}" \
  mpi4py \
  "hdf5=*=mpi*" \
  "h5py=*=mpi*"

echo "Installing documentation tools..."
conda install -y -c conda-forge "jupyter-book=1.*"

echo "Installing pip extras..."
python -m pip install -U pip setuptools wheel

python -m pip install \
  bigmpi4py \
  mpi-pytest \
  papermill \
  gstools \
  pqdm \
  rich \
  progress \
  voila \
  aiohttp

python -m pip install "jax[cpu]"

echo "Running sanity checks..."
python - <<'PY'
import os, glob
from mpi4py import MPI
import h5py

prefix = os.environ.get("CONDA_PREFIX", "")
print("CONDA_PREFIX:", prefix)
print("MPI size:", MPI.COMM_WORLD.Get_size())
print("h5py mpi:", getattr(h5py.get_config(), "mpi", None))

cands = glob.glob(os.path.join(prefix, "lib", "libmpi*"))
print("libmpi candidates:", cands[:10])

if not cands:
    raise SystemExit("ERROR: libmpi not found in conda env.")

if not getattr(h5py.get_config(), "mpi", False):
    raise SystemExit("ERROR: h5py was not built with MPI support.")
PY

echo "Exporting environment YAML..."
rm -f "${conda_list}" "${conda_env_yml}"

conda list > "${conda_list}"

conda env export \
  | grep -v "^name:" \
  | grep -v "^prefix:" \
  > "${conda_env_yml}"

echo "Deactivating env..."
conda deactivate

conda config --remove envs_dirs "${conda_root}/envs" || true
conda config --remove pkgs_dirs "${conda_root}/pkgs" || true

end=$(date +%s)

echo ""
echo "=================================================="
echo "Done."
echo "Created: ${conda_env_yml}"
echo "Package list: ${conda_list}"
echo "Elapsed time: $(( (end-start1)/60 )) minutes"
echo "Next:"
echo "  ./go.icesee.rhel9"
echo "=================================================="

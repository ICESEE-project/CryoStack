#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# convert_icesee_to_submodule.sh — turn the external/ICESEE subtree into a git
# submodule in place, without rewriting the live files.
#
# Usage (from the CryoStack checkout root):
#   deployment/convert_icesee_to_submodule.sh            # dry run: report only
#   deployment/convert_icesee_to_submodule.sh --yes      # convert
#
# Env:
#   ICESEE_PIN      commit to pin (default: the cryostack integration commit)
#   ICESEE_SOURCE   repository holding that commit (default: GitHub ICESEE;
#                   a local clone works before the branch is pushed)
#   ICESEE_BRANCH   branch .gitmodules follows (default: cryostack)
#
# What it does:
#   1. Compares external/ICESEE with ICESEE_PIN through a scratch index and
#      lists every file that would change. Untracked files (run data, caches)
#      are never touched.
#   2. --yes: creates .git/modules/external/ICESEE over the existing directory,
#      checks out only the files that differ from the pin, replaces the
#      superproject's tracked subtree with a gitlink, writes .gitmodules and
#      removes external/ICESEE_UPSTREAM_SHA.txt. The superproject change is
#      staged, not committed.
# -----------------------------------------------------------------------------
set -euo pipefail

log(){ echo "[icesee-submodule] $*"; }
die(){ echo "[icesee-submodule][ERROR] $*" >&2; exit 1; }

ROOT="$(git rev-parse --show-toplevel)"
cd "${ROOT}"
PIN="${ICESEE_PIN:-bbdde20ecdc5fee54eb2d9e67672e60a1ecb503a}"
SOURCE="${ICESEE_SOURCE:-https://github.com/ICESEE-project/ICESEE.git}"
BRANCH="${ICESEE_BRANCH:-cryostack}"
URL="https://github.com/ICESEE-project/ICESEE.git"
SUB="external/ICESEE"
MODDIR="$(git rev-parse --git-common-dir)/modules/${SUB}"
YES=0
[[ "${1:-}" == "--yes" ]] && YES=1

[[ -d "${SUB}" ]] || die "${SUB} not found"
[[ ! -e "${SUB}/.git" ]] || die "${SUB} already has its own git checkout"
[[ ! -e "${MODDIR}" ]] || die "${MODDIR} already exists"
[[ "$(git ls-files -s -- "${SUB}" | head -1 | cut -c1-6)" != "160000" ]] || die "${SUB} is already a gitlink"

scratch="$(mktemp -d)"
trap 'rm -rf "${scratch}"' EXIT

log "fetching ${PIN:0:12} from ${SOURCE}"
git clone -q --bare "${SOURCE}" "${scratch}/icesee.git"
git -C "${scratch}/icesee.git" cat-file -e "${PIN}^{commit}" 2>/dev/null \
  || git -C "${scratch}/icesee.git" fetch -q origin "${PIN}" \
  || die "${PIN} is not in ${SOURCE}"
PIN="$(git -C "${scratch}/icesee.git" rev-parse "${PIN}^{commit}")"

# files whose content differs from the pin (scratch index; nothing is written)
changes="$(GIT_DIR="${scratch}/icesee.git" GIT_WORK_TREE="${ROOT}/${SUB}" GIT_INDEX_FILE="${scratch}/index" \
  sh -c 'git read-tree "$1" && git status --porcelain --untracked-files=no' _ "${PIN}")"
log "files that will change to match ${PIN:0:12} ($(printf '%s' "${changes}" | grep -c . || true)):"
printf '%s\n' "${changes}" | sed 's/^/    /'

if [[ "${YES}" -ne 1 ]]; then
  log "dry run only; re-run with --yes to convert"
  exit 0
fi

log "creating ${MODDIR}"
mkdir -p "$(dirname "${MODDIR}")"
git clone -q --bare "${scratch}/icesee.git" "${MODDIR}"
git -C "${MODDIR}" config core.bare false
git -C "${MODDIR}" config core.worktree "$(realpath --relative-to="${MODDIR}" "${ROOT}/${SUB}")"
git -C "${MODDIR}" remote set-url origin "${URL}"
git -C "${MODDIR}" config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
printf 'gitdir: %s\n' "$(realpath --relative-to="${ROOT}/${SUB}" "${MODDIR}")" > "${SUB}/.git"

git -C "${SUB}" update-ref --no-deref HEAD "${PIN}"
git -C "${SUB}" read-tree "${PIN}"
changed_paths="$(printf '%s\n' "${changes}" | awk 'NF {print substr($0, 4)}')"
if [[ -n "${changed_paths}" ]]; then
  log "checking out the files that differ"
  printf '%s\n' "${changed_paths}" | git -C "${SUB}" checkout-index -f --stdin
fi
remaining="$(git -C "${SUB}" status --porcelain --untracked-files=no)"
[[ -z "${remaining}" ]] || die "submodule still differs from the pin:\n${remaining}"

log "replacing the tracked subtree with a gitlink"
git rm -r -q --cached -- "${SUB}"
git config -f .gitmodules "submodule.${SUB}.path" "${SUB}"
git config -f .gitmodules "submodule.${SUB}.url" "${URL}"
git config -f .gitmodules "submodule.${SUB}.branch" "${BRANCH}"
git add .gitmodules
git update-index --add --cacheinfo "160000,${PIN},${SUB}"
git submodule init -- "${SUB}" >/dev/null
if git ls-files --error-unmatch external/ICESEE_UPSTREAM_SHA.txt >/dev/null 2>&1; then
  git rm -q external/ICESEE_UPSTREAM_SHA.txt
fi

log "done (staged, not committed):"
git submodule status -- "${SUB}"
git status --short -- .gitmodules "${SUB}" external/ICESEE_UPSTREAM_SHA.txt

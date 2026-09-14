#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# CryoStack CloudFormation template publisher
# ============================================================
#
# Publishes the canonical CryoStack execution-role template to S3
# and verifies that the hosted object is byte-for-byte identical
# to the checked-in generated template.
#
# This script does NOT modify IAM permissions.
# The active AWS identity must already have permission to read/write:
#
#   s3://cryostack-cloudformation-713938953301/
#       cryostack-execution-role.json
#
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LOCAL_TEMPLATE="${REPO_ROOT}/deployment/cloudformation/cryostack-execution-role.json"

BUCKET="cryostack-cloudformation-713938953301"
OBJECT_KEY="cryostack-execution-role.json"
REGION="us-east-2"

S3_URI="s3://${BUCKET}/${OBJECT_KEY}"
PUBLIC_URL="https://${BUCKET}.s3.${REGION}.amazonaws.com/${OBJECT_KEY}"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

die() {
    echo "[ERROR] $*" >&2
    exit 1
}

info() {
    echo "[INFO] $*"
}

success() {
    echo "[OK] $*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

sha256_file() {
    local file="$1"

    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "${file}" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "${file}" | awk '{print $1}'
    else
        die "Neither sha256sum nor shasum is available."
    fi
}

# ------------------------------------------------------------
# Requirements
# ------------------------------------------------------------

require_command aws
require_command python3

[[ -f "${LOCAL_TEMPLATE}" ]] || \
    die "Generated CloudFormation template not found: ${LOCAL_TEMPLATE}"

# ------------------------------------------------------------
# Verify generated artifact against authoritative renderer
# ------------------------------------------------------------

info "Verifying generated template against render_template()..."

export CRYOSTACK_TEMPLATE_PATH="${LOCAL_TEMPLATE}"
export CRYOSTACK_REPO_ROOT="${REPO_ROOT}"

python3 <<'PY'
import json
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["CRYOSTACK_REPO_ROOT"])
template_path = Path(os.environ["CRYOSTACK_TEMPLATE_PATH"])

sys.path.insert(0, str(repo_root))

try:
    from cryostack_src.cloud.connect.cloudformation import render_template
except Exception as exc:
    raise SystemExit(
        f"[ERROR] Could not import authoritative CloudFormation renderer: {exc}"
    )

with template_path.open("r", encoding="utf-8") as handle:
    generated = json.load(handle)

rendered = render_template()

# Some implementations may return serialized JSON.
if isinstance(rendered, str):
    rendered = json.loads(rendered)

if generated != rendered:
    raise SystemExit(
        "[ERROR] deployment/cloudformation/cryostack-execution-role.json "
        "does not match render_template(). Regenerate the checked-in "
        "CloudFormation artifact before publishing."
    )

print("[OK] Generated template matches render_template().")
PY

# ------------------------------------------------------------
# Template version
# ------------------------------------------------------------

TEMPLATE_VERSION="$(
    python3 <<'PY'
import sys
import os
from pathlib import Path

repo_root = Path(os.environ["CRYOSTACK_REPO_ROOT"])
sys.path.insert(0, str(repo_root))

try:
    from cryostack_src.cloud.connect.cloudformation import TEMPLATE_VERSION
    print(TEMPLATE_VERSION)
except Exception:
    print("unknown")
PY
)"

LOCAL_SHA="$(sha256_file "${LOCAL_TEMPLATE}")"

echo
info "Template version : ${TEMPLATE_VERSION}"
info "Local template   : ${LOCAL_TEMPLATE}"
info "Local SHA256     : ${LOCAL_SHA}"
info "Destination      : ${S3_URI}"
info "Region           : ${REGION}"
echo

# ------------------------------------------------------------
# Show publishing identity
# ------------------------------------------------------------

info "Checking active AWS identity..."

AWS_IDENTITY="$(
    aws sts get-caller-identity \
        --query Arn \
        --output text
)"

info "Publishing as: ${AWS_IDENTITY}"

# ------------------------------------------------------------
# Upload
# ------------------------------------------------------------

info "Uploading CloudFormation template..."

aws s3 cp \
    "${LOCAL_TEMPLATE}" \
    "${S3_URI}" \
    --region "${REGION}"

# ------------------------------------------------------------
# Download hosted object and verify
# ------------------------------------------------------------

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

info "Downloading hosted template for verification..."

aws s3 cp \
    "${S3_URI}" \
    "${TMP_FILE}" \
    --region "${REGION}" \
    --only-show-errors

HOSTED_SHA="$(sha256_file "${TMP_FILE}")"

info "Hosted SHA256    : ${HOSTED_SHA}"

if [[ "${LOCAL_SHA}" != "${HOSTED_SHA}" ]]; then
    echo
    die "Published template verification failed: local and hosted SHA256 differ."
fi

echo
success "CloudFormation template published and verified."
success "Template version: ${TEMPLATE_VERSION}"
success "SHA256: ${LOCAL_SHA}"

echo
echo "Hosted template:"
echo "  ${PUBLIC_URL}"
echo
echo "Existing user stacks must still be updated through CloudFormation"
echo "before new IAM permissions in this template take effect."

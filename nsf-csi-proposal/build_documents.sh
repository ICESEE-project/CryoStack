#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${repo_root}"

mkdir -p output/pdf

documents=(
  project_summary
  project_description
  references_cited
  budget_justification
  facilities
  data_management_plan
  delivery_mechanism_metrics
  project_personnel_partners
  ci_professional_mentoring
)

for document in "${documents[@]}"; do
  latexmk -pdf \
    -interaction=nonstopmode \
    -halt-on-error \
    -outdir=output/pdf \
    -jobname="${document}" \
    "documents/${document}.tex"
done

latexmk -pdf \
  -interaction=nonstopmode \
  -halt-on-error \
  -outdir=output/pdf \
  -jobname="CryoStack_CSSI_Elements_Proposal_Draft" \
  main.tex

latexmk -c -outdir=output/pdf main.tex >/dev/null 2>&1 || true
find output/pdf -maxdepth 1 -type f \
  \( -name '*.aux' -o -name '*.bbl' -o -name '*.blg' -o \
     -name '*.fdb_latexmk' -o -name '*.fls' -o -name '*.log' -o \
     -name '*.out' \) -delete

echo "Built NSF upload PDFs in ${repo_root}/output/pdf"

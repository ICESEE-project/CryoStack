#!/usr/bin/env bash
set -euo pipefail

paper_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${paper_root}"
mkdir -p output/pdf
find output/pdf -maxdepth 1 -type f \
  \( -name 'paper_wrapper.*' -o -name 'CryoStack_Paper_Draft.pdf' \) -delete

# Preserve paper.md as the journal-facing source while removing its YAML
# front matter for the local LaTeX review build.
awk 'BEGIN { front=0; done=0 }
     NR==1 && $0=="---" { front=1; next }
     front && $0=="---" { front=0; done=1; next }
     !front && done { print }' paper.md > output/paper_body.md

pdflatex --shell-escape -interaction=nonstopmode -halt-on-error \
  -output-directory=output/pdf paper_wrapper.tex
(cd output/pdf && BIBINPUTS=../..: bibtex paper_wrapper)
pdflatex --shell-escape -interaction=nonstopmode -halt-on-error \
  -output-directory=output/pdf paper_wrapper.tex
pdflatex --shell-escape -interaction=nonstopmode -halt-on-error \
  -output-directory=output/pdf paper_wrapper.tex

mv output/pdf/paper_wrapper.pdf output/pdf/CryoStack_Paper_Draft.pdf
find output/pdf -maxdepth 1 -type f \
  \( -name '*.aux' -o -name '*.bcf' -o -name '*.bbl' -o -name '*.blg' -o \
     -name '*.log' -o -name '*.out' -o -name '*.run.xml' \) -delete
rm -f output/paper_body.md
echo "Built output/pdf/CryoStack_Paper_Draft.pdf"

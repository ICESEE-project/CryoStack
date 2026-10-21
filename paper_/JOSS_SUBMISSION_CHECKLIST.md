# JOSS pre-submission checklist

Checked against the JOSS author guidance and review checklist on 19 October
2026.

## Ready

- The paper contains all required sections: Summary, Statement of need, State
  of the field, Software design, Research impact statement, AI usage
  disclosure, Acknowledgements, and References.
- The manuscript body is within the JOSS target of 750--1,750 words.
- Author names, ORCIDs, affiliations, title, date, and bibliography metadata
  are present.
- Both figure paths resolve to committed PNG files.
- The repository contains an OSI-approved MIT license, installation and usage
  documentation, contribution and support guidance, a code of conduct, issue
  templates, automated tests, and continuous integration.
- Repository history spans more than six months and includes tagged releases.
- The official Open Journals draft action is configured in
  `.github/workflows/draft-paper.yml`.

## Author confirmation required before submission

- Read and confirm the AI usage disclosure. It currently states that OpenAI
  Codex (GPT-5) assisted with refactoring, test scaffolding, audits,
  documentation, and manuscript editing. Expand or narrow this statement if
  other tools, models, versions, or uses must be disclosed.
- Confirm that every listed author satisfies the project and JOSS authorship
  criteria and that no qualifying software author is missing.
- Confirm the research-impact wording and add concrete evidence of non-author
  adoption, publications, teaching use, or external integrations if available.
  Current JOSS screening treats demonstrated research use as a mandatory gate;
  the paper is candid that external adoption has not yet been established.
- Create an immutable archive for the submitted software release (for example,
  through Zenodo), then add its DOI to `paper.bib`, cite it in `paper.md`, and
  add the DOI to `CITATION.cff`. Do not submit with a placeholder DOI.
- Run the Draft JOSS paper workflow and inspect the generated PDF for figure,
  citation, line-break, and accessibility problems.
- Verify that the public default branch contains the paper, source, tests,
  documentation, issue tracker, and the exact tagged release to be reviewed.

# CryoStack CSSI Elements proposal: submission-readiness notes

This folder now contains a concrete, solicitation-aligned proposal narrative.
Its typography and page design closely follow Alex Robel's
`DRAGON_proposal.tex`: 11-point Times, one-inch margins, compact bold section
heads, author--year citations, unnumbered pages, an inline proposal title, and
a shaded objectives box. The Project Description now also follows DRaGoN's
argument order: Intellectual merit with O1--O3; State of knowledge; Proposed
research organized by O1--O3; Broader impacts; Timeline; Personnel; Results
from prior NSF support; and References Cited. CSSI-specific validation,
delivery, metrics, and sustainability criteria are embedded within that flow.

The combined internal-review PDF generated from `main.tex` contains only the
Project Description followed by References Cited, matching DRaGoN's review
flow. The Project Summary, budget justification, facilities, data-management
plan, and CSSI supplements remain intentionally separate. Each has a driver in
`documents/` and inherits shared formatting from `dragon_nsf_format.tex`.

## Proposal spine

- Title: **Elements: CryoStack — Reusable Cyberinfrastructure for
  Reproducible Cryosphere Computing**
- O1: Versioned application/model/dataset extension kits, production PISM
  coupling, a second Frozen Legacies collection, and automated CryoBench gates.
- O2: FastAPI control plane, typed connector/relay, allow-listed remote
  execution, reproducible environments, PACE, and an end-to-end AWS profile.
- O3: Community-ready experiment/provenance registry, connected data/model
  workflows, usability evaluation, training, contributor governance, and
  sustainability planning.
- Elements scope: three years; current planning total $486,436 (workbook
  rates). NSF 22-632 baseline limits: $600,000 total and up to $200,000 per
  year. At Georgia Tech FY27 rates the same effort costs $500,683 (see
  "Staffing options").

## Administrative confirmations required before submission

1. Confirm that Brian Kyanjo is eligible and intended to serve as PI and that
   Alexander Robel is Co-PI. Update all senior-personnel documents consistently
   if the roles differ.
2. Replace the budget workbook's planning assumptions with approved Georgia
   Tech salary, fringe, escalation, F&A rate/base, and cloud/travel estimates.
3. Decide whether any student, postdoc, research software engineer, consultant,
   collaborator, or subaward will be supported. Reconcile the budget,
   personnel list, management plan, biosketches, current/pending support, and
   collaboration letters.
4. Decide whether Talea Mayo has a formal role. Do not add her to the required
   personnel list without a confirmed role and the corresponding proposal
   documents.
5. Ask the research office whether the PI's software-engineering effort counts
   as support for a “CI Professional.” Submit the CI Professional plan only if
   applicable.
6. Obtain current baseline evidence before submission: registered users,
   completed non-test runs, unique external groups, GitHub clones/downloads,
   releases, contributors, workshops, publications, and citations. Replace the
   sentence promising final counts in Results from Prior NSF Support.
7. Confirm PACE allocation/queue/storage access and the Georgia Tech VM,
   security, backup, and deployment commitments. Avoid listing unapproved
   institutional resources as committed cost sharing.
8. Seek narrowly worded letters of collaboration from a PISM
   developer/experienced user, a historical-radar data steward, PACE or Georgia
   Tech web/security personnel, and a research-software or Science Gateway
   expert as appropriate. Add every letter writer to
   the required personnel/partner list.
9. Resolve the repository license inconsistency (BSD-2-Clause versus MIT) with
   Georgia Tech and project contributors; keep the Year-1 harmonization task if
   it will not be resolved before submission.
10. Confirm the PISM demonstration domain, assimilated observations, state
    variables, parameters, ensemble size, quantitative scientific acceptance
    thresholds, and estimated compute/storage requirements.
11. Generate SciENcv biosketches and current-and-pending-support documents; the
    legacy `sections/biosketch.tex` is not included in the combined draft.
12. Authoritative program page:
    https://www.nsf.gov/funding/opportunities/cssi-cyberinfrastructure-sustained-scientific-innovation
    Track: Elements (small teams, robust scientific services). Framework
    Implementations is a possible later step; Transition to Sustainability is
    premature until adoption is demonstrated. Keep aligned with the page's
    emphasis on integrated CI services, measurable delivery and usage, and
    community development. Contact the cognizant CSSI (OAC) and GEO/OPP
    program officers about scientific priorities and the budget before
    finalizing. Do not change the \$486,436 budget or add the research
    software engineer until the new solicitation's ceiling and Georgia Tech
    salaries/rates are confirmed.
    Solicitation status (checked October 13, 2026): the NSF CSSI page reads
    "Status: Waiting for new publication" and lists NSF 22-632 only as
    previous guidelines, with no due dates. NSF 22-632 (including the
    \$600,000 / 3-year / up-to-\$200,000-per-year Elements limits, the 15-page
    Project Description, the required Delivery Mechanism and Community Usage
    Metrics supplement, and the CI Professional mentoring plan if CI
    professionals are funded) is a planning baseline only; its page says the
    program is not currently accepting proposals. PAPPG NSF 24-1 is the
    version in force; NSF 26-200/26-202 apply to awards only. No binding AI
    disclosure requirement was found. No submission deadline is
    assumed. When the new solicitation appears, re-verify every requirement,
    the PAPPG in force, and any binding disclosure rules, then run Georgia
    Tech's compliance review.
13. Computing-access pilot (planning scenario, not in the budget): up to 50
    participants x \$25 = \$1,250, about \$1,560 with 25% contingency, for
    eligible CryoLauncher/ICESEE workflows only. Needs institutional approval
    and Georgia Tech cost classification (participant support vs. other direct
    costs); per-workflow allocations must be estimated before being offered.
    Added to the Georgia Tech-rate base: +\$1,562 as participant support
    (no F&A) or +\$2,459 as other direct costs (57.4% F&A).
    Cost estimates use AWS us-east-2 list prices and assumed runtimes, not
    measured AWS benchmarks. CloudBank (currently described as access through
    ACCESS and the NAIRR Pilot) and research-credit programs are unverified.
14. Staffing scenario (not in the budget): see "Staffing options" below.
15. Computing-allocation service (Task 2.4, proposed): engineering is inside
    PI effort; allocation administration, approvals, and billing
    reconciliation are unbudgeted operational effort. Georgia Tech must
    approve distributing grant-funded computing this way. BYO billing audit
    (2026-10-13): users without a connected AWS account fell back to the host's
    ambient/profile AWS credentials ("developer mode"). Fix prepared and
    tested, not deployed (`_changes/r7-byo.patch`): no connection -> refused;
    host credentials only for user ids listed in
    `CRYOSTACK_CLOUD_OPERATOR_USER_IDS` (empty by default). The project-managed
    allocation path (Task 2.4) does not exist yet and is refused.

## Page-limit check

- Project Summary: 1 page.
Measured 2026-10-13 with tectonic and Times-metric fonts; confirm with
pdfLaTeX before submission.

- Project Summary: 1 page.
- Project Description: 14 pages (15-page maximum).
- Data Management and Sharing Plan: 2 pages.
- Delivery Mechanism and Community Usage Metrics: 2 pages (2-page maximum).
- Budget Justification: 2 pages. Facilities: 1 page. References: 1 page.
- CI Professional mentoring plan: not written; 2-page maximum if required.

## Recommended next substantive additions

The most valuable remaining evidence is not more generic prose. Add (a) a
table of current CryoStack/ICESEE baseline adoption and reliability, (b) one
scientific preliminary-result figure showing ICESEE error reduction or scaling,
(c) named external design partners, and (d) a precise PISM use-case and compute
estimate. These additions should fit comfortably within the remaining Project
Description pages.

## Build

From this directory:

```sh
./build_documents.sh
```

The script builds the individual Research.gov upload files and a combined
Project Description plus References review copy named
`CryoStack_CSSI_Elements_Proposal_Draft.pdf`. Budget and supplements are not
appended to that review copy. Upload the individual documents.

## Staffing options (for PI decision; budget unchanged at \$486,436)

Recalculated with Georgia Tech rates (osp.gatech.edu/rates, checked
2026-10-13): F&A 57.4% MTDC (capped research, FY25-FY27, fixed for the award),
FY27 full fringe 34.1%. Salaries and 3% escalation are still workbook
assumptions (PI \$85,000, Co-PI \$130,000, RSE \$85,000 base).

| Scenario | Y1 | Y2 | Y3 | Total | Fits \$600k and \$200k/yr? |
|---|---|---|---|---|---|
| Workbook (in proposal) | | | | \$486,436 | yes |
| Base at GT rates | \$162,708 | \$166,854 | \$171,121 | \$500,683 | yes |
| + pilot as participant support | | +\$1,562 | | \$502,246 | yes |
| + pilot as other direct cost | | +\$2,459 | | \$503,142 | yes |
| + RSE 20% | \$198,591 | \$203,813 | \$209,189 | \$611,592 | **no** (both) |
| + RSE 15% | | | max \$199,672 | \$583,865 | yes |

The largest RSE share that fits both limits is about 15% (~1.8 person-months
per year, ~\$83,700 over three years). A graduate research assistant cannot
be costed without stipend figures (GT tuition \$1,612/month is excluded from
MTDC; graduate health fringe 6.8%).

- **A. Current allocation** (PI 7.2 months/year, Co-PI 1 month/year): every
  development, release, deployment, and support task depends on the PI.
- **B. Add a ~15% research software engineer** (about \$83,700): CryoBench
  CI tiers, release engineering, security tests, and a second person able to
  deploy and roll back each component (Tasks 1.3, 2.1, 2.2, release process).
  Year 3 sits about \$330 under the \$200,000 annual limit, so any salary
  above the assumptions requires a smaller fraction.

Recommendation: B, because it directly removes the single-maintainer risk
named in the risk register. Keep \$486,436 in the proposal until Georgia Tech
confirms salaries and the new solicitation confirms the limits. Adding
personnel also triggers the CI Professional plan decision (item 5).

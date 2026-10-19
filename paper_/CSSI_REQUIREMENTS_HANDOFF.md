# CSSI (NSF 22-632) requirements handoff for the CryoStack proposal

**Purpose.** Extract NSF 22-632 as a requirements document for the Fall 2026
CryoStack CSSI proposal and map it against the CryoStack implementation and the
JOSS paper. **The NSF proposal is not edited by this pass.** This document is
input for a later proposal-revision pass.

**Sources.** NSF CSSI program page
(<https://www.nsf.gov/funding/opportunities/cssi-cyberinfrastructure-sustained-scientific-innovation>)
and the NSF 22-632 solicitation text
(<https://www.nsf.gov/funding/opportunities/cssi-cyberinfrastructure-sustained-scientific-innovation/nsf22-632/solicitation>),
read September 2026. Section labels below (§II, §V.A, §VI.A …) follow the
standard NSF solicitation numbering; **verify the exact sub-labels against the
official PDF and the PAPPG in force for the December 1, 2026 deadline** before
relying on any citation here. The proposal team's own
`nsf-csi-proposal/SUBMISSION_READINESS.md` already records NSF 22-632 as
current as of August 9, 2026 and an Elements scope (3 years, $600,000 cap).

Companion documents: `paper/AUDIT_JOSS_CURRENT_STATE.md`,
`paper/JOSS_TO_NSF_HANDOFF.md`, `paper/JOSS_REVISION_NOTES.md`.

---

## 1. Award classes (NSF 22-632 §II, §III)

| Class | Purpose (solicitation language) | Budget | Duration | Team |
|---|---|---|---|---|
| **Elements** | "Small groups that will create and deploy robust services for which there is a demonstrated need, and that will advance one or more significant areas of science and engineering." | **Up to $600,000 total** (≈ $200,000/yr) | **Up to 3 years** | Small group (PI + a few) |
| **Framework Implementations** | "Larger, interdisciplinary teams organized around the development and application of services aimed at solving common research problems … resulting in a sustainable community framework providing CI services to a diverse community or communities." | **$600,001 – $5,000,000 total** | **3–5 years** | Larger, interdisciplinary; multi-institution encouraged; formal management plan required |
| **Transition to Sustainability** | "Groups who would like to execute a well-defined sustainability plan for existing CI with demonstrated impact … enable new avenues of support for the long-term sustained impact of the CI." | **Up to $1,000,000 total** | **Up to 2 years** | Existing team with an existing, adopted CI |

**Anticipated awards (FY23 basis):** ~20 Elements, ~10 Frameworks, ~5
Transition. Cost sharing prohibited. Annual PI-meeting travel to NSF must be
budgeted (§V, §VII).

**Note on figures:** the current NSF CSSI *program page* quotes program-wide
availability ($10M Elements / $20M Framework / $4M Transition) and a "finite
duration, up to 10 years" phrasing; those are aggregate/portfolio statements,
not per-award caps. The **per-award** caps and durations above are the NSF
22-632 numbers and match the existing proposal budget
(`nsf-csi-proposal/sections/budget_justification.tex`: $486,436 planning total,
"$600,000 Elements cap"). **OWNER_CHECKPOINT:** confirm the per-award cap and
duration in the exact solicitation revision that governs the December 1, 2026
deadline — CSSI has been revised repeatedly (18-531 → 19-548 → 20-592 → 22-632)
and a 2026 revision may exist.

---

## 2. Elements vs. Framework Implementations — evidence for both

The current proposal (`nsf-csi-proposal/`) is written as **Elements**. That is
almost certainly right, but the case for each is below so the choice is
deliberate.

### Evidence FOR Elements

- **Team size.** Two senior personnel (PI Kyanjo, Co-PI Robel), one institution
  (Georgia Tech), no confirmed subawards, students, or RSEs
  (`SUBMISSION_READINESS.md` items 1, 3). Elements is "small groups"; Framework
  is "larger, interdisciplinary teams … across organizations."
- **Committed new scientific integration is bounded.** One production model
  (PISM) and one historical-radar dataset (`project_description.tex` O1). That
  is Elements-scale scope, not a multi-community framework.
- **Community is nascent.** No measured adoption, no external contributors, no
  governance body yet (JOSS paper limitations; `SUBMISSION_READINESS.md` item
  6). Framework review weights "stakeholder engagement" and "sustainable
  community framework" heavily; a Framework proposal with no existing community
  is weak.
- **Budget.** $486k planning total sits comfortably under the $600k Elements
  cap; a Framework ($600k–$5M) would need to justify 3–10× the personnel and a
  multi-institution management plan that does not exist.
- **Innovation weighting.** §VI.A notes Innovation "may be more heavily
  weighted" for Elements — CryoStack's per-model / per-backend contract design
  and the digest-bound human-in-the-loop approval boundary are genuine CI
  innovations that fit an Elements pitch.
- **Precedent.** ICESEE's own trajectory (CAREER-funded method → open library →
  JOSS/EGUsphere) is the pattern CSSI Elements expects: a demonstrated small
  service with a path to sustainability.

### Evidence FOR Framework Implementations

- **Breadth already present.** Four applications (CryoLauncher, ICESEE, LIVIST,
  Frozen Legacies), two models, two extensibility axes (model adapter, dataset
  adapter), remote HPC + cloud backends. That is more surface area than a
  typical Elements service.
- **"Common research problems faced by NSF researchers."** The
  data-to-model-to-assimilation lifecycle spans OPP, GEO/EAR, and CISE/OAC
  interests — a cross-directorate framing that Framework rewards.
- **The proposal's own objectives read Framework-sized.** O1 (versioned SDK +
  CryoBench qualification service + PISM + dataset adapter), O2 (threat model +
  rebuilt connector protocol + two qualified backends + SBOMs), O3 (durable
  provenance registry + observation-bundle schema + user studies + governance +
  five-year sustainability plan). Delivering all three credibly in 3 years at
  $200k/yr with two part-time PIs is aggressive; a reviewer may read it as an
  under-resourced Framework.
- **"Sustainable community framework … interoperable … by broad communities"**
  (Framework language) matches the stated end state better than "deploy robust
  services for which there is a demonstrated need" (Elements language).

### OWNER_CHECKPOINT — the decision

**Recommendation to consider, not a decision:** stay **Elements**, and
*right-size the objectives to Elements* rather than moving to Framework. The
binding constraints are team size, absence of an existing measured community,
and the PI-participation limit (§4 below) — all of which point to Elements now
and a **Framework Implementations or Transition to Sustainability** proposal in
~3 years once CryoStack has adoption evidence. If the team can, before Fall:
(a) add a second institution with a real role, (b) secure 2–3 named external
design-partner groups with letters, and (c) show baseline adoption numbers,
then Framework becomes defensible — but the scope must then genuinely widen
beyond ice sheets (glacier/permafrost/sea-ice/solid-earth adapters), not just
cost more.

The decision belongs to the PI and Co-PI and should be recorded with rationale
in the proposal's architectural decision record.

---

## 3. Solicitation expectations, by topic (NSF 22-632 §II, §V.A, §VI.A)

Each row: what NSF asks for → where it must be addressed.

| Expectation | Solicitation language / intent | Where in the proposal |
|---|---|---|
| **Demonstrated scientific need** | "fill well-recognized science and engineering needs"; "advance research capability in significant S&E areas" | Project Description Theme 1 (Science-driven); Project Summary Overview |
| **Significant bottlenecks** | "must be designed to overcome significant bottlenecks to solving compelling S&E questions"; for GEO: "compelling geoscience questions" | Theme 1, opening; must be the spine of the whole narrative (see §5) |
| **Integrated CI services** | services "science-driven, innovative, collaborative, leveraged, strategic, sustained"; span "sensors … to high-end data and computing systems" | Theme 2 (CI Plans) |
| **Reusable services** | Elements: "disseminated to the community as reusable services"; Framework: CI "sharable, easily findable and accessible, interoperable, and reusable" | Theme 2 + Theme 3 Deliverables |
| **Community-driven CI** | "engage CI experts, specialists, and scientists … working in concert with the relevant domain scientists"; "community-driven approach"; user interactions in the plan | Theme 2 (Close Collaboration); Theme 1 (community development); management |
| **Interoperability** | Framework: "interoperable … by broad communities"; GEO: "seamless discovery, access, and transfer of data and metadata" | Theme 2 architecture; O1 contracts; O3 observation-bundle schema |
| **Reproducibility** | architecture must address how "reproducibility … will be addressed by the project and integrated into … the engineering process" | Theme 2; O2 environments; O3 provenance |
| **Provenance** | "support the integrity and provenance of the scientific workflow and resulting data artifacts" | Theme 2; O3 provenance registry + run bundles |
| **Sustainability** | "benefits beyond the participants and the lifetime of the award"; "sustainability approaches following well-established models"; identify transition to other support | Theme 3 (Sustained and Sustainable Impacts); five-year operations plan |
| **Community creation** | "catalyze the development of sustainable CI communities that transcend scientific and geographical boundaries"; "scales from individuals … to large communities" | Theme 1 + Theme 3; O3 governance |
| **Education / workforce development** | "innovative educational activities to train next-generation creators of CI"; **"should not … be the focus … but integrated within the main effort"** (CyberTraining is the home for education-focused work) | Broader Impacts section (required, separate); O3 workshops/office hours; CI Professional plan if applicable |
| **Interdisciplinary use** | benefits "communities beyond initial targets"; Framework encourages "multiple disciplines" | Theme 1 broader impact; directorate-alignment statement |
| **Delivery mechanisms** | "clearly articulate the services and capabilities to be delivered, and how"; explore ACCESS, leadership computing, OAC Software Institutes, cloud, Big Data Hubs | Theme 3 Deliverables; **Delivery Mechanism and Community Usage Metrics supplement (2 pp, required)** |
| **Measurable outcomes** | "success … articulated through sound mechanisms that assess the development and delivery" | Theme 3 Metrics; the supplement |
| **Quantitative usage / adoption metrics** | "quantifiable metrics for … anticipated community adoption and usage"; "the breadth of the user community" | Theme 3 + the supplement |
| **Yearly targets** | "quantitative metrics with targets identified for each year of the award"; "clearly show what the project will accomplish each year" | Theme 3 + the supplement; the timeline table |
| **Metric collection viability** | "viability of the mechanisms employed for collecting the metrics should be described" | the supplement |
| **Management / coordination** | Elements/Transition: in the Project Description. Framework: **separate Management and Coordination Plan (3 pp)** with roles, cross-org mechanisms, budget pointers | Project Description "Close Collaboration" / management subsection (Elements) |
| **Participating directorates/divisions** | proposal "must explicitly state alignment with participating directorates/divisions/offices" | a dedicated paragraph in the Project Description (the current draft has "Alignment with NSF Directorates and Divisions") |
| **Prior CI funding evidence** | PIs with prior CI awards: "show quantifiable evidence of the use, impact and sustainability of the previously funded work" | Results from Prior NSF Support |
| **Security / usability balance** | "balance the security and usability of the infrastructure in a way that directly supports the underlying science drivers"; protection against attack; secure sharing | Theme 2; O2 threat model + security review |
| **AI/ML, privacy, trust, energy** | address "disruptive changes … and emerging concerns (privacy, trust, transparency, reproducibility, AI/ML support, energy efficiency)" | Theme 1 Innovation — relevant to the human-in-the-loop agent layer framing |
| **License declaration** | "identify intended software/data CI license and justification" | Theme 3; DMSP |

### Required supplementary documents (NSF 22-632 §V.A)

Anything not on this list (or in the PAPPG) → **returned without review**.

| Document | Page limit | Required for | Notes |
|---|---|---|---|
| Project Summary | 1 | all | Overview / IM / BI; add keyword `HTCAccess` only if requesting HTC |
| Project Description | 15 (draft uses ~10) | all | Three themes; separate Broader Impacts section; directorate-alignment statement |
| **Delivery Mechanism and Community Usage Metrics** | 2 | **all** | deliverables mechanism + quantifiable metrics with **yearly targets** + collection methodology |
| **Management and Coordination Plan** | 3 | **Framework only** | Elements addresses management inside the Project Description |
| **CI Professional Mentoring / Professional Development Plan** | 2 | **if any CI-professional effort is charged** (RSE, programmer, data scientist, sysadmin, facilitator …) | assessed under Broader Impacts; `SUBMISSION_READINESS.md` item 5 flags that the PI's software-engineering effort may trigger this |
| High-Throughput Computing Resources Request | 2 | if requesting HTC via NSF | task/ensemble/resource breakdown |
| Letters of Collaboration | — | optional | **intent only**, no endorsements/laudatory language; every writer also goes on the Personnel/Partner list |
| Project Personnel and Partner Organizations list | — | all | numbered: name; organization(s); role |
| Biographical Sketch (SciENcv) | per PAPPG (≈2) | all senior/key personnel | anyone with a biosketch counts as Senior Personnel for the participation limit |
| Current & Pending (Other) Support (SciENcv) | per PAPPG | all senior/key personnel | |
| Data Management and Sharing Plan | per PAPPG (draft uses 2) | all | reviewers asked to assess |
| Budget and Budget Justification | per PAPPG | all | no voluntary cost sharing; include NSF PI-meeting travel |
| Mentoring Plan | per PAPPG (1) | if postdocs/students trained | assessed under Broader Impacts |
| Facilities, Equipment & Other Resources | per PAPPG | all | PACE, GT VM, etc. — as resources, not committed cost sharing |

### Solicitation-specific review criteria (NSF 22-632 §VI.A)

Standard IM + BI, **plus** the three-theme criteria — reviewers score all of
them:

- **Theme 1:** Does it fill well-recognized S&E needs and advance significant
  areas? Broader impact beyond initial targets, to underrepresented
  communities, education, workforce? What well-recognized science outcomes does
  the CI enable? What innovative/transformational capability?
- **Theme 2:** Architecture and engineering process (design/dev/docs/test/
  validation/release)? How are security, privacy, trustworthiness, provenance,
  transparency, reproducibility, usability integrated? Adaptable to new
  technology? Builds on / leverages existing NSF & national CI? Engages CI
  experts with domain scientists? How is the project (incl. collaboration)
  managed? Community-engagement mechanisms?
- **Theme 3:** Are services and delivery clearly articulated? Long-term impact
  sustained beyond the award, following an established sustainability model?
  Quantifiable metrics for development/delivery **and** for community
  adoption/usage, with **per-year targets**?

Weighting differs by class: Elements → Innovation weighted more; Framework →
planning/leveraging/stakeholder engagement; Transition → convincing adoption
metrics.

### Eligibility and the participation limit (NSF 22-632 §IV)

- No PI-degree or organization-count restriction.
- **Hard limit: an individual may be PI, co-PI, or Senior Personnel on _at
  most one_ proposal across all three CSSI classes per solicitation cycle.** A
  second proposal with that person is **returned without review, no
  exceptions.** Anyone with a biosketch in the proposal counts.
  - **Implication for CryoStack:** if Kyanjo or Robel is named on *any other*
    CSSI proposal this cycle (as co-PI, senior personnel, or subaward lead),
    the CryoStack proposal dies. Check with every potential collaborator before
    listing them. This also constrains who can be a *funded* design partner.
- Deadlines: December 1 annually (was Dec 16 2022; Dec 1 2023; **Dec 1 2025**;
  Dec 1 annually thereafter → **December 1, 2026** for this cycle).

---

## 4. Compliance matrix

Columns: **Requirement** → **What NSF asks for** → **Existing CryoStack
evidence** → **Evidence expected from the JOSS paper** → **Gap remaining** →
**Candidate NSF proposed activity** → **Where it must appear**.

| Requirement | What NSF asks | CryoStack evidence at HEAD | JOSS-paper evidence | Gap remaining | Candidate CSSI activity | Where in proposal |
|---|---|---|---|---|---|---|
| Demonstrated scientific need | well-recognized S&E need | ICESEE + CryoLauncher usage in the group; the manual data→model→DA integration burden is documented | JOSS "Statement of Need" cites the fragmented lifecycle and the missing access/operations layer | need is asserted, not yet quantified with external users | user study + baseline adoption table; letters from external groups describing the pain | Theme 1; Delivery/Metrics supplement; letters |
| Significant bottleneck (compelling geoscience question) | overcome a bottleneck to compelling science | (see §5 — the code is prior work, not the bottleneck) | JOSS shows the platform exists and what it cannot yet do (cross-model result contract, ICESEE diagnostics, portable HPC, archival provenance) | the proposal must name the *science* blocked by those gaps (multi-model observation-constrained ice-sheet state/parameter estimation with quantified structural uncertainty) | O1 cross-model result/observation contracts + CryoBench; O3 provenance — framed as unblocking that science | Theme 1 opening; O1/O3 |
| Integrated CI services | science-driven, innovative, collaborative, leveraged, strategic, sustained | gateway + identity + workspaces + experiments + Control Center + deployment registry + connector + remote Slurm + AWS Batch (ISSM) | JOSS "Software Architecture" through "Reproducible Experiment Lifecycle" documents all of it as implemented | services are single-institution, developer-operated, not community-governed | O2/O3 hardening + operations + governance | Theme 2; Theme 3 |
| Reusable services | disseminated as reusable services | model-adapter contract, `ExecutionBackend` contract, dataset-manifest/adapter, capability registry, result-package protocol | JOSS "Model capability registry", "Results, Packaging, and Visualization", Frozen Legacies "two kinds of extensibility" | contracts are internal, not versioned public SDKs with templates/fixtures/deprecation policy | O1 Task 1.1 — versioned application/model/dataset/observation-bundle SDKs + template repos | O1; DMSP |
| Community-driven CI | co-design with domain scientists; community engagement mechanisms | ICESEE user base; LIVIST (Dawson) and Frozen Legacies (external radar tools) integrations are already multi-contributor | JOSS Acknowledgements name external contributors | no design-partner program, no advisory board, no contribution/governance docs | O3 Task 3.3 — governance kit, advisory reviews, contribution pairing | Theme 2 Close Collaboration; O3; letters; Personnel list |
| Interoperability | cross-resource, cross-model discovery/access/transfer | connector (direct SSH + workstation connector), Spack + Apptainer environments, transport-neutral result packages | JOSS "HPC Connector", "Cloud and Container Architecture", "Results" | one cluster (PACE) exercised; ISSM-only cloud; no common observation-bundle schema; ICESEE has no result contract | O2 backend qualification (PACE + AWS + BYO-account); O1 observation-bundle schema; O1 `cryostack.icesee.results` | O1; O2 |
| Reproducibility | integrated into the engineering process | per-run working copies, immutable config snapshot, Spack locks / digest-pinned images, ~1,280 tests + offline acceptance command | JOSS "Reproducible Experiment Lifecycle" + "Verification"; explicitly lists the missing archival fields | no environment digest / input-output checksums / transformation records / exportable run manifest; no scientific acceptance gate | O1 CryoBench (analytic/restart/DA-diagnostic/scaling/SBOM gates); O3 archival provenance manifest + citation-ready run bundle | O1 Task 1.3; O3 Task 3.1 |
| Provenance | workflow + artifact integrity/provenance | experiment records + event timeline + job/cluster identifiers; agent layer's digest + input fingerprint + trace/provenance split | JOSS "Identity, workspaces, and experiment persistence" (basis for provenance) + agent section | not a cross-application machine-readable schema; not FAIR-published | O3 versioned experiment/provenance registry; observation-bundle provenance | O3 Task 3.1; DMSP |
| Sustainability | sustained beyond award; established model; transition path | MIT license; open repo; container + Spack distribution; local-usable core | JOSS "Availability" + closing paragraph on what community operation needs | no five-year operations estimate, no minimum-staffing analysis, no chosen support model | O3 Year-3 five-year sustainability plan + maintainer handoff; identify institutional / community-allocation / later Transition-to-Sustainability path | Theme 3; O3 |
| Community creation | catalyze a community that scales | four apps, external contributors, GT PACE reference deployment | JOSS establishes the platform others could build on | no external adopters measured; no workshops held; no contributor governance | O3 workshops (3), office hours, contribution guide, code of conduct, adapter proposal template | Theme 1 + O3; Delivery/Metrics supplement |
| Education / workforce | integrated, not the focus | laptop-scale tutorials (Lorenz-96 via ICESEE), Jupyter Book docs, public Developer Guide | JOSS notes browser access lowers the entry cost for students/instructors | no formal training program, no accessibility (WCAG) review, no evaluation instruments | O3 Task 3.2 user/accessibility evaluation; O3 Task 3.3 workshops prioritizing MSIs/EPSCoR; CI Professional plan if effort is charged | Broader Impacts; O3; CI Professional plan (if applicable) |
| Interdisciplinary use | benefit communities beyond initial targets | contracts are model-agnostic; Frozen Legacies proves a data-side axis | JOSS: "the same adapter, validation, provenance, and execution contracts apply to glacier, climate, and geophysical models" (stated as potential) | no non-ice-sheet adapter exists | keep as *potential* in Broader Impacts; do **not** promise a non-cryosphere adapter in an Elements award | Broader Impacts; directorate alignment |
| Delivery mechanisms | how services reach users; leverage ACCESS etc. | hosted gateway at cryostack.eas.gatech.edu; connector binaries; container/Spack recipes; docs site | JOSS "CryoStack is available at …" + deployment registry | no ACCESS/leadership-computing/Software-Institute linkage; connector binaries lag HEAD | O2/O3 — document delivery via GT gateway + BYO-account + container/Spack + (optionally) an ACCESS allocation path | **Delivery Mechanism and Community Usage Metrics supplement**; Theme 3 |
| Measurable outcomes + yearly targets | quantitative, per-year, collection method described | offline acceptance command produces a machine-readable pass/fail report; experiment DB records runs per user | JOSS reports concrete test/acceptance counts at a pinned revision | no adoption instrumentation (unique users, runs, institutions, external groups) surfaced as metrics; no baseline | O3 Task 3.1 "privacy-preserving metric export" in the Control Center; the metrics supplement with Y1–Y3 targets | **Metrics supplement**; Theme 3; timeline table |
| Management / coordination | roles, cross-org, mechanisms (Elements: in Project Description) | two-person team, weekly meetings, ADR practice (proposal already describes this) | n/a (JOSS is not a management document) | if Framework or multi-institution: no formal Management & Coordination Plan | keep management in the Project Description for Elements; add the 3-pp plan only if moving to Framework | Project Description management subsection |
| Directorate alignment | explicit statement | GT SEAS; cryosphere science; HPC/CI engineering | n/a | the current draft names CISE/OAC + GEO/OPP + GEO/EAR — verify each is a *participating* unit in 22-632 (§6 below) | keep the alignment paragraph; strengthen OPP tie | Project Description alignment paragraph; Project Summary |
| Prior-CI-support evidence | quantifiable use/impact/sustainability | Award 2235920 (CAREER, Robel) produced ICESEE (open, Zenodo DOI, JOSS/EGUsphere), container + Spack distribution | JOSS paper itself becomes citable evidence of a delivered platform | current draft "promises final counts" — a reviewer red flag | replace with actual numbers before submission (see §10) | Results from Prior NSF Support |
| Security / usability balance | protect against attack; secure sharing; balance with science drivers | scrypt, PKCE/state flows, HTTP-only cookies, same-site redirects, RBAC, per-user containment, no static cloud creds, relay v2 capability secrets, agent permission ceiling | JOSS documents all of the above *and* the residual gaps (generic shell channel, process-local relay state, OTP bootstrap) | no external security review; connector protocol not allow-listed | O2 Task 2.1 threat model + allow-listed connector + independent GT security review | Theme 2; O2 |
| License declaration | name + justify the CI license | MIT (+ inconsistent BSD-3-Clause identifiers) | JOSS flags the inconsistency twice | inconsistency unresolved; no SBOM/license manifest | O2 Task 2.2 license reconciliation + SBOMs + license manifests | Theme 3; DMSP; O2 |

---

## 5. The bottleneck framing (NSF 22-632 §II — the load-bearing requirement)

NSF: *"All projects must be designed to overcome significant bottlenecks to
solving compelling S&E questions"* — and for geosciences specifically,
*"compelling geoscience questions."* Reviewers look for this first. A proposal
that reads as **"we built CryoStack and want funding to add features"** fails
this criterion.

**Do not frame the proposal as feature work on CryoStack.** Frame it as:
CryoStack has removed the *first* layer of friction (access, execution,
persistence); the *scientific* bottleneck that remains is what the award
attacks.

Candidate bottleneck statements (the team must choose and sharpen one — this is
an **OWNER_CHECKPOINT** for the Co-PI as science lead):

1. **Structural uncertainty in observation-constrained ice-sheet projection.**
   Sea-level projections from ice-sheet models carry large, poorly quantified
   *structural* uncertainty because each model is assimilated and diagnosed in
   its own bespoke pipeline, so differences cannot be attributed to model
   physics versus undocumented staging and post-processing. *Compelling
   question:* how much of the spread in projected Antarctic/Greenland
   contribution is model-structural, and which basal/rheological parameters are
   actually constrained by current observations? *Why existing approaches fail:*
   no common observation bundle, ensemble specification, diagnostic definition,
   or provenance record across ISSM, Icepack, PISM. *CryoStack as prior work:*
   the platform runs two of these models today through one interface with
   per-user isolation and structured results. *Remaining CI challenge:*
   versioned scientific workflow/result/observation contracts + a scientific
   acceptance gate (CryoBench) + machine-readable provenance so a multi-model
   experiment is reproducible and attributable.

2. **Loss of decades of Antarctic radar observations.** Historical airborne
   radar holdings (and the interpretation expertise around them) are
   disappearing; they are not in a form that can initialize or validate modern
   models. *Compelling question:* what do pre-satellite-era radar surveys tell
   us about past ice thickness and bed conditions, and can they constrain
   model initial states? *Why existing approaches fail:* desktop-only,
   provenance-poor, non-FAIR. *CryoStack as prior work:* Frozen Legacies
   already registers, catalogs, and geolocates one collection. *Remaining CI
   challenge:* a dataset SDK + observation-bundle schema + provenance-captured
   processing so preserved observations feed initialization/assimilation.

3. **Portability of validated workflows across institutional HPC.** A DA
   experiment validated on one cluster cannot be moved to another researcher's
   allocation without re-engineering scheduler, environment, and staging logic,
   and the public control plane that would enable this is a security problem.
   *Compelling question:* can a community run the *same* observation-constrained
   experiment on whatever resource their institution provides and get a
   comparable, reproducible answer? *Why existing approaches fail:* containers
   and Spack do not supply job authorization, staging, monitoring, recovery, or
   a portable execution record; storing keys or exposing a shell is
   unacceptable. *CryoStack as prior work:* the connector relay + B3 identities
   + typed operations already do a first version of this. *Remaining CI
   challenge:* an allow-listed, auth-bound, replay-safe execution fabric
   qualified on ≥2 backends.

The strongest proposal probably leads with **(1)** as the science bottleneck
and uses **(2)** and **(3)** as the enabling CI sub-problems.

**Required logic chain for the Project Description:**

```
compelling geoscience question (structural uncertainty in observation-
    constrained ice-sheet state/parameter estimation; fate of legacy
    observations)
  → why existing approaches are insufficient (bespoke per-model pipelines;
    no shared contracts; non-portable HPC; non-FAIR observations; no
    scientific acceptance gate)
  → CryoStack (JOSS paper) demonstrates feasibility and prior work (one
    gateway, two models, remote HPC, per-user isolation, structured results,
    connector, cloud foundations, human-in-the-loop approval boundary,
    test/acceptance infrastructure)
  → remaining CI research/development challenges (versioned scientific
    contracts; CryoBench; hardened portable execution fabric; archival
    provenance + run bundles; observation-bundle schema; community framework)
  → specific CSSI activities (O1/O2/O3 tasks)
  → deliverable community services (SDK + CryoBench + qualified backends +
    provenance registry + connected data-to-model demo + governance)
  → quantitative adoption / scientific-impact metrics (users, runs,
    institutions, adapters, reproduced experiments, external contributors)
  → sustainability beyond the award (institutional hosting + portable
    recipes + community allocations + later Transition-to-Sustainability)
```

---

## 6. NSF science constituencies for CryoStack (NSF 22-632 §II directorate table)

| Unit | Participating in 22-632? | Fit for CryoStack | Who would actually use the CI |
|---|---|---|---|
| **CISE / OAC** | Yes — the lead office | **Primary.** OAC funds "software/data engineering and infrastructure … broad applicability … sustaining discovery across all fields." CryoStack's contract-based separation of scientific adapters from execution backends and the human-in-the-loop approval boundary are OAC-relevant CI research. | RSEs and CI facilitators building model-coupled workflows; other Earth-science gateway teams reusing the connector/relay and result-contract patterns |
| **GEO / OPP (Office of Polar Programs)** | Yes — 22-632 lists OPP with interests including "sea/land ice melt" and "interdisciplinary research on polar system interactions" | **Primary domain alignment.** The scientific users (ice-sheet dynamics, Antarctic radar, sea-level-relevant cryosphere) are OPP's community. | Antarctic/Greenland ice-sheet modelers; radar/geophysics groups; polar data stewards; students in polar programs without local HPC staff |
| **GEO / EAR (Earth Sciences)** | Yes — "geophysics, continental hydrology, geomorphology, tectonics, geobiology" | **Secondary, justified.** Geophysical inverse problems and Earth-system modeling; the ensemble-DA + adapter machinery generalizes to other solid-earth inverse problems. | Geodynamics / glacial-isostatic-adjustment / subglacial-hydrology modelers doing inversion |
| **GEO / AGS, OCE** | Yes | **Weak / future.** Climate and ocean forcing of ice sheets is a coupling interest, but no code path today. Mention only as a downstream interoperability possibility. | coupled climate–ice or ocean–ice modelers, later |
| **CISE / CCF, IIS** | Yes | **Weak.** The agent/approval-boundary work has an IIS (human-AI interaction) angle, but leading with it would misrepresent the project. Keep as a one-line Innovation note. | — |
| **ENG / CBET, CMMI** | Yes — "Earth systems", "multi-scale modeling tools", "computational error assessment" | **Weak / opportunistic.** Only if a genuine environmental-modeling co-design partner appears. Do not claim without one. | — |
| **EDU** | Yes | **Not a fit as primary.** CSSI explicitly routes education-focused proposals to CyberTraining; keep education integrated in Broader Impacts only. | instructors using tutorials |

**Recommended alignment statement:** primary **CISE/OAC**; domain **GEO/OPP**;
secondary **GEO/EAR**. This matches the current draft. Before submission,
**contact the cognizant OAC and OPP program officers** (the solicitation and
the current draft both call for this) to confirm fit, the Elements-vs-Framework
choice, and budget range.

---

## 7. Preliminary-work evidence CryoStack already provides

These are **prior work / feasibility**, established by the code and the JOSS
paper. **They must appear as accomplishments, never as proposed activities.**

| Capability | Preliminary-work claim it supports | JOSS section that documents it |
|---|---|---|
| Browser-accessible scientific workflows | a scientist can configure and launch ISSM/Icepack/ICESEE runs from a browser with no local model install | Gateway; CryoLauncher; Reproducible Experiment Lifecycle |
| HPC execution | real Slurm submission via direct SSH or an outbound workstation connector; job lifecycle (`sbatch`/`squeue`/`sacct`/`scancel`); log/result return | HPC Connector and Remote Execution |
| Multiple scientific applications / models | four applications; two model adapters behind one capability registry; two extensibility axes (model, dataset) | Scientific Applications; Model capability registry; Frozen Legacies |
| Reproducible environments | Spack source builds + Docker/Apptainer images; digest-pinned model images; container publication layer | Cloud and Container Architecture |
| User isolation | trusted session identity; per-user owner roots enforced by a containment check; per-user run directories; canonical examples read-only | Identity, workspaces, and experiment persistence |
| Provenance (basis) | immutable configuration snapshot + event timeline + job/cluster identifiers per experiment; agent digest + input fingerprint + trace/provenance separation | Identity/experiment persistence; Human-in-the-Loop section |
| Structured results | transport-neutral result packages (`cryostack.issm.results`, `cryostack.icepack.results`) with model-free readers and a shared reader/visualizer protocol; deterministic visualization | Results, Packaging, and Visualization |
| Connector architecture | outbound-only WebSocket relay; keys stay on the workstation; no inbound connection to workstation or cluster; relay v2 per-user session binding + capability secrets; B3 namespaced SSH identities | HPC Connector and Remote Execution; Figure 2 |
| Cloud foundations | implemented end-to-end AWS Batch path for ISSM (config → preflight → S3 staging → submit-job → job-id → run registration → lifecycle); `aws`-CLI-only, no static credentials | Cloud and Container Architecture |
| Application / model abstraction | `ExecutionBackend` submit/status/logs/terminate contract; provider-independent cloud driver contracts; capability registry consumed by gateway, results, visualization, assistant | CryoLauncher; Model capability registry; Cloud |
| Agentic / human-in-the-loop foundations | request → declarative RunPlan → CryoStack validation (B3/B4/Basic-mode/preflight) → plan digest + input fingerprint → explicit human approval → existing execution infrastructure; LLM advisory only; no vendor SDK; opt-in Beta panel with no submit control | Human-in-the-Loop Run Assistance (Experimental) |
| Testing / acceptance infrastructure | ~1,280 Python tests + 208 agent tests + browser connector-page tests, green at a pinned revision; `python -m cryostack_src.acceptance --offline` read-only invariant checks with a machine-readable report | Availability, Verification, and Limitations |

---

## 8. Genuinely unresolved problems (evaluated, not auto-accepted)

For each: is it a real CSSI-grade problem, or is it routine engineering /
already done?

| Candidate | Verdict | Reasoning |
|---|---|---|
| Individual applications → sustainable community framework | **Strong.** | This is exactly the CSSI Elements-to-Framework arc. Genuinely unresolved: no external adopters, no governance, no versioned SDK, no maintainer plan. But it must be *scoped to Elements* (contracts + one new model + one dataset + first governance kit), not promised as a finished framework. |
| Portable execution across institutional HPC | **Strong.** | Real research problem: a public control plane reaching user-authorized resources without stored keys or a shell, qualified on ≥2 sites. CryoStack has v1; the allow-listed, replay-safe, resource-policy-bound version is unbuilt and non-trivial. High reviewer appeal (security + usability + science). |
| Standardized scientific workflow / result contracts across models | **Strong, and this is the intellectual core.** | Not routine: defining an observation bundle, ensemble spec, state-vector packing, observation operator, and diagnostic definition that ISSM/Icepack/PISM can all satisfy, with versioning and a conformance test, is a research contribution. Directly serves the bottleneck in §5(1). |
| Reproducible model / environment distribution | **Medium.** | Spack + containers + digest pinning exist. The unsolved part is SBOMs, license manifests, lock-file provenance, and *scientific* smoke tests as a release gate — worth including but not a headline. |
| Scalable cloud / HPC interoperability | **Medium, needs care.** | The ISSM AWS Batch path exists; ICESEE's MPI ensemble genuinely does not fit single-container Batch — a real gap. But "scalable cloud interoperability" in general is broad and easy to over-promise. Scope to: qualify PACE + one AWS profile + a bring-your-own-account path with the *same* experiment spec, and name the MPI-cloud primitive as a bounded investigation, not a deliverable. |
| Community onboarding of additional models | **Strong but must be bounded.** | PISM is the right single target (mature community, complementary architecture, open, no proprietary license). Do **not** promise Elmer/Ice, SICOPOLIS, etc. — name them as the pathway the SDK enables. |
| FAIR / provenance-aware scientific workflows | **Strong.** | The archival provenance manifest (code/adapter versions, image digests / Spack locks, input-output checksums, seeds, diagnostics) + citation-ready run bundle is unbuilt and is a clean CSSI deliverable that maps to NSF's explicit provenance/reproducibility criterion. |
| Observational-data integration | **Medium-strong.** | The observation-bundle schema connecting a Frozen Legacies / LIVIST product to model initialization/assimilation is unbuilt and is the "data-to-model" story reviewers like. One demonstration is enough for Elements. |
| Education / training | **Keep small.** | Required as *integrated* Broader Impacts, not a focus (CSSI routes education-first work to CyberTraining). Workshops + tutorials + accessibility review are appropriate; a curriculum is not. |
| Community governance | **Strong as a deliverable, cheap to do.** | Contribution guide, code of conduct, adapter proposal template, maintainer-rotation policy, security-reporting channel. Unbuilt today; low cost; directly addresses the "sustained/community" criterion. |
| Sustainability | **Required, currently weak.** | No five-year operations estimate, no minimum-staffing analysis, no chosen model. This is a genuine gap the award should close in Year 3, and reviewers will look for it. |
| Quantitative adoption / usage infrastructure | **Strong and underappreciated.** | NSF wants "viability of the mechanisms employed for collecting the metrics." CryoStack already has the experiment DB and the acceptance-report format; turning that into privacy-preserving metric export in the Control Center is a concrete, credible O3 deliverable that *also* produces the numbers the proposal needs. |
| Safe human-in-the-loop agentic scientific workflows | **Real, but position carefully.** | The digest-bound approval boundary + input fingerprint + advisory-LLM design is a genuine CI-research contribution and touches NSF's "AI/ML support, trust, transparency" language. **Risk:** a cryosphere-CI proposal that leans on "agentic AI" can read as trend-chasing. Position it as *one* Innovation thread — a safety architecture for assistant-guided run preparation with human approval as the execution authority — not as a project objective. Keep it out of the headline and the metrics. |

---

## 9. Quantitative metrics CryoStack could realistically commit to

Categories separated per the directive. **Every number below is a placeholder
requiring an OWNER_CHECKPOINT** — the PI/Co-PI must set targets they will
actually be evaluated against; NSF review penalizes both fantasy numbers and
absent numbers. Collection mechanism noted because §V.A requires it.

### Software-development metrics
- Versioned SDK contract releases (application / model / dataset /
  observation-bundle): target per year. *Mechanism:* Git tags + release notes.
- Test count and coverage of shared layers; CI pass rate on protected branches.
  *Mechanism:* CI dashboard (already have ~1,280 tests + the acceptance suite).
- Public API/contract documentation pages. *Mechanism:* docs site build.

### Service-reliability metrics
- Gateway uptime / availability of the reference deployment. *Mechanism:*
  route health checks (already implemented) → uptime log.
- Median time from run submission to first status update; failed-run rate with
  a diagnosed cause. *Mechanism:* experiment DB event timestamps.
- Mean time to recover a failed remote/cloud run. *Mechanism:* incident log.

### Supported-model / application metrics
- Number of qualified model adapters (baseline **2**: ISSM, Icepack; committed
  **+1**: PISM). *Mechanism:* CryoBench pass records.
- Number of qualified dataset adapters (baseline **1**: LYRA; committed
  **+1**). *Mechanism:* manifest validation + qualification checklist.
- Number of qualified execution backends (baseline: local + PACE Slurm +
  connector; committed: + one AWS profile). *Mechanism:* backend qualification
  test suite.
- Examples runnable end-to-end per model. *Mechanism:* the capability matrix
  the code already tracks (`overnight/AUDIT_icesee_...` / example matrices).

### Institutional / HPC portability metrics
- Number of distinct institutional HPC systems on which a common experiment
  spec runs to completion (baseline **1**: PACE; target **≥2**). *Mechanism:*
  a portability test log with site + date + job id (redacted).
- Number of external groups that connected their own resource via the
  connector. *Mechanism:* connector session records (owner-scoped; aggregate
  count only).

### Reproducibility metrics
- Fraction of runs that produce a complete provenance manifest. *Mechanism:*
  manifest presence check in the result package.
- Number of independently reproduced shared experiments (a second user re-runs
  a published run bundle and matches within tolerance). *Mechanism:* CryoBench
  reproduce-a-bundle test + a public "reproduced" log.
- Number of published citation-ready run bundles with DOIs. *Mechanism:* Zenodo
  deposition records.

### User / community adoption metrics
- Annual unique authenticated users; new users per quarter. *Mechanism:*
  privacy-preserving metric export from the auth DB (an O3 deliverable).
- Completed non-test scientific runs per year. *Mechanism:* experiment DB,
  filtered to non-`test_mode` runs.
- Distinct external adopting groups (institution + contact). *Mechanism:*
  lightweight registration or opt-in survey.
- External code/documentation contributors (cumulative). *Mechanism:* Git
  history + merged-PR authorship.
- GitHub stars / forks / clones / release downloads. *Mechanism:* GitHub
  traffic API + release assets.

### Training / workforce metrics
- Workshops delivered and participants (prioritize MSIs, EPSCoR jurisdictions,
  no-local-HPC-staff institutions). *Mechanism:* registration + attendance.
- Office-hours sessions and attendees. *Mechanism:* calendar + sign-in.
- CI professionals mentored (if any effort is charged) and their outcomes
  (papers, talks, career steps). *Mechanism:* the CI Professional plan's own
  tracking.
- Accessibility conformance level achieved on core workflows (target WCAG 2.2
  AA). *Mechanism:* accessibility audit report.

### Scientific-use metrics
- Peer-reviewed publications using CryoStack (by the team and by others).
  *Mechanism:* citation tracking + a "powered by CryoStack" request.
- Multi-model experiments completed (same observation bundle through ≥2
  adapters). *Mechanism:* CryoBench cross-model records.
- Data-to-model demonstrations (a Frozen Legacies / LIVIST product feeding an
  initialization or assimilation). *Mechanism:* documented use-case runs.
- Parameters/fields shown to be observationally constrained in a demonstration
  study. *Mechanism:* the science use-case writeups.

**Guidance:** the current proposal's headline targets (5 adapters, 100 annual
users, 1,000 runs in Year 3, 8 external groups, 50 workshop participants, SUS ≥
75, 3 external contributors) are *plausible for an Elements award only if*
baseline numbers exist now and the trajectory is credible. **OWNER_CHECKPOINT:**
re-derive every target from a measured Year-0 baseline (§10) rather than from a
round number.

---

## 10. Evidence to start collecting **before** the Fall 2026 submission

The proposal is stronger with numbers than with prose. All of the following are
realistically accumulable between now (September 2026) and December 1, 2026,
and most are already latent in the system.

| Evidence | How to get it now | Effort | Why it matters |
|---|---|---|---|
| **Baseline authenticated users** | count in the auth DB; note growth since deployment | low | Results from Prior NSF Support; the metrics baseline (`SUBMISSION_READINESS.md` item 6) |
| **Completed non-test runs** (local + PACE + cloud) | filter the experiment DB for non-`test_mode` runs; break down by model and backend | low | preliminary work; proves the pipeline is used, not just built |
| **Successful real HPC executions** | run 3–5 real ISSM/Icepack jobs on PACE end to end; capture job ids, wall times, result packages, and one visualization each | medium (needs the PACE/Duo path — `SUBMISSION_READINESS.md` item 7) | directly answers "does the connector actually work"; a figure for Theme 2 |
| **One real cloud run** | one qualified ISSM AWS Batch run on a controlled account (small); capture cost, time, S3 layout, provenance | medium (needs a controlled account + MATLAB license decision) | de-risks the O2 AWS claim; a reviewer will ask |
| **One reproducibility demonstration** | one person publishes a run bundle; a second re-runs it and shows the result matches within tolerance | medium | the single most persuasive artifact for the reproducibility criterion |
| **Icepack exporter validated on real Firedrake** | run one Icepack tutorial in the `with-icepack` container; confirm the exporter output | medium | removes a JOSS limitation and a proposal credibility risk |
| **Distinct institutions / groups touching CryoStack** | list every group that has used ICESEE or CryoStack, with contact and use | low | adoption evidence; candidate letter writers |
| **External testers** | recruit 3–5 people outside the group to run the laptop-scale tutorial and one remote run; collect written feedback + task-completion notes | medium | formative-evaluation baseline; Broader Impacts; possible letters |
| **Named design partners** | secure 2–3 groups (a PISM developer/user; a historical-radar data steward; a Science Gateways / RSE contact; ideally a second institution) willing to write **intent-to-collaborate** letters | medium–high | Framework-vs-Elements lever; §V.A letters; Personnel list; the "community-driven" criterion |
| **PISM use-case specification** | Co-PI defines domain, assimilated observations, state/parameters, ensemble size, acceptance thresholds, compute estimate (`SUBMISSION_READINESS.md` item 10) | medium | O1 Task 1.2 credibility; without it the PISM plan is hand-wavy |
| **One workshop or tutorial delivered** | run a short hands-on session (even internal-to-department or at a conference) and record participants + materials | medium | Broader Impacts; workforce metric baseline; "we have done this before" |
| **GitHub activity snapshot** | pull stars/forks/clones/downloads/contributors/releases from the GitHub API; take a dated snapshot now and another just before submission | low | adoption trajectory; Results from Prior NSF Support |
| **Documentation usage** | enable privacy-preserving analytics on the docs site (or note server logs) for a dated baseline | low | delivery-mechanism evidence |
| **Scientific collaborations / publications** | list every paper (submitted or published) that used ICESEE/CryoStack; request "powered by" acknowledgement going forward | low | scientific-use metric; prior-support evidence |
| **JOSS submission status** | submit the JOSS paper as early as possible; a "submitted"/"in review"/"published" status is citable in the proposal | low (paper is ready) | the proposal's central prior-work citation |
| **License reconciliation** | resolve MIT vs BSD-3-Clause with GT and contributors (`SUBMISSION_READINESS.md` item 9) | low–medium | removes a stated weakness; needed for the DMSP and O2 |
| **Letters of collaboration drafted** | send the NSF-compliant intent template to each partner with enough lead time | medium | §V.A; must not contain endorsements |
| **PI-participation check** | confirm neither Kyanjo nor Robel is named on any other CSSI proposal this cycle | low | §IV — a violation is an automatic return without review |

**Realistic assessment:** the low-effort items (DB counts, GitHub snapshot,
collaboration list, JOSS submission, participation check) are achievable in
days. The medium items (3–5 real PACE runs, one cloud run, one reproducibility
demo, Icepack validation, PISM use-case, external testers, one workshop) are
achievable by December if started now and are what move the proposal from
"promising" to "demonstrated." The high-effort item (a real second institution
with a funded role) is the one that could change the award class and should be
decided early.

---

## 11. Proposal structure and supplementary documents vs. the solicitation

**Verify every item against the official NSF 22-632 PDF and the PAPPG in force
for December 1, 2026 before relying on it.** The current
`nsf-csi-proposal/` follows the DRaGoN proposal's *typographic* and
*argument-order* conventions (`SUBMISSION_READINESS.md`), which is a stylistic
choice, not a solicitation requirement — the solicitation requirements are
below.

| Mandatory component | Solicitation basis | Present in `nsf-csi-proposal/`? | Note |
|---|---|---|---|
| Project Summary, 1 page, Overview / IM / BI | NSF 22-632 §V.A; PAPPG II.D.2.b | `sections/project_summary.tex` | has Overview / IM / BI headers — good |
| Project Description, 15-page max, three CSSI themes + separate Broader Impacts + directorate-alignment statement | NSF 22-632 §V.A ("Project Description content"); §II themes | `sections/project_description.tex` (~10 pp) | Uses O1–O3 + State-of-knowledge order. **Ensure the three CSSI themes (Motivation/Impact, CI Plans, Measurable Outcomes) are each unmistakably addressed** — a reviewer checks against the solicitation's headings, not DRaGoN's. Broader Impacts is a **separate section** (present). Directorate alignment paragraph present. |
| Delivery Mechanism and Community Usage Metrics, 2-page max: deliverables mechanism + yearly quantitative targets + collection method | NSF 22-632 §V.A (required supplementary doc, all classes) | `sections/delivery_mechanism_metrics.tex` + `documents/` | **Confirm it is uploaded as the named supplementary document, not folded into the Project Description.** Confirm per-year targets and a described collection mechanism. |
| Management / coordination | NSF 22-632 §V.A: **in the Project Description for Elements**; separate 3-page plan **only for Framework** | in `project_description.tex` ("Close Collaboration and Management Plan") | Correct for Elements. If the class changes to Framework, a separate 3-pp Management and Coordination Plan with roles + cross-org mechanisms + budget pointers becomes mandatory. |
| CI Professional Mentoring / Professional Development Plan, 2-page max | NSF 22-632 §V.A: required **if CI-professional effort is charged**; assessed under Broader Impacts | `sections/ci_professional_mentoring.tex` exists | **OWNER_CHECKPOINT (`SUBMISSION_READINESS.md` item 5):** ask the research office whether the PI's software-engineering effort counts as CI-professional support. Include the plan **only if** applicable; an unnecessary supplement risks return-without-review. |
| Data Management and Sharing Plan | PAPPG II.D.2; NSF 22-632 references it | `sections/data_management_plan.tex` (2 pp) | Must name the CI license and justify it; align with the JOSS "Availability" section and the license-reconciliation task. |
| Budget + Budget Justification; no voluntary cost sharing; NSF PI-meeting travel budgeted | PAPPG II.D.2; NSF 22-632 §II, §V, §VII | `sections/budget_justification.tex`, `cssi_elements_budget.xlsx` | $486,436 planning total < $600,000 cap. **Item 2:** replace planning rates with approved GT salary/fringe/F&A. Confirm annual PI-meeting travel is a line item. |
| Facilities, Equipment, and Other Resources | PAPPG II.D.2 | `sections/facilities.tex` / `documents/facilities.tex` | List PACE, GT VM, security/backup as **resources**, not committed cost sharing (prohibited). |
| Biographical Sketches (SciENcv) — all senior/key personnel | PAPPG II.D.2 | `sections/biosketch.tex` present but **not in the combined draft** | **Item 11:** generate via SciENcv. Anyone with a biosketch = Senior Personnel for the §IV participation limit. |
| Current and Pending (Other) Support (SciENcv) | PAPPG II.D.2 | not in repo | Generate via SciENcv for PI and Co-PI. |
| Project Personnel and Partner Organizations list | NSF 22-632 §V.A (required supplementary doc) | `sections/project_personnel_partners.tex` (10 lines) | Numbered `name; organization(s); role`. **Must include every letter-of-collaboration writer and every unfunded collaborator.** |
| Letters of Collaboration (optional) | NSF 22-632 §V.A | none yet | **Intent only**, NSF template language, no endorsements. Items 3, 8. |
| Mentoring Plan (if postdocs/students) | PAPPG II.D.2 | n/a unless a student/postdoc is added (item 3) | assessed under Broader Impacts |
| Results from Prior NSF Support | PAPPG; NSF 22-632 (prior-CI-support evidence) | in `project_description.tex` | **Item 6 / a reviewer red flag:** the draft "promises final counts." Replace with **actual measured numbers** before submission. |
| HTC Resources Request | NSF 22-632 §V.A, if requesting NSF HTC | not applicable unless the team wants NSF HTC | if used, add `HTCAccess` keyword to the Project Summary Overview |

**Do NOT add** any appendix or document not on this list or in the PAPPG —
NSF 22-632 §V.A: such proposals are **returned without review**.

---

## 12. Issues in the current `nsf-csi-proposal/` (flagged, NOT edited)

| Category | Finding | Where | Recommended fix (later pass) |
|---|---|---|---|
| **Weak bottleneck framing** | §IM opens with "Ice-sheet science increasingly depends on integrating …" and lists tasks; it never states a *single compelling geoscience question* that is *blocked* today. Reads closer to "integration is hard" than "this science cannot be done." | `project_description.tex` §IM | Open with the §5 bottleneck: structural uncertainty in observation-constrained ice-sheet state/parameter estimation; make CryoStack the prior work that makes attacking it feasible. |
| **Proposes work partly already done** | "modular AWS components" / "AWS discovery/provisioning modules are not yet an end-to-end qualified CryoLauncher workflow" understates HEAD — the end-to-end ISSM AWS Batch path exists (JOSS "Cloud" section). "shared platform tests are sparse" is no longer true (~1,280 tests + acceptance command). "CryoLauncher has working local and Slurm pathways" — local is ICESEE-only. | `project_description.tex` §IM ¶2, §SOK; `project_summary.tex` | Move the claim to the *qualifier* (per-user S3, job-def allow-list, budget/quota/cleanup, real-account qualification) and to the *scientific gate* (CryoBench), not test volume. Tighten "local" to "Slurm and cloud." See `JOSS_TO_NSF_HANDOFF.md` §2. |
| **Missing quantitative baseline** | Metrics targets (5 adapters, 100 users, 1,000 runs, 8 groups, SUS ≥ 75, 3 contributors) are stated as "targets for evaluation, not claims of current adoption" but there is **no Year-0 baseline** to make them credible. | §"Integrated measurable outcomes"; `delivery_mechanism_metrics.tex` | Collect the §10 baseline; re-derive each target from it; state the baseline explicitly in Results from Prior NSF Support and the metrics supplement. |
| **Community evidence absent** | No named external design partners, no advisory board, no letters, no measured adopters. The "community-driven" criterion (§VI.A Theme 2) is asserted, not evidenced. | throughout | Secure 2–3 intent-to-collaborate letters (§10); add writers to the Personnel list; describe a concrete design-partner review cadence. |
| **Sustainability under-specified** | "publish a five-year operations estimate … in Year 3" defers the entire sustainability analysis to the end of the award. §VI.A Theme 3 wants a sustainability *approach following an established model* stated up front. | §"Sustained and Sustainable Impacts" | Name the intended model now (institutional hosting + portable recipes + community allocations + a later Transition-to-Sustainability proposal), with Year-3 refinement — not Year-3 origination. |
| **Prior-support section promises future counts** | "its resulting publication is [cite]" and language promising final counts. Reviewers read unfilled promises as a weakness. | §"Results from prior NSF support" | Replace with measured use/impact/adoption numbers for Award 2235920 / ICESEE; cite the JOSS paper (submitted/in review/published) as delivered prior work. |
| **Directorate list needs verification** | Draft names CISE/OAC, GEO/OPP, GEO/EAR. All three are participating units in 22-632 (§6), but confirm the exact division names and that "CISE interest in software engineering that advances another scientific discipline" language matches the current solicitation. | §"Alignment with NSF Directorates and Divisions" | Verify against the 22-632 directorate table; keep OAC primary + OPP domain + EAR secondary; add the PO-contact sentence (already present). |
| **License inconsistency stated as a Year-1 task** | The proposal carries "reconcile the present BSD/MIT metadata discrepancy" as O2 Task 2.2 work. It is also a JOSS-flagged weakness and a DMSP dependency. | §research Task 2.2; DMSP | Resolve in the repo before submission if possible; if not, keep as an early Year-1 task and note it is already identified (which shows diligence, not neglect). |
| **Scope reads Framework-sized for an Elements budget** | O1+O2+O3 as written (versioned SDK + CryoBench service + PISM + dataset adapter + threat model + rebuilt connector protocol + two qualified backends + SBOMs + provenance registry + observation-bundle schema + user studies + governance + 5-year plan) is a lot for $200k/yr and two part-time PIs. | O1–O3 tasks | Either right-size each objective to Elements (fewer, deeper deliverables) or make the deliberate case for Framework with the added team/community (§2). |
| **"Product development" risk** | Several tasks ("finish separating panels", "complete AWS modules", "consolidate recipes") read as finishing a product rather than CI research. | §research O1/O2 | Reframe each as enabling a *scientific* capability (portable multi-model DA; reproducible cross-model attribution) with the engineering as the means. |
| **Education framing** | Broader Impacts is solid, but ensure education/training is clearly *integrated*, not a co-equal objective — CSSI routes education-first proposals to CyberTraining (§3). | §Broader impacts; O3 Task 3.3 | Keep workshops/tutorials/accessibility as integrated activities; do not elevate to an objective. |
| **Unsupported maturity claims** | Watch for any sentence implying the connector, cloud path, or provenance is production-ready. The JOSS paper is careful here; the proposal should match. | §IM, §research | Cross-check every capability claim against `JOSS_TO_NSF_HANDOFF.md` classes A/B/C. |
| **Talea Mayo role undefined** | `SUBMISSION_READINESS.md` item 4: listed on the ICESEE paper but no confirmed proposal role. | Personnel documents | Do not add to the required Personnel list without a confirmed role and the matching documents; note the §IV participation limit. |

---

## 13. What would make this proposal competitive?

A critical assessment against NSF 22-632, not encouragement.

### Strengths already in hand
- **A working, documented platform** with a JOSS paper — most CSSI Elements
  proposals cannot point to this much running code. The contract-based
  separation (model adapter / execution backend / gateway services) is a
  genuine CI design contribution.
- **Two models already integrated** through one interface, with structured
  results and per-user isolation — concrete evidence the abstraction works.
- **A real security-relevant CI artifact**: the outbound-only connector relay
  with per-user session binding and no stored keys, plus the digest-bound
  human-approval boundary for assistant-guided runs.
- **Test and acceptance infrastructure** that can generate the metrics NSF
  asks for.
- **Strong domain-science pairing**: an RSE-profile PI and a cryosphere-science
  Co-PI, with an active NSF CAREER award producing the scientific method
  (ICESEE) the platform serves.
- **A clean scientific bottleneck available** (§5): multi-model
  observation-constrained ice-sheet state/parameter estimation with quantified
  structural uncertainty.

### Weaknesses before submission
- **No measured adoption.** Zero external users, zero external contributors,
  zero workshops on record. This is the single biggest risk against the
  "community" and "sustainability" criteria.
- **No named external partners or letters.** The proposal currently has no
  documented collaborators beyond the two PIs.
- **Single institution, two part-time PIs, Framework-sized objectives.** The
  scope-to-resource ratio invites a "can they actually do this" review.
- **Bottleneck not yet foregrounded.** The current draft leads with integration
  difficulty, not blocked science.
- **Key end-to-end paths unproven in the wild**: no real PACE run on record
  (institutional-auth gap), no real cloud run, no reproducibility
  demonstration, Icepack exporter unvalidated on real Firedrake.
- **Sustainability deferred to Year 3.**
- **Prior-support section promises rather than reports numbers.**
- **PI-participation limit** could silently disqualify the proposal if either
  PI is listed elsewhere in the CSSI cycle.

### Evidence needed (from §10, in priority order)
1. JOSS paper submitted (citable status).
2. 3–5 real PACE runs with job ids, wall times, result packages, one figure.
3. One reproducibility demonstration (publish a bundle, someone else re-runs).
4. Year-0 adoption baseline (users, non-test runs, institutions, GitHub).
5. 2–3 intent-to-collaborate letters (PISM user, radar data steward, RSE/
   gateways contact; ideally a second institution).
6. One real cloud run + Icepack real-Firedrake validation.
7. PISM use-case specification with a compute estimate.
8. One workshop/tutorial delivered and counted.

### Partnerships / community involvement needed
- A **PISM developer or experienced user** willing to advise and review
  (already in `SUBMISSION_READINESS.md` item 8).
- A **historical-radar data steward** for the second Frozen Legacies dataset.
- A **Science Gateways Community / research-software-engineering** contact for
  external design review.
- **GT PACE and web/security personnel** as documented consultants (not cost
  sharing).
- Ideally a **second institution** with a funded or clearly-committed role —
  this is the lever that makes Framework defensible and materially strengthens
  an Elements proposal.
- 3–5 **external testers** who are not co-authors.

### Technical work worth completing before submission
- Close the PACE institutional-auth gap enough to run real jobs (or document
  precisely why it is an award-time task with a credible plan).
- One qualified real-account AWS run (small, controlled).
- Icepack exporter validation on real Firedrake.
- One reproducibility demonstration end to end.
- License reconciliation.
- Privacy-preserving metric export from the Control Center (produces the
  numbers *and* is a demonstrable O3 capability).

### Work that should deliberately remain proposed work
See §14.

---

## 14. What NOT to build before the proposal

The intellectual and CI-development case for the award depends on there being
**real, hard, unfinished CI research** to fund. Completing the proposed
innovations before submission would hollow out the proposal.

### Build before submission — feasibility demonstration only
- Enough of the **real HPC path** to show 3–5 genuine runs (not a hardened,
  allow-listed protocol — just proof the current connector works on PACE).
- **One** real cloud run (not a qualified, per-user-isolated, budget-controlled
  service).
- **One** reproducibility demonstration (not the full archival provenance
  manifest + run-bundle system).
- **Icepack exporter validation** on one real Firedrake run (not transient /
  1-D / tensor-field support).
- **Metric export** from the Control Center at a basic level (not the full
  policy/audit-search operations console).
- **License reconciliation** and a JOSS submission.

### Build before submission — remove obvious credibility risks
- Fix anything that makes a reviewer doubt the code runs at all: the PACE-auth
  story, the stale connector binaries, the "flowline/L96" figure error
  (`AUDIT_JOSS_CURRENT_STATE.md` §5).
- Have a **written PISM use-case** so O1 Task 1.2 is concrete.
- Have the **Year-0 baseline numbers**.

### Keep as proposed NSF work — do NOT pre-build
- **Versioned public SDK contracts** with semantic versioning, deprecation
  policy, reference fixtures, and template repositories for
  application/model/dataset/observation-bundle extension. (Designing these
  *is* the intellectual contribution.)
- **CryoBench** — the tiered scientific acceptance gate (analytic/restart/
  DA-diagnostic/scaling/SBOM tests as a promotion gate). Ship the offline
  *invariant* acceptance command (done); do not build the *scientific*
  qualification service.
- **PISM integration itself** — the adapter, observation operators, ensemble
  execution, and the synthetic-truth + real-data demonstration.
- **`cryostack.icesee.results`** schema and the DA diagnostics (error/spread/
  innovations/increments/rank histograms) computed and persisted. This needs a
  scientific exporter design; do not greenfield it now.
- **Allow-listed, replay-safe, resource-policy-bound connector protocol** to
  replace the generic shell channel; signed job envelopes; the independent
  security review. Keep relay v2 as the demonstrated baseline.
- **Multi-node MPI cloud primitive** for ICESEE ensembles
  (ParallelCluster / Batch-MNP / EKS-MPI). Name it as a bounded investigation.
- **Per-user S3 isolation + tightened IAM + job-definition allow-list +
  budget/quota/cleanup/cost-attribution** for the cloud path.
- **Archival provenance manifest** + citation-ready exportable run bundle with
  DOIs.
- **Observation-bundle schema** and the connected Frozen-Legacies/LIVIST →
  model demonstration.
- **Transactional shared database** + durable task/session store + versioned
  migrations.
- **Second historical-radar dataset adapter** and the browser-executable,
  provenance-captured radar-processing task.
- **Governance framework** (contribution guide, code of conduct, maintainer
  rotation, adapter proposal template) beyond a minimal placeholder — the
  *process* of building it with the community is part of O3.
- **User-centered evaluation** (formative + summative studies, SUS, WCAG audit)
  and the **workshop series**.
- **Agent live-submission wiring** and any agent cloud backend — keep the
  approval boundary as demonstrated prior work; the safe live-execution
  architecture is proposed research.
- **Five-year sustainability / operations plan** and maintainer handoff.

**Rule of thumb:** build what proves *the idea is feasible*; propose what
proves *the idea is hard, valuable, and not yet solved*. The JOSS paper is the
feasibility proof; the CSSI proposal is the case that a community-grade,
qualified, sustainable version is a real cyberinfrastructure research and
development undertaking.

---

## 15. Sequence (unchanged from the directive)

```
CryoStack implementation (done / ongoing)
  → JOSS submission / publication  (paper is ready; submit early)
  → measurable early adoption / evidence  (§10 — collect Sept–Nov 2026)
  → CSSI proposal citing CryoStack  (December 1, 2026 deadline)
  → NSF project advances CryoStack from the demonstrated foundation into
    broader sustainable community cyberinfrastructure
```

**Do not revise `nsf-csi-proposal/` yet.** The JOSS paper comes first; this
document is the input for the later proposal pass.

---

## 16. Consolidated OWNER_CHECKPOINTs

1. **Award class** — Elements vs. Framework; recommendation is Elements now,
   Framework/Transition later, but the PI/Co-PI decide and record rationale
   (§2).
2. **Per-award budget cap / duration** — verify against the exact solicitation
   revision governing December 1, 2026 (§1).
3. **The scientific bottleneck** — Co-PI as science lead selects and sharpens
   one compelling geoscience question (§5).
4. **Every metric target** — re-derive from a measured Year-0 baseline; do not
   ship round numbers (§9).
5. **PI-participation check** — confirm neither PI is on any other CSSI proposal
   this cycle (§3, §11).
6. **CI Professional plan** — include only if CI-professional effort is charged;
   ask the research office (§11).
7. **Second institution / named partners** — decide early; it changes the award
   class case and the strength of the proposal (§10, §13).
8. **Directorate alignment** — verify CISE/OAC + GEO/OPP + GEO/EAR against the
   22-632 directorate table and contact the cognizant POs (§6).
9. **Results from Prior NSF Support** — replace promised counts with measured
   numbers (§12).
10. **License reconciliation** — resolve before submission if possible (§12).
11. **Which technical items to complete pre-submission** vs. keep as proposed
    work (§14).

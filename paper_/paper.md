---
title: 'CryoStack: A modular cyberinfrastructure stack for cryosphere data, models, data assimilation, and heterogeneous computing'
tags:
  - Python
  - cryosphere
  - scientific gateways
  - ice-sheet modeling
  - data assimilation
  - radar data
  - reproducible workflows
  - high-performance computing
  - cloud computing
authors:
  - name: Brian Kyanjo
    orcid: 0000-0002-0995-1051
    affiliation: "1"
    corresponding: true
  - name: Alexander A. Robel
    orcid: 0000-0003-4520-0105
    affiliation: "1"
  - name: Angelo Tarzona Suyosa
    orcid: 0000-0002-3464-7537
    affiliation: "1"
affiliations:
  - name: School of Earth and Atmospheric Sciences, Georgia Institute of Technology, Atlanta, Georgia, USA
    index: 1
date: 19 October 2026
bibliography: paper.bib
---

# Summary

Cryosphere research increasingly combines numerical ice-sheet models,
observations, data assimilation, interactive analysis, and computing systems
that range from laptops to institutional clusters and commercial cloud
services. CryoStack is an open-source platform that brings these components
behind a common web entry point while preserving the specialized interfaces of
each scientific application. Its current applications are CryoLauncher for
ice-sheet model configuration and execution, ICESEE for ensemble data
assimilation [@kyanjo2026icesee], Frozen Legacies for historical radar data,
and LIVIST (Living Ice Sheet Temperature) for englacial-temperature products.
The deployed platform is available at <https://cryostack.eas.gatech.edu/>, and
the source is maintained at <https://github.com/ICESEE-project/CryoStack>.

# Statement of need

A cryosphere workflow may require a researcher to install compiled model
dependencies, translate data, prepare scheduler scripts, transfer inputs,
track jobs, retrieve outputs, and record the configuration that produced a
result. These tasks are often repeated when the model, dataset, institution,
or computing system changes. The burden is especially high for students and
groups without dedicated research-software or high-performance-computing
support.

CryoStack serves researchers moving between exploratory and production
workflows, collaborators who do not share a computing environment, radar
scientists preserving difficult legacy observations, and instructors seeking
a consistent entry point for computational examples. It separates scientific
configuration from execution and records user workspaces, saved
configurations, experiments, job identifiers, output locations, and status
events. This makes transitions among applications, data, and computing
resources explicit and inspectable without claiming that every application
uses the same execution or result pipeline.

# State of the field

Mature packages already provide the scientific capabilities that CryoStack
exposes. ISSM supports continental-scale ice-sheet modeling and inversion
[@larour2012issm], Icepack provides composable glacier-flow modeling in Python
[@shapero2021icepack], and ICESEE provides ensemble state and parameter
estimation [@kyanjo2026icesee]. General-purpose platforms such as HUBzero
provide infrastructure for online scientific collaboration
[@mclennan2010hubzero], while JupyterHub provides multi-user computational
workspaces.

CryoStack does not reimplement those models, assimilation algorithms, or
general gateway services. Its contribution is the cryosphere-specific
integration layer: capability-aware model configuration, heterogeneous
execution, experiment persistence, neutral result packages, and
manifest-driven observational applications in one deployable stack. Extending
an individual model or a generic notebook platform would not address the need
to coordinate model, data-assimilation, radar, licensing, scheduler, and
cloud constraints while allowing each scientific application to evolve
independently.

# Software design

CryoStack separates four concerns: access and operational services,
scientific applications, execution backends, and reproducible software
environments (Figure 1). Identity and experiment records live outside the
applications. Per-user workspace roots and containment checks prevent file
operations from escaping an owner's workspace, and canonical examples are
copied before modification. Deployable applications and their dependencies,
routes, health checks, and restart scopes are declared in a registry rather
than embedded in a single service.

![CryoStack's layered architecture. Four scientific applications reuse shared
services and contracts, while execution support remains workflow-specific.](cryostack_architecture.png)

A model capability registry records supported configuration fields, execution
modes, licensing requirements, and result support. This design rejects invalid
combinations before submission and makes differences between models explicit.
CryoLauncher currently configures ISSM and Icepack. ICESEE retains its own
submission and assimilation-diagnostic pipeline for ISSM, Icepack, Lorenz-96,
and a one-dimensional flowline model. Frozen Legacies uses dataset manifests
and ingestion adapters to build a geolocated catalog of historical Antarctic
radar observations and derived products. LIVIST retains a specialized
interface for radar- and borehole-constrained temperature products.

Remote execution supports direct SSH when the application host can reach an
institutional resource and a Connector/Relay mode when access is possible only
from a user's workstation, virtual private network, or approved edge system
(Figure 2). CryoLauncher and ICESEE each implement scheduler-aware submission,
status, logging, termination, and retrieval while sharing the connectivity
layer. The relay binds a session to an authenticated user and uses pairing and
per-session secrets; institutional accounts, multifactor authentication,
scheduler policy, and allocations remain under institutional control. The same
Connector/Relay can let a cloud workload reach a private service, as
demonstrated by an ISSM job using an institutional MATLAB license.

![CryoStack applications and shared connectivity. CryoLauncher and ICESEE use
their own Remote and Cloud execution paths and can reach institutional
resources directly or through Connector/Relay.](cryostack_hpc_bridge.png)

Cloud drivers expose provider-independent contracts, with AWS Batch as the
implemented provider. CryoLauncher Icepack workflows have completed
single-node CPU runs on Fargate and EC2 On-Demand. ISSM workflows have also
completed end-to-end runs on both modes, including MPI-parallel solution,
post-processing, retrieval, and visualization. ICESEE's Lorenz-96 example has
completed Fargate execution under its single-process contract. These results
qualify specific workflows, not EC2 Spot, GPU, multi-node, or arbitrary
networking configurations. Spack [@gamblin2015spack] supports source-based
environments, while Docker and Apptainer [@kurtzer2017singularity] provide
preconfigured execution environments.

Completed CryoLauncher runs produce a versioned, transport-neutral result
package containing metadata, mesh geometry, field arrays, and available
figures. Model-independent readers load these packages without MATLAB or
Firedrake, and a shared visualization layer renders fields and time series.
Experiment records provide useful operational provenance, but are not yet a
complete archival record of input checksums, environment digests,
transformations, and outputs.

The repository includes automated tests for identity, workspace isolation,
model adapters, Connector/Relay, cloud modules, deployment, and
application-specific paths. Continuous integration runs the offline portions,
and a separate acceptance command checks safety and consistency invariants
without institutional or cloud credentials. Live PACE, AWS, and MATLAB paths
require documented manual qualification.

# Research impact statement

CryoStack is deployed and has been used by the authors to integrate and
execute research workflows spanning ice-sheet modeling, ICESEE data
assimilation [@kyanjo2026icesee], historical radar-data curation, and
radar/borehole temperature exploration. Its verified workflows include
remote-cluster execution and end-to-end AWS runs with result retrieval and
visualization. The public repository provides examples, documentation,
automated tests, contribution guidance, tagged releases, and more than six
months of distributed development history. These materials make the platform
testable and extensible while clearly identifying the workflows that still
require live infrastructure. External adoption and quantitative reductions in
researcher effort have not yet been established.

# AI usage disclosure

OpenAI Codex (GPT-5) assisted with code refactoring, test scaffolding,
repository audits, documentation, and manuscript copy-editing. The authors
made the scientific and architectural decisions and reviewed, edited, and
tested AI-assisted outputs. No scientific results in this paper were generated
by AI.

# Acknowledgements

This work was supported in part by the U.S. National Science Foundation
through CAREER Award No. 2235920. We gratefully acknowledge the Astera
Institute for funding the backend infrastructure for the LIVIST project. The
authors also thank Renette Jones-Ivey of the University at Buffalo for her
assistance with the initial Jupyter Book backend; Justin Quinn for helping
launch the CryoStack-GHUB backends before their migration to a Georgia Tech
virtual machine; Troy Hilley of Research Computing Services; and the
Partnership for an Advanced Computing Environment (PACE) for providing
computational resources. We further thank Research Scientist Fang (Cherry) Liu
for her assistance in resolving challenges related to user authentication and
remote access to PACE.

# References

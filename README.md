# CryoStack

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**CryoStack** connects cryosphere applications, per-user workspaces, experiment
records, and supported local, institutional HPC, and AWS Batch execution paths.
Backend availability and validation are specific to each workflow.

## Applications

- **CryoLauncher** — configures and runs ice-sheet models (currently ISSM
  and Icepack), with a curated parameter subset, run tracking, and
  model-free result viewing.
- **ICESEE** — ensemble-based state and parameter estimation for ice-sheet
  models, using the same identity, workspace, and connector infrastructure
  as CryoLauncher.
- **LIVIST** (Living Ice Sheet Temperature) — exploration of Antarctic
  englacial-temperature products inferred from radar and constrained by
  boreholes.
- **Frozen Legacies** — a manifest-driven catalog for discovering and
  working with historical Antarctic radar observations and derived
  products.

Applications reuse shared CryoStack infrastructure rather than each
maintaining their own: per-user identity and workspaces, experiment
records, and the Connector/Relay for reaching institutional or other
private resources (from Remote HPC access, and, when a Cloud workflow
needs it, private connectivity such as an institutional MATLAB
license), plus a shared AWS account/onboarding layer for Cloud.
CryoLauncher and ICESEE each implement their own submission, execution,
and result-handling today rather than through one common execution or
result contract. This infrastructure is not itself an application.
Administrative/operations tooling (Control Center) is separate from the
scientific applications above.

## Documentation

Full documentation is built as a Jupyter Book from `icesee_jupyter_book/`
and deployed at <https://cryostack.eas.gatech.edu/>. Start with:

- **Interactive Jupyter Book** format with comprehensive documentation
- **Runnable tutorials** including the Lorenz-96 data assimilation demo
- **Cloud-ready deployment** through CryoStack infrastructure
- **Ensemble data assimilation** workflows (EnKF-style methods)
- **Modular design** for coupling with ice-sheet models (ISSM, Icepack, flowline solvers)
- **No HPC required** for lightweight examples

This README is intentionally short; it does not duplicate that
documentation.

## Local installation

```bash
git clone https://github.com/ICESEE-project/CryoStack.git
cd CryoStack
conda env create -f tools/icesee1_environment.yml -n cryostack-dev
conda activate cryostack-dev
```

Use the repository's Python 3.11 environment for development. The narrower book
and Connector dependency lists do not include every test dependency. Starting
the gateway and services is documented in the
[Developer Guide](icesee_jupyter_book/docs/developer_guide.md).
For a first scientific experiment, follow the ICESEE getting-started guide below.

## Exercising representative functionality without live infrastructure

An offline, read-only acceptance check exercises core invariants (agent
safety properties, capability-registry and result-contract consistency,
cloud restrictions and absence of static credentials, per-user workspace
isolation) without requiring HPC, cloud, or institutional credentials. Run `python -m cryostack_src.acceptance --offline`. See the
[Developer Guide](icesee_jupyter_book/docs/developer_guide.md) for qualification
limits.

Useful workflow guides:

- **[Quickstart Guide](icesee_jupyter_book/applications/icesee/getting_started.md)** — Fastest way to get started
- **[User Manual](icesee_jupyter_book/applications/icesee/user_manual.md)** — Practical usage notes
- **[ICESEE Workflow](icesee_jupyter_book/applications/icesee/user_manual.md)** — Conceptual overview of the DA cycle
- **[Tutorial Notebooks](icesee_jupyter_book/icesee_jupyter_notebooks/)** — Interactive examples including:
  - Lorenz-96 data assimilation demo (runnable in CryoStack)
  - Flowline model coupling
  - ISSM and Icepack integration examples
- **[HPC Coupling Guide](icesee_jupyter_book/docs/hpc_cloud.md)** — Advanced deployment patterns
- **[Container Usage](icesee_jupyter_book/docs/developer_guide.md)** — Docker/Singularity workflows

For upstream ICESEE documentation: [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki)

##  Project Structure

```
CryoStack/
├── cryostack_src/           # Shared platform: identity, workspaces,
│                            # execution/result contracts, cloud drivers
├── icesee_hpc_connector/    # Connector/Relay: shared Remote/Cloud
│                            # connectivity infrastructure
├── icesee_jupyter_book/     # Applications, docs, and the Jupyter Book UI
│   ├── applications/        # Per-application pages (CryoLauncher, ICESEE, ...)
│   ├── docs/                # Developer/Cloud/HPC guides
│   └── ui/                  # Gateways for each application
├── control_center/          # Administrative/operations tooling (not a
│                            # principal scientific application)
├── external/                # ICESEE, Frozen Legacies, LIVIST (subtrees)
├── deployment/              # CloudFormation and deployment scripts
├── bin/                     # Launcher scripts
├── LICENSE                  # MIT License
└── README.md                # This file
```
## Architecture and configuration

See the [current manuscript](paper_/paper.md) for the architecture and qualified
execution paths. **Auto-config · Beta** in CryoLauncher and ICESEE prepares
configuration changes from natural-language requests. It offers a compact change
preview, retention of valid current settings, bounded diagnosis and repairs,
stateless refinement, and read-only explanations. Apply updates manual controls;
the existing review, validation, and execution controls remain authoritative.
It does not submit workflows. See the [Auto-config guide](icesee_jupyter_book/docs/building_agents.md).

AWS Batch Fargate is implemented and tested; EC2 is an opt-in alternative. The
tested Icepack workflows have scientific validation on Fargate and EC2
On-Demand (single-node CPU). CryoLauncher's ISSM workflow has completed
end-to-end execution on both Fargate and EC2 On-Demand — MPI-parallel solver
execution, postprocessing, retrieval, and visualization — reaching the
configured Georgia Tech institutional MATLAB license through the same
Connector/Relay infrastructure used for Remote access; this validates one
institutional Cloud/Connector configuration, not arbitrary institutional
license-server arrangements, and ICESEE's own Cloud execution has not been
separately validated for ISSM-based workflows. EC2 Spot, GPU, and multi-node
remain unvalidated. See [HPC and Cloud](icesee_jupyter_book/docs/hpc_cloud.md)
for restrictions.

## Running the test suite

```bash
python -m pytest cryostack_src icesee_jupyter_book icesee_hpc_connector deployment
```

See the
CI workflow (`.github/workflows/tests.yml`) for what runs automatically on
push and pull request, and what is excluded because it needs live AWS,
PACE, or MATLAB access.

## Paper

A JOSS submission describing CryoStack's architecture and scope is at
[`paper_/paper.md`](paper_/paper.md).

## Citing CryoStack

A citable release (Zenodo DOI and `CITATION.cff`) has not yet been issued.
Until then, cite the JOSS paper above once published, or reference the
repository URL and the commit/tag used.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

**Copyright (c) 2026 ICESEE, Brian Kyanjo, Alexander Robel**

##  Citation

If you use ICESEE in your research, please cite:

```bibtex
@software{icesee2026,
  author = {Kyanjo, Brian and Robel, Alexander},
  title = {ICESEE: Ice Sheet State and Parameter Estimator},
  year = {2026},
  url = {https://github.com/ICESEE-project/ICESEE}
}
```

##  Support

- **Issues**: [GitHub Issues](https://github.com/ICESEE-project/CryoStack/issues)
- **Documentation**: [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki)
- **CryoStack Support**: bkyanjo3@gatech.edu

## Contributing and support

CryoStack grew from deployment tooling for the ICESEE framework into a
wider platform for the computational cryosphere; ICESEE remains one of its
applications, alongside CryoLauncher, Frozen Legacies, and LIVIST.

## Acknowledgements

This work was supported in part by U.S. National Science Foundation CAREER
award 2235920.

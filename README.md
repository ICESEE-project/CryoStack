# CryoLauncher

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**CryoLauncher** is an interactive **Jupyter Book** environment that brings the ICESEE (Ice-sheet Coupled Ensemble Simulator and Estimator) framework to the cloud through CryoStack. This tool enables users to explore ensemble data assimilation workflows, run lightweight examples, and understand the ICESEE framework without requiring a full HPC setup.

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

- **Modular structure** — Reuse the same DA logic across different models
- **Model coupling** — Integrate external codes/workflows while keeping the assimilation engine consistent  
- **Scalability** — Execute on HPC and cloud-style environments, including CryoStack

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
- For local development:
  - Python 3.8+
  - Anaconda or Miniconda
  - Jupyter Book

##  Quick Start

### On CryoLauncher

1. Navigate to the Run Center
2. Launch the tool
3. The Jupyter Book will open automatically
4. Start with the **Lorenz-96 tutorial** for a complete end-to-end example

### Local Installation

```bash
# Clone the repository
git clone  https://github.com/ICESEE-project/CryoStack.git
cd CryoStack

# Get dependencies and the kernal installed and activated
./tools/go.icesee1 && source ./tools/create_icesee1_environment_yml.sh
```

`tools/icesee1_environment.yml` is the environment this repository's own
CI and test suite are validated against (Python 3.11). Two narrower
`pip`-installable dependency lists also exist —
`icesee_jupyter_book/requirements.txt` and
`icesee_hpc_connector/requirements.txt` — but they do not by themselves
cover everything the test suite needs (for example `pytest` and `aiohttp`),
so the conda environment above is the supported path for development.
Starting the full gateway/service stack (Nginx, `aiohttp`, Voilà, the
connector relay) is documented in the Developer Guide above — it is a
multi-process deployment, not a single script, and the commands there are
authoritative over anything summarized here.

## Exercising representative functionality without live infrastructure

An offline, read-only acceptance check exercises core invariants (agent
safety properties, capability-registry and result-contract consistency,
cloud restrictions and absence of static credentials, per-user workspace
isolation) without requiring HPC, cloud, or institutional credentials:

- **[Quickstart Guide](icesee_jupyter_book/quickstart.md)** — Fastest way to get started
- **[User Manual](icesee_jupyter_book/user_manual.md)** — Practical usage notes
- **[ICESEE Workflow](icesee_jupyter_book/icesee_workflow.md)** — Conceptual overview of the DA cycle
- **[Tutorial Notebooks](icesee_jupyter_book/icesee_jupyter_notebooks/)** — Interactive examples including:
  - Lorenz-96 data assimilation demo (runnable in CryoStack)
  - Flowline model coupling
  - ISSM and Icepack integration examples
- **[HPC Coupling Guide](icesee_jupyter_book/icesee_hpc_coupling.md)** — Advanced deployment patterns
- **[Container Usage](icesee_jupyter_book/running_with_containers.md)** — Docker/Singularity workflows

For upstream ICESEE documentation: [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki)

##  Project Structure

```
CryoLauncher/
├── icesee_jupyter_book/     # Jupyter Book source files
│   ├── icesee_jupyter_notebooks/  # Tutorial notebooks
│   ├── _config.yml          # Book configuration
│   ├── _toc.yml            # Table of contents
│   └── *.md                # Documentation pages
├── external/
│   └── ICESEE/             # ICESEE core (git subtree)
├── bin/                    # Scripts for launching the book
├── middleware/             # CryoStack integration scripts
├── src/                    # Build system
│   ├── Makefile           # Build commands
│   └── readme.txt         # Build instructions
├── LICENSE                 # MIT License
└── README.md              # This file
```
## Simplified architectural diagram
```text
                    ┌────────────────────────────┐
                    │          Users             │
                    │  Browser / Web Interface   │
                    └─────────────┬──────────────┘
                                  │ HTTPS
                                  ▼
        ┌────────────────────────────────────────────────┐
        │        GT-hosted ICESEE Web Server             │
        │                                                │
        │  ┌──────────────────────────────────────────┐  │
        │  │ Jupyter Book Frontend                    │  │
        │  │ Documentation + workflow entry point     │  │
        │  └──────────────────────────────────────────┘  │
        │                                                │
        │  ┌──────────────────────────────────────────┐  │
        │  │ Voilà GUI Apps                           │  │
        │  │ ICESEE DA GUI + Ice-sheet Modeling GUI   │  │
        │  └──────────────────────────────────────────┘  │
        │                                                │
        │  ┌──────────────────────────────────────────┐  │
        │  │ Backend Orchestration Layer              │  │
        │  │ SSH, SLURM submission, monitoring, logs  │  │
        │  └──────────────────────────────────────────┘  │
        └─────────────┬──────────────────────┬───────────┘
                      │                      │
          SSH / SLURM │                      │ Cloud API / SSH
                      ▼                      ▼
        ┌──────────────────────┐      ┌──────────────────────┐
        │   HPC Resources      │      │   Cloud Resources    │
        │                      │      │                      │
        │  PACE                │      │  AWS / other cloud   │
        │  UBuffalo cluster    │      │  compute services    │
        │  User-owned clusters │      │                      │
        └──────────┬───────────┘      └──────────┬───────────┘
                   │                             │
                   ▼                             ▼
        ┌────────────────────────────────────────────────┐
        │              Simulation Outputs                │
        │  Logs, plots, result files, lightweight views  │
        └────────────────────────────────────────────────┘
```

## Running the test suite

```bash
python -m pytest cryostack_src icesee_jupyter_book icesee_hpc_connector deployment
```

At the current revision this suite passes more than 1,800 tests; see the
CI workflow (`.github/workflows/tests.yml`) for what runs automatically on
push and pull request, and what is excluded because it needs live AWS,
PACE, or MATLAB access.

## Paper

A JOSS submission describing CryoStack's architecture and scope is at
[`paper/paper.md`](paper/paper.md).

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
  title = {ICESEE: Ice-sheet Coupled Ensemble Simulator and Estimator},
  year = {2026},
  url = {https://github.com/ICESEE-project/ICESEE}
}
```

##  Support

- **Issues**: [GitHub Issues](https://github.com/ICESEE-project/CryoStack/issues)
- **Documentation**: [ICESEE Wiki](https://github.com/ICESEE-project/ICESEE/wiki)
- **CryoStack Support**: bkyanjo3@gatech.edu

## Contributing and support

This work builds upon the ICESEE framework and leverages CryoStack infrastructure for cloud-based scientific computing.

## Acknowledgements

This work was supported in part by U.S. National Science Foundation CAREER
award 2235920.

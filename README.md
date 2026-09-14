# CryoStack

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

CryoStack is an open-source cyberinfrastructure stack for assembling
reproducible cryosphere workflows from scientific applications, user
workspaces, data catalogs, experiment records, and heterogeneous execution
resources (local, institutional HPC, and cloud). It connects ice-sheet
modeling, ensemble data assimilation, and the discovery and reuse of
historical Antarctic radar observations behind one shared platform, rather
than as separate tools with independent installation and execution paths.

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

Not every application uses every execution backend; see `paper/paper.md`
and `icesee_jupyter_book/docs/` for the current scope of each.

## Documentation

Full documentation is built as a Jupyter Book from `icesee_jupyter_book/`
and deployed at <https://cryostack.eas.gatech.edu/>. Start with:

- `icesee_jupyter_book/docs/developer_guide.md` — architecture, build,
  test, and extension workflow.
- `icesee_jupyter_book/docs/hpc_cloud.md` — remote HPC and cloud execution.
- `icesee_jupyter_book/applications/` — per-application user manuals and
  getting-started guides.

This README is intentionally short; it does not duplicate that
documentation.

## Local installation

```bash
git clone https://github.com/ICESEE-project/CryoStack.git
cd CryoStack
conda env create -f tools/icesee1_environment.yml -n cryostack-dev
conda activate cryostack-dev
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

```bash
python -m cryostack_src.acceptance --offline
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

CryoStack is distributed under the [MIT License](LICENSE). Some source
files carry other license identifiers and integrated applications/submodules
retain their own licenses; see `paper/paper.md` ("Software design") for the
current, disclosed state of this inconsistency, which has not yet been
resolved.

## Contributing and support

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development, testing, and
documentation workflow, and the [issue templates](.github/ISSUE_TEMPLATE/)
for filing bugs or requests. There is no separate support channel; use
GitHub Issues.

## Acknowledgements

This work was supported in part by U.S. National Science Foundation CAREER
award 2235920.

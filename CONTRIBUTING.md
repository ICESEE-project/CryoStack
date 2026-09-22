# Contributing to CryoStack

CryoStack is currently maintained by a small team. This document describes
the actual development workflow used in this repository; it does not assume
an existing active external contributor community.

## Development setup

```bash
git clone https://github.com/ICESEE-project/CryoStack.git
cd CryoStack
conda env create -f tools/icesee1_environment.yml -n cryostack-dev
conda activate cryostack-dev
```

This is the same environment `.github/workflows/tests.yml` uses. The
narrower `icesee_jupyter_book/requirements.txt` and
`icesee_hpc_connector/requirements.txt` files cover only part of what the
test suite needs and are not a substitute for it.

## Running tests

```bash
python -m pytest cryostack_src icesee_jupyter_book icesee_hpc_connector deployment
```

Tests that require live AWS, PACE, or MATLAB access are excluded from the
default run; see `.github/workflows/tests.yml` for what CI executes
automatically and what it skips, and why.

A separate offline, read-only acceptance check is available for verifying
core platform invariants without any live infrastructure:

```bash
python -m cryostack_src.acceptance --offline
```

## Documentation

Documentation lives under `icesee_jupyter_book/` and builds as a Jupyter
Book. If a change affects behavior described in
`icesee_jupyter_book/docs/` or `icesee_jupyter_book/applications/`, update
the corresponding page in the same change.

## Submitting a change

1. Open an issue first for anything beyond a small fix, so the change can be
   discussed before significant work is done.
2. Fork the repository and create a branch for your change.
3. Keep the change scoped: unrelated formatting or refactors in the same
   pull request make review slower.
4. Add or update tests for any behavior change.
5. Open a pull request against `main` describing what changed and why, and
   reference the related issue.

## Code style

Follow the conventions already present in the file you are editing. There is
currently no separate style guide or linter configuration; consistency with
surrounding code is the standard.

## Reporting bugs and requesting features

Use the [issue templates](.github/ISSUE_TEMPLATE/) in this repository.
Include steps to reproduce, what you expected, and what actually happened.

## Code of conduct

Participation in this project is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

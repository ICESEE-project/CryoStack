# Vendored `websockets` 16.0 (pure Python, client subset)

Why this exists: `cryostack_src/cloud/license_tunnel_client.py` runs
standalone inside the AWS Batch scientific container
(`bkyanjo/icesee-combined`), which does not have `websockets` installed and
must never require a rebuild of that image or a runtime `pip install`. This
directory is staged alongside the tunnel client (see
`cryostack_src.cloud.runtime.license_tunnel_client_extra_files`) as
`WORKDIR/.cryostack_runtime/websockets/` so the client can import a pinned,
deterministic copy regardless of what (if anything) is on the container's
own Python path.

- **Source**: PyPI `websockets` 16.0, unmodified, copied verbatim from an
  installed distribution (`pip show websockets` → `License-Expression:
  BSD-3-Clause`). `LICENSE` in this directory is the upstream license file,
  copied as-is -- required for redistribution, never edited.
- **Scope**: only the modules empirically required for the client-side
  connect/send/recv/close path `license_tunnel_client.py` actually
  exercises (verified by tracing `sys.modules` through a real
  relay + Connector + loopback-echo round trip -- see
  `cryostack_src/cloud/tests/test_license_tunnel_client_bundle.py`).
  Server (`asyncio/server.py`, `asyncio/router.py`), sync (`sync/*`),
  legacy (`legacy/*`), CLI (`cli.py`), and auth (`auth.py`) modules are
  deliberately excluded -- never imported by this client-only usage.
- **No C extension**: `speedups.*` (the optional native `apply_mask`
  accelerator) is intentionally NOT vendored. `frames.py` already falls
  back to the pure-Python `utils.apply_mask` on `ImportError`
  (`try: from .speedups import apply_mask / except ImportError: from
  .utils import apply_mask`) -- exactly the path this omission takes, and
  the only reason a compiled, Python-ABI-specific `.so` is safe to leave
  out for a container running a different Python version than this repo's
  own development environment.
- **Pinning**: this checked-in copy IS the pinned version -- staged
  verbatim from the repo, never re-derived from whatever `websockets`
  happens to be installed on the deploying machine at runtime.
- **Updating**: bump by re-copying the same module list from a newer
  `websockets` release's source tree and re-running the import-closure
  trace to confirm no new internal dependency appeared; update this file's
  version number and the directory name together.

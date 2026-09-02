# Maintainer / Operations Guide

**Restricted.** This guide is for people **operating a CryoStack deployment**.
It is served only to authenticated accounts holding a `developer`,
`maintainer`, `admin`, or `owner` role (enforced at the request boundary in
`bin/icesee_app.py`, the same `require_roles` mechanism that gates the Control
Center). It is deliberately **excluded from the public book build**
(`_toc.yml`).

Placeholders used throughout — substitute your deployment's values, never
commit real ones:

| Placeholder | Meaning |
|---|---|
| `<release-host>` | SSH target of the release/deploy host |
| `<release-user>` | account that owns the canonical store on the release host |
| `<web-root>` | nginx document root for the site (e.g. the path in `icesee.conf`) |
| `<public-base>` | public HTTPS base URL of the deployment |
| `<resource-id>` | a compute-resource identifier |

Never place a password, access key, connector control/session secret, relay
deployment token, private SSH key, real allocation identifier, personal email
address, or production credential in this file. The commands below stay
reproducible with placeholders and environment variables.

---

## Publishing production connector binaries

Releasing the connector has **three deliberately separate stages** so a build
produced on one machine can never disturb an artifact built on another.

```text
   native builder                         release host
 ┌───────────────┐   register    ┌──────────────────────────┐   release   ┌──────────────────────────┐
 │ dist/packages/│ ────────────► │ canonical artifact store │ ──────────► │ <web-root>/downloads/    │
 │  <artifact>   │               │  <store>/<platform>/     │  candidate  │  connectors/  (served)   │
 │  <..build.json│               │  source of truth         │  + promote  │  deployment target only  │
 └───────────────┘               └──────────────────────────┘             └──────────────────────────┘
```

* **Native build output** — `dist/packages/` on the machine that can build
  that platform. Transient; never published directly.
* **Canonical artifact store** — `<store>/<platform>/`, a persistent
  directory **outside the web root** on the release host, one subdirectory
  per platform. The source of truth for what is publicly available.
* **Served release** — `<web-root>/downloads/connectors/`. A deployment
  target only. Regenerated wholesale from the store on every release.

Build the artifact first (see the public Developer Guide → *Connector
development*), then:

### 1. Register into the canonical store

**Same machine builds and serves** (the common single-host case):

```bash
bash publish_connector_artifact.sh
```

**Separate builder** (e.g. releasing the macOS build from a Mac to the Linux
release host):

```bash
export CRYOSTACK_RELEASE_HOST=<release-host>      # ssh target
export CRYOSTACK_RELEASE_USER=<release-user>      # optional ssh user
bash publish_connector_artifact.sh
```

The store path is resolved **on the release host**, from `<release-user>`'s
home (`~/.cryostack/connector-artifacts`). The builder's home is never used
remotely — a Mac's `/Users/<name>/…` cannot leak onto a Linux release host.

`CRYOSTACK_RELEASE_STORE` is an **optional override**, not normally required:

```bash
export CRYOSTACK_RELEASE_STORE=<remote-store-path>   # only for a non-default store location
```

Registering one platform never touches another: registering macOS preserves
the Linux artifact; registering Windows later preserves both. Registration
re-verifies `sha256` / `size_bytes` against the sidecar and **refuses** an
artifact whose `pairing_protocol` does not match this release line
(`--allow-protocol-mismatch` to override deliberately).

### 2. Inspect the canonical store

On the release host:

```bash
python3 deployment/connector_store.py list
```

```text
[store] /home/<release-user>/.cryostack/connector-artifacts
[store]   linux-x86_64   CryoStack-Connector-linux-x86_64.tar.gz   <size>  v2  <revision>
[store]   macos-arm64    CryoStack-Connector-macos-arm64.dmg       <size>  v2  <revision>
```

### 3. Release

Run **as the release owner, without sudo**:

```bash
bash release_connector.sh
```

`release_connector.sh` manages the privilege boundary itself:

1. it resolves the canonical store from the **release owner's** home — never
   `/root`, even if the whole script is invoked under `sudo`;
2. it inspects the store, builds a **candidate** web tree and fully verifies
   it (manifest, `SHA256SUMS`, permissions) — all **unprivileged**;
3. only the final **atomic promotion** into the (root-owned)
   `<web-root>/downloads/connectors/`, and the nginx reload, run through
   `sudo` — which may trigger the site's sudo / MFA prompt the first time.
   That is expected.

If candidate verification fails, the currently served release is left
**byte-for-byte unchanged**; a failed directory swap rolls the previous live
release back. Re-running with the same store re-publishes the same release
(idempotent). After promotion the script enforces `0755` directories /
`0644` files and re-verifies the **live** tree before reporting success.

Dry run:

```bash
bash release_connector.sh --print-config
```

> `sudo bash release_connector.sh` is also supported (the release owner and
> the canonical store still resolve to the **invoking** user via `SUDO_USER`,
> not to `root`), but it is not the normal workflow.

`build_deploy_connector.sh` chains all three stages for the single-host case
(`CRYOSTACK_SKIP_BUILD=1` to skip the build and register/release an existing
`dist/packages/` artifact).

### 4. Remove a platform

A platform is **only** removed on request:

```bash
python3 deployment/connector_store.py unpublish <platform>
bash release_connector.sh
```

Publishing or releasing from one builder must never remove artifacts built on
another platform. `unpublish` is the intentional removal mechanism.

---

## Production web deployment

`deployment/deploy_web_nginx/deploy_web.sh` rsyncs the built book and static
web assets into `<web-root>` and then **re-hardens** the tree: `rsync -a`
preserves the repository's `0770/0660` modes, which the nginx worker cannot
read, so `deploy_web.sh` resets `0755` directories / `0644` files (excluding
`downloads/connectors/`, owned by the release flow) and runs `restorecon`
when SELinux is active. It hard-gates on `nginx -t` and runs an HTTP smoke
check of the setup page after reload.

### Verify a release

A connector release is only operational when **both** the setup page and the
downloads respond:

```bash
curl -sSIL <public-base>/connect/
curl -sSL  <public-base>/downloads/connectors/manifest.json
```

`/connect/` must return `200` (not `403`). A `403` there is almost always DAC
permissions — the tree was not re-hardened after an `rsync -a`. Diagnose:

```bash
sudo namei -l <web-root>/connect/index.html
sudo tail -n 50 /var/log/nginx/error.log
getenforce; ls -Zd <web-root>/connect
```

Then the download checks:

```bash
curl -sSL  <public-base>/downloads/connectors/SHA256SUMS
curl -sSIL <public-base>/downloads/connectors/<artifact> \
  | grep -Ei 'HTTP/|content-(type|length|disposition)'
```

A healthy artifact response is `200`, `Content-Type: application/octet-stream`,
`Content-Disposition: attachment`, and a `Content-Length` matching
`size_bytes` in the manifest. **Always check the live `manifest.json` before
assuming a release succeeded** — it lists exactly the platforms currently
published and their `pairing_protocol`.

`deploy_web.sh` runs the `/connect/` smoke check itself after every deploy
(override the base with `CRYOSTACK_PUBLIC_BASE`, skip with
`CRYOSTACK_SKIP_SMOKE=1`).

### Audit nginx

```bash
sudo bash deployment/nginx_audit.sh
```

A healthy result: exactly one `server` block owns the site `server_name` on
each listen address, exactly one `map $connection_upgrade`, and
`OK: no server_name appears in more than one block`. A duplicate means a
stale conf file is still loaded — `deploy_web.sh` disables known prior
CryoStack blocks, but Certbot-managed or hand-added blocks must be reconciled
by hand.

---

## Service management

Services are managed through `deployment/services.sh` (start / stop / status)
and the systemd units it wraps. The aiohttp web shell, the connector relay,
and the Voilà application processes are separate units; restarting the shell
does not restart the relay. After a code deploy, restart the affected unit
and re-run the release verification above.

The relay reads `CRYOSTACK_RELAY_CONTROL_TOKEN` from the service environment
(`deployment/services.sh`), never from a file in the repo.

---

## Rollback

* **Connector release** — re-run `release_connector.sh` against a canonical
  store that holds the previous artifact set, or restore the previous
  `<store>/<platform>/` contents and release again. The promotion is atomic
  and self-verifying; a failed candidate leaves the live tree untouched.
* **Web deploy** — `deploy_web.sh` keeps the previous tree until the new one
  verifies; re-deploy from the previous book build to roll back.
* **Application code** — restart the previous release's service unit; the
  web shell and gateways are stateless between requests (per-user workspace
  state lives in the auth database, which is migration-versioned).

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/Users/...` path appears on the Linux release host | An old `publish_connector_artifact.sh` expanded the default store with the builder's `$HOME`. Fixed: the remote store resolves on the release host. Set `CRYOSTACK_RELEASE_STORE` only for a non-default location. |
| `list` shows an empty store / `build-candidate` fails with "no registered platforms" | Nothing registered on this host yet — run `publish_connector_artifact.sh` first. `release_connector.sh --print-config` shows the resolved store path. |
| Store resolved to `/root/.cryostack/...` | An older `release_connector.sh`. The current one resolves the store from the invoking user's home even under `sudo` (via `SUDO_USER`). |
| `Permission denied` writing under `<web-root>` when run without sudo | Expected — the script detects the root-owned web root and escalates only the **promotion** step. It never `chmod`s unrelated content. |
| `pairing_protocol ... != expected` on register | The connector was built from source older than the current pairing protocol. Rebuild, or `--allow-protocol-mismatch` for a deliberate compatibility build. |
| `zero bytes` / `sidecar sha256 does not match` on register | Truncated or corrupted build output. Rebuild; do not hand-edit the sidecar. |
| A platform is missing from `manifest.json` | Either never registered on this release host, or explicitly `unpublish`ed. `connector_store.py list` shows what the store actually holds. |
| `/connect/` returns `403` | The web tree was not re-hardened after `rsync -a`. Re-run `deploy_web.sh`; check `namei -l` and SELinux context. |
| `nginx_audit.sh` reports a duplicate `server_name` | A stale/other conf file also declares it. Identify it in the audit output and reconcile; do not blind-delete Certbot files. |
| Release "succeeded" but users report an old build | Check the **live** manifest and `connector_build_revision`; a release is only real once the served manifest reflects it. |
| ISSM container run dies at `launching solution sequence` with `No executable was specified on the prterun command line` / `No available launching agents were found` | A stray in-container `srun` shim shadowed PRRTE's own Slurm launcher. Fixed by pinning ISSM's in-container `mpiexec` to the batch node (`apptainer exec --env PRTE_MCA_ras=^slurm ...`). Container ISSM is single-node by design; route multi-node ISSM to the ICESEE-Spack backend. Do not reintroduce the shim. |

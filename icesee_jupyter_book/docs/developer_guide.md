# Developer Guide

This guide is for people **building, releasing, or operating** CryoStack itself.
It is separate from the end-user documentation: instructions for ordinary users
who install and pair the CryoStack Connector, and for configuring HPC access,
live in the CryoLauncher **User Manual**.

A consolidated platform-architecture and contribution guide is still in
progress. The section below is complete and authoritative.

---

## Building and Publishing CryoStack Connectors

The CryoStack Connector is the small desktop application that bridges the
browser to a VPN-protected cluster. Releasing it has **three deliberately
separate stages** so that a build produced on one machine can never disturb an
artifact built on another:

```
   native builder                         release host
 ┌───────────────┐   register    ┌──────────────────────────┐   release   ┌──────────────────────────┐
 │ dist/packages/│ ────────────► │ canonical artifact store │ ──────────► │ downloads/connectors/    │
 │  <artifact>   │               │  <store>/<platform>/     │  candidate  │  (served, public)        │
 │  <..build.json│               │  source of truth         │  + promote  │  deployment target only  │
 └───────────────┘               └──────────────────────────┘             └──────────────────────────┘
```

* **Native build output** — `dist/packages/` on the machine that can build that
  platform. Transient; never published directly.
* **Canonical artifact store** — `<store>/<platform>/`, a persistent directory
  **outside the web root** on the release host, one subdirectory per platform.
  This is the source of truth for what is publicly available.
* **Served release** — `<web-root>/downloads/connectors/`. A deployment target
  only. Regenerated wholesale from the store on every release.

### Connectors cannot be cross-compiled

Each platform artifact must be built **natively**:

| Artifact | Builder |
|---|---|
| `CryoStack-Connector-linux-x86_64.tar.gz` | Linux x86_64 host |
| `CryoStack-Connector-macos-arm64.dmg` | Apple Silicon Mac |
| `CryoStack-Connector-macos-x86_64.dmg` | Intel Mac |
| `CryoStack-Connector-windows-x86_64.exe` | Windows x86_64 host |

### 1. Build natively

On the appropriate builder:

```bash
bash build_connector.sh
```

(on a headless Linux host: `xvfb-run bash build_connector.sh`)

Inspect the result:

```bash
ls -lh dist/packages/
cat dist/packages/CryoStack-Connector-<platform>.<ext>.build.json
```

The `.build.json` **sidecar** travels with the artifact and is validated at
registration:

| Field | Meaning |
|---|---|
| `platform` | canonical platform key (`linux-x86_64`, `macos-arm64`, …) |
| `filename` | canonical artifact filename |
| `sha256` | checksum of the artifact, re-verified on register |
| `size_bytes` | artifact size, re-verified on register |
| `built_at` | UTC build time (not fabricated) |
| `pairing_protocol` | connector ↔ relay pairing protocol the binary speaks |
| `connector_build_revision` | exact source revision (`git` short SHA, `-dirty` if modified) |

**`pairing_protocol` matters.** The relay's session-pairing protocol is
versioned. A connector built from source that predates a protocol change cannot
pair with the current relay. Registration **refuses** an artifact whose
`pairing_protocol` does not match the value this release line expects, so an
outdated binary can never be published as current merely because its filename
matches. Override deliberately (e.g. to stage a compatibility build) with
`--allow-protocol-mismatch`.

### Branding

Every packaging icon is derived from **one** canonical image,
`icesee_jupyter_book/cryostack.png`. `build_connector.sh` runs
`scripts/build_brand_assets.py` first, which regenerates
`icesee_hpc_connector/assets/cryostack-connector.{icns,ico,-512.png}` and the
`/connect/` logo. Do not hand-edit those outputs — change the canonical file and
re-run. macOS/`.app` and Windows/`.exe` get the icon via `--icon`; the Linux
tray loads the 512px PNG; the displayed name is always **CryoStack Connector**.

`build_brand_assets.py` also derives `icesee_jupyter_book/ui/assets/cryostack-mark-96.png`,
the small mark base64-embedded by the shared Voila application header
(`shared_application_header.py`). Same canonical source — do not hand-edit it.

### Shared application UI (B4)

The Voila gateways (IceSheets, ICESEE, future Icepack) share generic,
model-neutral UI building blocks in `icesee_jupyter_book/ui/`:

* `shared_application_header.build_application_header(app_name)` — compact shell
  header: CryoStack wordmark + a distinct, prominent application name.
* `shared_remote_connection_panel.build_remote_connection_panel(...)` —
  reorganises the existing remote widgets into *Compute resource* / *Your HPC
  identity* / *Access* / *Status*, with a status chip (Not checked / Verified /
  Mismatch / Failed driven by the B3 AccessState), the connector card, and the
  session id / websocket path / relay + raw state hidden behind a **Diagnostics**
  accordion. `apply_profile(profile)` refreshes the resource-aware auth options
  and the manual key-registration checklist.
* `shared_slurm_resources_panel.build_slurm_resources_panel(...)` — groups the
  existing Slurm widgets into *Job settings* / *Compute resources* /
  *Allocation & notifications* with full-word labels and help text. Serializer
  keys and submission kwargs are unchanged.
* `shared_auth_ux` — auth methods come from `ComputeProfile.auth_modes` /
  `ssh_agent_supported`; certificates / token auth / portal provisioning are
  never advertised. Manual registration shows a fixed six-step checklist and
  never asks for the institutional web-portal password.
* `shared_validation` — pure pre-submit checks (nodes/tasks/tasks-per-node
  floors and consistency, wall-time and memory syntax, account required only
  when the profile says so). No invented site limits.

These panels arrange the gateway's **existing** widget instances — they do not
own transport, the B3 Run gate, identity verification, or model logic.
Responsive rules for every shared class live only in
`shared_app_styles.py`.

### SSH credential namespace (B3)

Both the server-side "SSH Key Manager" and the workstation Connector now
namespace the generated SSH key by **resource + HPC username** (and, server-side,
the authenticated CryoStack user) instead of cluster name alone — the old
scheme (`~/.ssh/id_ed25519_icesee_<cluster>`) let two different people
configuring the same resource collide on one key. New keys live under
`~/.ssh/cryostack/id_ed25519_<namespace>`. The old key is **never read or
adopted automatically**; if present it is simply orphaned and reported (not
deleted) so an operator can clean it up once its replacement is confirmed
working. Existing users re-register/re-bootstrap the new key once.

### macOS connector — architecture & acceptance test

The macOS connector uses a strict split: the Cocoa main thread does **UI only**
(menu, the onboarding/status window, a `rumps.Timer` status poll), while **one**
background worker owns the HTTP pairing exchange, the WebSocket
connect/reconnect, and every SSH operation. `--onedir` (not `--onefile`) is used
for the `.app`, and the bundle is **ad-hoc signed** (`codesign -s -`) so a copy
in `/Applications` is not subject to Gatekeeper *App Translocation*.

It is **not menu-bar-only**: a normal Dock-visible window appears on launch and
whenever the connector is unpaired, with an obvious pairing field. After pairing
it becomes a **✓ Connected** panel with *Open CryoStack* / *Hide Window*. The
menu bar stays as a control surface (Status, Show CryoStack Connector,
Pair/Re-pair, Open Setup Page, Open Log File, Quit). Clicking the Dock icon (or
**Show CryoStack Connector**) brings the window back.

**Acceptance test — run the copy installed in `/Applications`, on an Apple
Silicon Mac:**

1. Mount the DMG, drag **CryoStack Connector** to Applications, eject the DMG.
2. Double-click `/Applications/CryoStack Connector.app` → a **visible window**
   appears with `Status: Not paired` and a pairing field. (No menu-bar
   knowledge required.)
3. Leave it **60 s** unpaired — window and menu stay responsive.
4. Enter a valid pairing code (from the CryoLauncher/ICESEE UI) → `Pair` →
   window shows **✓ Connected**; menu shows `Status: connected ✓`.
5. **Hide Window**; reopen via **Show CryoStack Connector** and via a Dock click.
6. Stay connected several minutes; drop the network/relay then restore →
   `reconnecting… → connected ✓`, no freeze.
7. **Quit** → `pgrep -fl 'CryoStack Connector'` shows nothing.
8. Relaunch immediately — **no reboot**; a second launch shows *"CryoStack
   Connector is already running"* and exits.

**If the `/Applications` copy is unresponsive** (while the DMG copy works), it is
almost certainly translocation of an unsigned bundle. Run the audit:

```bash
bash scripts/diagnose_connector_macos.sh
```

It checks running processes, the single-instance lock
(`~/.cryostack/connector.lock`), the `com.apple.quarantine` xattr, `codesign` /
`spctl` state, and whether the process command path contains `AppTranslocation`.
Clear it with `xattr -dr com.apple.quarantine "/Applications/CryoStack Connector.app"`.
If the app is genuinely hung, capture the main-thread stack first:

```bash
sample "$(pgrep -f 'CryoStack Connector' | head -1)" 5 -file /tmp/cryostack-connector-sample.txt
```

Lifecycle events are in `~/icesee_connector.log` as `[lifecycle] <ts> <event>`
(fixed names only — never a pairing code, secret, or SSH argument).

#### Known macOS issues (accepted for the current release)

Connector **v2 pairing, direct launch, the menu bar, and the visible
pairing/status window all work**. Two macOS issues are deferred:

1. **`/Applications` copy can become unresponsive** while a direct launch (from
   the DMG or elsewhere) works. Suspected cause: Gatekeeper App Translocation of
   the ad-hoc-signed (not Developer-ID-notarized) bundle. **Workaround:**
   `xattr -dr com.apple.quarantine "/Applications/CryoStack Connector.app"` then
   relaunch, or run from a non-`/Applications` location; `bash
   scripts/diagnose_connector_macos.sh` confirms translocation. Real fix =
   Developer-ID signing + notarization (future).
2. **Copy/paste into the pairing-code field does not work reliably** in the
   native window / `rumps.Window`. **Workaround:** type the code, or export
   `CRYOSTACK_PAIRING_CODE` before launch.

Do not regress the working direct-launch path while addressing these.

### 2. Register into the canonical store

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

The store path is resolved **on the release host**, from `<release-user>`'s home
(`~/.cryostack/connector-artifacts`). The builder's home is never used remotely —
so a Mac's `/Users/<name>/…` cannot leak onto a Linux release host.

`CRYOSTACK_RELEASE_STORE` is an **optional override**, not normally required:

```bash
export CRYOSTACK_RELEASE_STORE=<remote-store-path>   # only if the store is not in the default location
```

When it is omitted, the default is resolved from the release user's home **on
the release host**.

Registering one platform never touches another. Registering macOS preserves the
Linux artifact; registering Windows later preserves both.

### 3. Inspect the canonical store

On the release host:

```bash
python3 deployment/connector_store.py list
```

```
[store] /home/<release-user>/.cryostack/connector-artifacts
[store]   linux-x86_64   CryoStack-Connector-linux-x86_64.tar.gz       383220894  v2  1a2b3c4d5e6f
[store]   macos-arm64    CryoStack-Connector-macos-arm64.dmg            61365713  v2  1a2b3c4d5e6f
```

### 4. Release

Run **as the release owner, without sudo**:

```bash
bash release_connector.sh
```

`release_connector.sh` manages the privilege boundary itself:

1. it resolves the canonical store from the **release owner's** home — never
   `/root`, even if the whole script is invoked under `sudo`;
2. it inspects the store, builds a **candidate** web tree and fully verifies it
   (manifest, `SHA256SUMS`, permissions) — all **unprivileged**;
3. only the final **atomic promotion** into the (root-owned)
   `downloads/connectors/`, and the nginx reload, run through `sudo` — which may
   trigger the site's sudo / Duo prompt the first time. That is expected.

If candidate verification fails, the currently served release is left
**byte-for-byte unchanged**; a failed directory swap rolls the previous live
release back. Re-running with the same store re-publishes the same release
(idempotent). After promotion the script enforces `0755` directories / `0644`
files and re-verifies the **live** tree before reporting success.

Check what it will do first, without touching anything:

```bash
bash release_connector.sh --print-config
```

> `sudo bash release_connector.sh` is also supported (the release owner and the
> canonical store still resolve to the **invoking** user via `SUDO_USER`, not to
> `root`), but it is not the normal workflow — you do not need to prefix the
> whole command with `sudo`.

`build_deploy_connector.sh` chains all three stages for the single-host case
(`CRYOSTACK_SKIP_BUILD=1` to skip the build and register/release an existing
`dist/packages/` artifact).

### 5. Verify the public release

A connector release is only operational when **both** the setup page and the
downloads respond:

```bash
curl -sSIL https://cryostack.eas.gatech.edu/connect/
curl -sSL  https://cryostack.eas.gatech.edu/downloads/connectors/manifest.json
```

`/connect/` must return `HTTP/2 200` (not `403`). A `403` there is almost always
DAC permissions: `deploy_web.sh` re-hardens the web tree to `0755` dirs / `0644`
files after `rsync -a` (which otherwise preserves the repo's `0770/0660`), and
runs `restorecon` when SELinux is active. If it still 403s:

```bash
sudo namei -l /var/www/cryolauncher/connect/index.html
sudo tail -n 50 /var/log/nginx/error.log
getenforce; ls -Zd /var/www/cryolauncher/connect
```

Then the download checks:

```bash
curl -sSL  https://cryostack.eas.gatech.edu/downloads/connectors/SHA256SUMS
curl -sSIL https://cryostack.eas.gatech.edu/downloads/connectors/<artifact> \
  | grep -Ei 'HTTP/|content-(type|length|disposition)'
```

A healthy artifact response is `HTTP/2 200`, `Content-Type:
application/octet-stream`, `Content-Disposition: attachment`, and a
`Content-Length` matching `size_bytes` in the manifest.

**Always check the live `manifest.json` before assuming a release succeeded** —
it lists exactly the platforms currently published and their `pairing_protocol`.
`deploy_web.sh` runs the `/connect/` smoke check itself after every deploy
(override the host with `CRYOSTACK_PUBLIC_BASE`, skip with
`CRYOSTACK_SKIP_SMOKE=1`).

### 6. Audit nginx

```bash
sudo bash deployment/nginx_audit.sh
```

A healthy result: exactly one `server` block owns `server_name
cryostack.eas.gatech.edu` on each listen address, exactly one `map
$connection_upgrade`, and `OK: no server_name appears in more than one block`.
A duplicate means a stale conf file is still loaded — `deploy_web.sh` disables
known prior CryoStack blocks, but Certbot-managed or hand-added blocks must be
reconciled by hand.

### 7. Remove a platform

A platform is **only** removed on request:

```bash
python3 deployment/connector_store.py unpublish <platform>
bash release_connector.sh
```

Publishing or releasing from one builder must never remove artifacts built on
another platform. `unpublish` is the intentional removal mechanism.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `/Users/...` path appears on the Linux release host | An old `publish_connector_artifact.sh` expanded the default store with the builder's `$HOME`. Fixed: the remote store resolves on the release host. Set `CRYOSTACK_RELEASE_STORE` only for a non-default location. |
| `list` shows an empty store / `build-candidate` fails with "no registered platforms" | Nothing is registered on this host yet — run `publish_connector_artifact.sh` first. `release_connector.sh --print-config` shows the resolved store path. |
| Store resolved to `/root/.cryostack/...` | An older `release_connector.sh`. The current one resolves the store from the invoking user's home even under `sudo` (via `SUDO_USER`). `--print-config` confirms `canonical_store`. |
| `Permission denied` writing under `/var/www/...` when run without sudo | Expected on a normal deployment — the script detects the root-owned web root and escalates the **promotion** step with `sudo` on its own (watch for the Duo prompt). It never `chmod`s unrelated `/var/www` content. |
| `pairing_protocol ... != expected` on register | The connector was built from source older than the current pairing protocol and cannot pair. Rebuild from current source, or `--allow-protocol-mismatch` if you deliberately need a compatibility build. |
| `zero bytes` / `sidecar sha256 does not match` on register | Truncated or corrupted build output. Rebuild; do not hand-edit the sidecar. |
| A platform is missing from `manifest.json` | Either never registered on this release host, or explicitly `unpublish`ed. `connector_store.py list` shows what the store actually holds. |
| `nginx_audit.sh` reports a duplicate `server_name` | A stale/other conf file also declares it. Identify it in the audit output and reconcile; do not blind-delete Certbot files. |
| Release "succeeded" but users report an old build | Check the **live** manifest (`curl .../manifest.json`) and `connector_build_revision`; a release is only real once the served manifest reflects it. |

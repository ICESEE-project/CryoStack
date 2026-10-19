# Maintainer / Operations Guide

**Restricted.** This guide is for people **operating a CryoStack deployment**.
It is served to owners and to maintainers or admins whom an owner has
explicitly granted Developer Guide access in **Control Center → Users**. A
Control Center role alone is not sufficient. The capability is audited,
owner-revocable, and automatically removed when the recipient is demoted to
developer or user. It is deliberately **excluded from the public book build**
(`_toc.yml`).

Start with the owner-only [Service operations and release runbook](service_operations.md)
for the platform topology, durable-store map, staging rules, release gates,
rollback sequence, and return-from-leave checklist.

Placeholders used throughout — substitute your deployment's values, never
commit real ones:

| Placeholder | Meaning |
|---|---|
| `<release-host>` | SSH target of the release/deploy host |
| `<release-user>` | account that owns the canonical store on the release host |
| `<web-root>` | nginx document root for the site (e.g. the path in `icesee.conf`) |
| `<public-base>` | public HTTPS base URL of the deployment |
| `<resource-id>` | a compute-resource identifier |
| `<site-domain>` | the site's TLS hostname (the `server_name` in `icesee.conf`) |

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

Build the artifact first (see the Developer Guide → *Connector
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

## TLS certificate renewal

TLS terminates at **nginx** on the web host. The certificate is a Let's
Encrypt certificate managed by **Certbot** (EL9 EPEL packages `certbot` and
`python3-certbot-nginx`), using the nginx authenticator and installer:

| Item | Location / value |
|---|---|
| Renewal configuration | `/etc/letsencrypt/renewal/<site-domain>.conf` (`authenticator = nginx`, `installer = nginx`) |
| Certificate used by nginx | `/etc/letsencrypt/live/<site-domain>/fullchain.pem` and `privkey.pem` (symlinks to the newest files in `/etc/letsencrypt/archive/`) |
| nginx TLS block | `deployment/deploy_web_nginx/nginx/icesee.conf` (the `# managed by Certbot` lines) |
| Renewal schedule | systemd `certbot-renew.timer` → `certbot-renew.service` (twice a day, randomized delay, `Persistent=true`) |
| Hook settings | `/etc/sysconfig/certbot` (`PRE_HOOK`, `POST_HOOK`, `DEPLOY_HOOK`; empty by default) and `/etc/letsencrypt/renewal-hooks/{pre,deploy,post}/` |
| Logs | `journalctl -u certbot-renew.service` and `/var/log/letsencrypt/letsencrypt.log` |

On EL9 the timer is named `certbot-renew.timer` (not `certbot.timer`). It is
installed **disabled**, so it must be enabled once -- there is no cron entry
for Certbot, so this does not create a duplicate schedule:

```bash
sudo systemctl enable --now certbot-renew.timer
systemctl list-timers --all | grep certbot
```

`certbot renew` only replaces a certificate within 30 days of expiry (the
default); runs at other times are no-ops.

**nginx reload.** Because the certificate uses the nginx *installer*, Certbot
reloads nginx itself after it deploys a renewed certificate; no extra deploy
hook is needed and the CryoStack application services are not restarted. If
the certificate is ever re-issued with a different installer (for example
`--webroot`), add a deploy hook, which runs only after a successful renewal:

```bash
sudo install -m 0755 /dev/stdin /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK'
#!/bin/sh
nginx -t && systemctl reload nginx
HOOK
```

**Validate** (safe: the dry run uses the Let's Encrypt staging service and
changes nothing):

```bash
sudo certbot renew --dry-run
sudo nginx -t && sudo systemctl reload nginx
systemctl status certbot-renew.timer --no-pager
echo | openssl s_client -connect <site-domain>:443 -servername <site-domain> -verify_return_error 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
curl -sSI http://<site-domain>/ | head -n 3            # 301 to https://
curl -sSI <public-base>/auth/login | head -n 1         # 200
```

The certificate must list `DNS:<site-domain>`, `Verify return code: 0 (ok)`,
and a `notAfter` more than 30 days ahead.

**Failure visibility.** A failed renewal is recorded in the journal of
`certbot-renew.service` and in `letsencrypt.log`; the service unit enters the
`failed` state (`systemctl --failed`). Let's Encrypt no longer sends
expiration e-mails, so monitor the expiry date from outside -- for example a
check that alerts when the served certificate expires within 14 days:

```bash
echo | openssl s_client -connect <site-domain>:443 -servername <site-domain> 2>/dev/null \
  | openssl x509 -noout -checkend $((14*24*3600)) || echo "certificate expires within 14 days"
```

**Troubleshooting.**

* *Dry run fails with an authorization/connection error* -- the nginx
  authenticator answers the HTTP-01 challenge on port 80: port 80 must stay
  reachable from the Internet (campus firewall) and the HTTP server block must
  keep serving `/.well-known/acme-challenge/`; check `nginx -t` first.
* *nginx still serves the old certificate* -- `sudo systemctl reload nginx`,
  then re-run the `openssl` check; confirm the `ssl_certificate` paths point to
  `live/`, not `archive/`.
* *Timer disabled again* -- this host is also managed by campus configuration
  management (Salt highstate runs daily); if the timer state is reverted, ask
  the system administrators to enable `certbot-renew.timer` in the host's
  configuration.
* *Rate limits* -- never use `--force-renewal` routinely; test with
  `--dry-run`.

---

## Frozen Legacies data backup

Frozen Legacies keeps review submissions, decisions and published observations in its SQLite catalog **and** immutable review snapshots on disk; one is useless without the other. Back them up together with the module built for it, and back up the `users/` workspace root at the same time:

```bash
python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup create --out /backups/frozen-legacies
python -m icesee_jupyter_book.applications.frozen_legacies.radar.backup verify /backups/frozen-legacies/frozen-legacies-<UTC time>
```

`create` and `verify` exit non-zero when anything is missing or damaged. Restore with the GUI services stopped (`deployment/services.sh stop-gui`, then `... backup restore <backup>`, `--force` to replace existing data, which is moved aside rather than deleted). Details: Frozen Legacies Developer Guide, *Backup and recovery*.

## Service management

Services are managed through `deployment/services.sh` (start / stop / status)
and the systemd units it wraps. The aiohttp web shell, the connector relay,
and the Voilà application processes are separate units; restarting the shell
does not restart the relay. After a code deploy, restart the affected unit
and re-run the release verification above.

The relay reads `CRYOSTACK_RELAY_CONTROL_TOKEN` from the service environment
(`deployment/services.sh`), never from a file in the repo.

The Voilà application servers do not inherit the gateway's environment. The
gateway starts them with an allowlist (`VOILA_ENV_ALLOWLIST` in
`bin/icesee_app.py`): application settings, the AWS profile name and region,
and scientific model paths. OAuth client secrets, the relay control token,
static AWS keys and operator session variables never reach a notebook kernel.
A new setting that kernels must read has to be added to that allowlist.

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

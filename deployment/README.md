# CryoStack Deployment Framework

The CryoStack deployment framework provides a unified way to build, update,
validate, and operate all CryoStack applications.

Unlike the original `reboot_gui.sh`, the deployment system understands
application dependencies and restart policies, allowing individual applications
to be rebuilt without unnecessarily interrupting the rest of the platform.

---

# Architecture

```
                    applications.yaml
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
   preflight.py     cryostack_build.py   health_check.py
         │                 │                 │
         └────────────┬────┴─────────────────┘
                      │
                 services.sh
                      │
                CryoStack runtime
```

`applications.yaml` is the single source of truth.

Every deployment tool reads from the registry rather than maintaining its own
knowledge of applications.

---

# Components

## applications.yaml

Defines

- applications
- dependencies
- build steps
- required software
- artifacts
- restart policy
- health checks
- routes

No deployment script should contain application-specific logic.

---

## cryostack_build.py

Responsible only for building applications.

Supports

```
list
build
policy
```

Examples

```bash
python deployment/cryostack_build.py list

python deployment/cryostack_build.py build frozen-legacies

python deployment/cryostack_build.py build livist

python deployment/cryostack_build.py build all
```

---

## preflight.py

Checks

- Python availability
- required executables
- required directories
- required files

before a build begins.

Example

```bash
python deployment/preflight.py \
    --application frozen-legacies
```

---

## services.sh

Controls runtime services only.

It never performs builds.

### Entire platform

```bash
deployment/services.sh start

deployment/services.sh stop

deployment/services.sh restart

deployment/services.sh status
```

### GUI only

```bash
deployment/services.sh start-gui

deployment/services.sh stop-gui

deployment/services.sh restart-gui
```

### Connector only

```bash
deployment/services.sh start-connector

deployment/services.sh stop-connector

deployment/services.sh restart-connector
```

---

## update_gui.sh

Updates one application.

Example

```bash
./update_gui.sh frozen-legacies
```

The script automatically

1. runs preflight
2. resolves dependencies
3. determines restart scope
4. builds required applications
5. restarts only affected services
6. performs health checks

---

## reboot_gui.sh

Performs a complete platform rebuild.

Use when

- modifying shared infrastructure
- upgrading Jupyter Book
- upgrading CryoLauncher
- rebuilding every application

Example

```bash
./reboot_gui.sh
```

---

# Typical Workflows

## Build a single application

```bash
python deployment/cryostack_build.py \
    build frozen-legacies
```

---

## Update a single application

```bash
./update_gui.sh frozen-legacies
```

---

## Rebuild everything

```bash
./reboot_gui.sh
```

---

## Check runtime status

```bash
deployment/services.sh status
```

---

## Check platform health

```bash
python deployment/health_check.py
```

---

## Check one application

```bash
python deployment/health_check.py \
    --application frozen-legacies
```

---

## Back up and rehearse a restore

```bash
python deployment/cryostack_backup.py create --dest ~/cryostack-backups
python deployment/cryostack_backup.py verify ~/cryostack-backups/<stamp>
python deployment/cryostack_backup.py drill  ~/cryostack-backups/<stamp> --scratch /tmp/cryostack-drill
```

`create` copies the auth database, the Frozen Legacies catalog and review
snapshots, the Control Center ops store, the LIVIST job store and both
workspace roots (gateway `users/` and Voila `icesee_jupyter_notebooks/users/`)
while the services keep running, into an owner-only directory with
`SHA256SUMS` and `BACKUP.json`. The destination may not be inside the
repository. `drill` restores everything into the scratch directory -- never
into the installation -- and checks that it opens and matches. Copy the
backup off-host and re-run `verify` there. Output contains counts only.
SQLite files are opened read-only and an idle database is copied without
leaving `-wal`/`-shm` files beside it. `--installation <repository>` backs up
another checkout's data (for example the running installation from a
review copy).

### Encrypted off-host copy

Backups hold password hashes and session ids, so they leave the host only
encrypted to a recovery key whose private half is never on this host.

1. Once, on the recovery machine (an administrator's workstation or the
   off-site host): `gpg --quick-generate-key "CryoStack recovery
   <ops@example.org>" default default never`, keep the private key and its
   passphrase there (plus a paper or hardware-token copy), and bring only
   `gpg --armor --export <fingerprint> > cryostack-recovery-pub.asc` to this
   host.
2. Here, after `create` and `verify`:

   ```bash
   python deployment/cryostack_backup.py export ~/cryostack-backups/<stamp> \
       --recipient-key cryostack-recovery-pub.asc --dest ~/cryostack-offhost
   rsync -av --chmod=F600 ~/cryostack-offhost/<stamp>.tar.gpg* <off-host>:cryostack/
   ssh <off-host> 'cd cryostack && sha256sum -c <stamp>.tar.gpg.sha256'
   ```

   `export` refuses a backup that does not verify and a key file that
   contains a private key; no plaintext archive is written.
3. Restore rehearsal on the recovery machine:

   ```bash
   python deployment/cryostack_backup.py unpack <stamp>.tar.gpg --into /scratch/restore
   python deployment/cryostack_backup.py drill /scratch/restore/<stamp> --scratch /scratch/drill
   ```

Keep at least the last seven daily and four weekly archives off-host; delete
the local `~/cryostack-offhost` copy once the remote checksum matches.

## Isolate notebook kernels

Voilà kernels run user-influenced code (examples, configuration, local
model runs). Without isolation they can read the gateway's environment
(OAuth secrets, relay token), the databases in `var/`, the operator's
`~/.aws`, `~/.ssh` and `~/.cryostack`, the backups, every other user's
workspace, and write the code. Two independent layers close this.

### Layer 1 — per-user kernel sandbox (no root needed)

`bin/cryostack_kernel.py` is the `python3` kernelspec of both Voilà servers
(`bin/voila_config/kernels/python3`). With `CRYOSTACK_KERNEL_SANDBOX=bwrap`
every kernel starts inside bubblewrap: its own process tree (the gateway is
not visible), the system, Python environment and code read-only, `var/`,
`users/`, logs and local source configuration hidden, only the signed-in
user's workspace directory writable, `HOME` inside that directory (HPC keys
and `~/.ssh/config` per user), and model installations (`ISSM_DIR`,
`ICEPACK_ROOT`, or `~/ISSM`, `~/icepack`) read-only. Local ICESEE runs
execute a private copy of the example inside the user's run directory. A
kernel without a CryoStack identity or without bubblewrap does not start.

1. Requirements: the `bubblewrap` package and unprivileged user namespaces
   (`/proc/sys/user/max_user_namespaces` > 0); both present on RHEL 9.
2. AWS for hosted cloud runs: put a least-privilege profile for kernels
   (`config` + `credentials`; Batch submit/describe, its logs, the results
   bucket, `sts:AssumeRole` on customer roles — never the operator's keys)
   in a directory only the service account can read, and set
   `CRYOSTACK_KERNEL_AWS_DIR` to it. Without it kernels have no AWS
   credentials (bring-your-own-account runs still assume roles with what the
   user's connection provides).
3. HPC keys: `python deployment/migrate_kernel_ssh_keys.py --workspace-root
   <repo>/icesee_jupyter_book/icesee_jupyter_notebooks` (dry run), then
   `--apply`: copies each CryoStack key pair from `~/.ssh/cryostack` into
   its owner's sandbox home (originals kept). Users who relied on the Voilà
   account's personal `~/.ssh/id_ed25519` must authorise a CryoStack key
   generated in the app.
4. Enable: `CRYOSTACK_KERNEL_SANDBOX=bwrap` in the gateway environment
   (`services.sh`), restart the gateway (its Voilà servers restart with it).
5. Accept: `python -m pytest cryostack_src/tests/test_kernel_sandbox.py`
   on the host, then sign in, open CryoLauncher and ICESEE, restore a
   workspace, run the Lorenz-96 local example, open a Remote connection.
6. Roll back: unset `CRYOSTACK_KERNEL_SANDBOX` (or set `off`) and restart.
   The per-user copies of keys stay where they are.

### Layer 2 — Voilà under its own account (administrator)

Defence in depth: even a kernel escaping the sandbox lands in an account
that cannot read the gateway's files. `deployment/check_kernel_isolation.py`
lists what an account can reach (permission checks only, nothing is read):

```bash
sudo -u cryostack-kernel /path/to/python deployment/check_kernel_isolation.py \
    --installation /home/<operator>/CryoLauncher --operator-home /home/<operator>
```

1. Accounts: `useradd --system --create-home --home-dir /var/lib/cryostack-kernel
   --shell /sbin/nologin cryostack-kernel`; a group `cryostack-voila` holding
   both the operator and `cryostack-kernel` (never add the kernel account to
   the operator's own group: `var/`, `users/` and `~/.aws` are group-writable).
2. Read-only code: `setfacl -m u:cryostack-kernel:--x <operator home>`;
   `setfacl -R -m u:cryostack-kernel:r-X,d:u:cryostack-kernel:r-X` on the
   repository and the conda environment; then
   `setfacl -R -m u:cryostack-kernel:---,d:u:cryostack-kernel:---` on
   `var/` and `users/`.
3. Kernel-owned data: the Voilà workspace root
   (`icesee_jupyter_book/icesee_jupyter_notebooks/users/`) and
   `icesee_jupyter_book/icesee_runs/` owned by `cryostack-kernel:cryostack-voila`,
   mode `2770`. The kernel AWS directory of layer 1 readable by it only.
4. Shared Voilà token: a random token of at least 32 characters in
   `/etc/cryostack/voila_token`, `root:cryostack-voila`, mode `0640`
   (hidden inside the sandbox).
5. Voilà servers: `deployment/kernel-account/cryostack-voila@.service`
   (`systemctl enable --now cryostack-voila@icesee cryostack-voila@icesheets`).
   They run `bin/icesee_app.py voila <app>` -- the gateway's own command line
   and environment allowlist; put `CRYOSTACK_KERNEL_SANDBOX=bwrap` in
   `/etc/cryostack/voila.env`.
6. Gateway: `CRYOSTACK_VOILA_MODE=external` and
   `CRYOSTACK_VOILA_TOKEN_FILE=/etc/cryostack/voila_token`, then restart it.
   It no longer starts Voilà; it proxies, warms up and reports the two
   services as before. Note: `services.sh stop` kills every `voila` process
   of the operator account by pattern; the units are not affected.
7. Accept: `check_kernel_isolation.py` as `cryostack-kernel` exits 0; repeat
   the checks of layer 1.
8. Roll back: unset `CRYOSTACK_VOILA_MODE`, restart the gateway (it starts
   its own Voilà again), `systemctl disable --now cryostack-voila@*`.

---

# Adding a New Application

Adding an application requires only one new section in
`applications.yaml`.

Example

```yaml
applications:

  my-new-app:

    title: My New Application

    dependencies:
      - cryostack-book

    build:

      - name: Build application

        command:

          - python
          - build.py

    artifacts:

      - applications/my-new-app/site/index.html

    routes:

      - /my-new-app/

    restart:

      scope: none

    health:

      target: my-new-app

      path: /my-new-app/

      expected_statuses:

        - 200
```

After adding the registry entry, the application automatically becomes available
to

- preflight
- build
- dependency resolution
- selective update
- health checks

without modifying any deployment scripts.

---

# Restart Scopes

Three restart scopes currently exist.

## none

No runtime interruption.

Example

```
Frozen Legacies
```

---

## gui

Restart only the GUI.

Example

```
CryoLauncher UI
```

---

## connector

Restart only the connector relay.

---

## all

Restart the entire CryoStack runtime.

Example

```
Core platform changes
```

---

# Design Principles

The deployment framework follows five principles.

## 1. Registry Driven

Everything is described in
`applications.yaml`.

---

## 2. Dependency Aware

Applications are built in dependency order.

---

## 3. Zero-Downtime Updates

Applications that do not affect the runtime may be updated without restarting
the platform.

---

## 4. Single Source of Truth

Deployment information exists only once.

Scripts consume the registry.

---

## 5. Extensible

Future applications should require only registry changes rather than modifying
deployment scripts.

Examples include

- CryoLauncher
- ICESEE
- Frozen Legacies
- LIVIST
- Borehole Explorer
- Data Catalog
- User Dashboard
- Authentication Portal

---

# Future Roadmap

Planned improvements include

- PID-based service management
- Docker deployment backend
- Kubernetes backend
- Slurm deployment backend
- Remote deployment
- Automatic dependency graph visualization
- Incremental builds
- Parallel application builds
- Deployment caching
- GitHub Actions integration
- Production deployment profiles
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
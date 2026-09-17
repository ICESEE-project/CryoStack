# Connector & Relay

:::{raw} html
<style>
.bd-article-container section:first-child > h1:first-child {
  display: none !important;
}
</style>
:::

:::{raw} html
<div class="cryostack-docs-page">
  <section class="cryostack-docs-hero">
    <div class="cryostack-section-label">CryoStack Developer Guide</div>
    <h1>Connector &amp; Relay</h1>
    <p>
      Architecture, building a Connector locally, versioning, and what is
      (and is not) automated about publishing an update.
    </p>
    <div class="cryostack-docs-actions">
      <a class="cryostack-btn secondary" href="developer_guide.html">
        &larr; Developer Guide
      </a>
    </div>
  </section>
</div>
:::

---

The CryoStack Connector is the small desktop application that bridges the
browser to a VPN-protected cluster over the relay — shared infrastructure
used by both Remote access and, when a Cloud workflow needs private
institutional connectivity, Cloud workloads (see
[Execution Backends](dev_execution.md) for the shared
session/two-capability-plane architecture).

## Architecture

Pairing uses a versioned protocol: a `session_id` that is not secret, a
one-time `pairing_code`, and per-session secrets that authenticate the
connector's WebSocket. The relay never exposes a "newest session" endpoint.
On macOS the Cocoa main thread does UI only (menu, onboarding/status window,
a timer status poll) while **one** background worker owns the HTTP pairing
exchange, the WebSocket connect/reconnect, and every SSH operation. The
`.app` is built `--onedir` and ad-hoc signed so a copy in `/Applications` is
not subject to Gatekeeper App Translocation.

**Where it lives.** The desktop application's source is
`icesee_hpc_connector/`. The relay server it pairs with is
`icesee_jupyter_book/core/connector_relay_server.py`, exposing both the
Remote command-dispatch endpoints (`/connector/ws/{id}`) and the Cloud
private-service tunnel endpoints (`/connector/tunnel-grant/{id}`,
`/connector/tunnel/{id}`, `/connector/tunnel-data/{id}`). The Connector-side
allow-list of what it will tunnel to (`SITE_TUNNEL_TARGETS`) lives in
`icesee_hpc_connector/connector_core.py` and resolves symbolic
`(purpose, endpoint)` pairs to real `(host, port)` only on the Connector
side — the relay and the Cloud caller never supply or see the real target.

## Build one locally

On the platform you are targeting (connectors cannot be cross-compiled):

```bash
bash build_connector.sh
# headless Linux:
xvfb-run bash build_connector.sh
```

`build_connector.sh` first runs `scripts/build_brand_assets.py`, which
regenerates every icon and the shared header mark from the one canonical
`icesee_jupyter_book/cryostack.png`. Do not hand-edit those outputs.

Inspect the result:

```bash
ls -lh dist/packages/
cat dist/packages/CryoStack-Connector-<platform>.<ext>.build.json
```

## Versioning and the build sidecar

The `.build.json` sidecar travels with the artifact:

| Field | Meaning |
|---|---|
| `platform` | canonical platform key (`linux-x86_64`, `macos-arm64`, …) |
| `filename` | canonical artifact filename |
| `sha256`, `size_bytes` | re-verified when the artifact is registered for release |
| `built_at` | UTC build time |
| `pairing_protocol` | the connector–relay pairing protocol the binary speaks |
| `connector_build_revision` | exact source revision (`git` short SHA, `-dirty` if modified) |

`pairing_protocol` matters: a connector built from source that predates a
protocol change cannot pair with the current relay, and release registration
refuses a mismatch.

## Publishing an update — what is automated, what is not

Building the artifact and computing its `.build.json` sidecar (hash, size,
pairing protocol, source revision) is automated by `build_connector.sh`.
**Publishing and releasing a built artifact — registering it as the
downloadable version CryoStack points users to, updating
`/downloads/connectors/` — is a manual maintainer operation**, covered by the
separate, role-gated Maintainer Guide (`/docs/maintainer/`), not by this
public Developer Guide. Before replacing the deployed version, the
Connector's own test suite and the relay-protocol compatibility check (that
`pairing_protocol` matches the deployed relay) must pass; this repository
does not encode an automated release pipeline beyond the local build script
— treat anything not described here as a manual step until documented
otherwise.

## Known macOS issues (accepted for the current release)

Connector v2 pairing, direct launch, the menu bar, and the visible pairing/
status window all work. Two issues are deferred: a `/Applications` copy can
become unresponsive while a direct launch works (suspected App Translocation
of the ad-hoc-signed bundle; clear with
`xattr -dr com.apple.quarantine "/Applications/CryoStack Connector.app"`),
and paste into the pairing-code field is unreliable (type the code, or export
`CRYOSTACK_PAIRING_CODE`). `bash scripts/diagnose_connector_macos.sh` audits
translocation, quarantine, and signing state. Do not regress the working
direct-launch path while addressing these.

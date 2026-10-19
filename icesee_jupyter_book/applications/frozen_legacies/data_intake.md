# Frozen Legacies dataset intake

This runbook covers archival navigation tables and radar TIFFs received from
external collaboration storage. It deliberately separates temporary transfer,
validation, and durable publication.

## Storage lifecycle

1. Land new files in `/scratch/cryostack-development/incoming/`. Scratch is a
   temporary transfer and processing area, not the authoritative archive.
2. Record the source description, byte size, and SHA-256 digest before
   extraction or conversion.
3. Inspect archives for absolute paths, parent-directory traversal, symbolic
   links, encryption, excessive expansion, and unexpected file types.
4. Extract into a new directory without overwriting an earlier intake.
5. Validate file structure and scientific identifiers. Never manufacture
   missing observations or coordinates.
6. Promote accepted source files and their manifest to the configured CEDAR
   dataset mount. The application catalog remains an index and can be rebuilt.
7. Keep application workspaces on the configured CEDAR user mount. Do not use
   the repository, a home directory, or scratch as persistent application
   storage.

Production services must not read directly from the intake directory. A file
becomes available to users only after its durable location is registered as an
approved Frozen Legacies data source and indexing completes successfully.

## Curator web intake

When `CRYOSTACK_FROZEN_LEGACIES_INTAKE_ROOT` names a directory inside an
approved storage root, maintainers, administrators, and owners see **New
scientific intake** in Control Center → Frozen Legacies. They can upload TIFFs,
navigation CSVs, and ZIP film archives without using a shell. ZIP extraction
rejects absolute/parent paths, links, unsupported files, case-insensitive
destination collisions, more than 5,000 files, more than 4 GiB expanded data,
and suspicious expansion ratios. The request itself is limited to 1 GiB.

Successful staging writes a SHA-256 receipt and registers a local source as
maintainers-only. Every receipt item is `unverified` and the receipt is
`unpublished`. The curator then uses the existing buttons to test the source,
index changes, watch progress and failures, cancel, retry, inspect discovered
files, and explicitly change visibility only after scientific review. Staging
does not infer flight numbers, CBD ranges, coordinates, or observations;
filename parsing and navigation association remain the existing catalog
indexer's clearly labeled metadata behavior. CLI utilities are retained only
for operator recovery.

### Current large-upload limitation

The current form is intentionally a bounded first release, not the transfer
mechanism for the forthcoming film archive. It sends one multipart HTTP request
with a 1 GiB aggregate limit. An interrupted browser, gateway restart, or
service restart loses the request and the curator must upload it again. The
server first writes temporary request files and then copies them into a staging
tree, so peak space can approach twice the compressed upload plus the expanded
archive. A process crash can also leave `.upload-*` or `.staging-*`
directories; they are not currently reconciled automatically. Do not raise the
request limit to accommodate large batches.

### Required resumable-upload protocol

Implementation status (18 October 2026): the Control Center now uses the first
resumable path for maintainer intake. It uploads fixed 8 MiB chunks, verifies
each chunk in the browser and server, persists the opaque session ID locally,
resumes when the maintainer re-selects the same files, exposes progress/cancel,
and computes the authoritative whole-file SHA-256 while assembling on the
server. Sessions remain on the configured intake volume and finalized sources
remain unpublished. Cross-process locking, expiry/janitor reconciliation, and
the 1 TiB protocol limits below remain release gates before raising the current
4 GiB session bound.

Large TIFF and film intake uses durable upload sessions rather than one
large multipart request. The browser workflow remains **New scientific
intake**, but the wire contract is:

1. `POST /frozen-legacies/api/admin/upload-sessions` creates a session after
   validating source ID, dataset ID, expected file list, byte sizes and optional
   client SHA-256 values. The response supplies an opaque 256-bit session ID,
   an expiry, a server-selected chunk size (64 MiB by default), and the chunks
   already committed. Creating the same request with the same idempotency key
   returns the existing session.
2. `PUT .../upload-sessions/{session}/files/{file}/chunks/{index}` accepts one
   chunk. Require a declared byte range, exact length and SHA-256 digest. Write
   to a new file in the session directory, `fsync` it, atomically rename it to
   its committed name, `fsync` the containing directory, and record it in the
   session database transaction. A retry with the same digest is a no-op; a
   conflicting retry is `409 Conflict`. Do not append to a shared partial file.
3. `GET .../upload-sessions/{session}` returns only the caller-visible session
   manifest, committed chunk bitmap, verified bytes, expiry and actionable
   failures. The browser stores only the opaque ID and resumes by querying the
   server; browser local state is never authoritative.
4. `POST .../upload-sessions/{session}/finalize` acquires a per-session lock,
   verifies that every byte is present, streams chunks in order while computing
   the complete SHA-256, safely validates archives, writes the intake receipt,
   and atomically promotes one immutable release directory. Finalize is
   idempotent and returns the already-created source after a retry.
5. `DELETE .../upload-sessions/{session}` cancels an unfinalized session. It
   marks the database row cancelled before asynchronous byte removal so a
   concurrent upload cannot resurrect it. Indexing and publication remain
   separate explicit operations.

The session store must be a transactional durable database outside the source
tree. Each record includes owner, creator role, source and dataset IDs,
idempotency key, expected and received bytes, file/chunk digests, creation,
last-activity and expiry times, state, error, and final intake receipt ID. Use
the following state machine; no other transition is valid:

```text
open -> verifying -> finalized -> indexed -> published
  |         |            |
  +------> failed <-------+
  |
  +------> cancelled -> purged
open/failed -> expired -> purged
```

After a service restart, reconcile database rows with committed chunk files,
verify any chunk whose transaction may have been interrupted, remove only
uncommitted temporary chunks, and return sessions to `open` or `failed` with a
specific reason. Never infer `finalized`, `indexed`, or `published` from a
directory name. Finalized receipt and catalog registration should share an
idempotent operation/reconciliation record because an NFS rename and a local
database transaction cannot be one atomic transaction.

### CEDAR staging and capacity rules

Configure a dedicated durable session root on the writable CEDAR user/intake
mount, separate from immutable datasets and rebuildable preview caches. At
startup and before every mutation, verify the expected filesystem/mount ID,
attestation marker, writable service UID/GID, and NFS health. If the CEDAR mount
is absent, stale, read-only, or replaced by an underlying local directory,
intake must fail closed; never create a fallback directory on the VM root disk.
Temporary chunk files, committed chunks, assembled releases and receipts must
remain on the same mounted filesystem so atomic rename does not cross devices.

Reserve capacity before accepting a session. The reservation is the sum of
declared source bytes, worst-case allowed archive expansion, finalize working
space, and a safety margin. Charge reservations and committed bytes against a
global intake quota and the applicable account/dataset quota; do not count the
same byte twice while a reservation becomes committed usage. Before each chunk
and finalize step, check the filesystem free-byte and free-inode reserves.
Refuse new writes with `507 Insufficient Storage` before either reserve is
crossed. Existing readable data is never automatically deleted to satisfy a
quota.

Avoid assembling a second copy when possible: stream committed chunks directly
into a new final file and remove chunks only after the final digest, receipt,
atomic promotion and reconciliation record are durable. ZIP expansion must
retain the existing path/link/type/count/ratio checks and apply declared and
actual expanded-byte limits while streaming. A quota or validation failure
leaves the session resumable or explicitly failed; it must not expose partial
files to the indexer.

Unfinalized sessions expire after an operator-configurable period (seven days
by default). A single-instance, lease-protected janitor first marks eligible
sessions `expired`, waits a recovery grace period, then removes only paths that
are both beneath the attested session root and owned by that session's manifest.
It records reclaimed bytes and an audit event. Finalized source data, receipts,
cataloged files and anything under an unknown directory are never janitor
targets. Operators get a dry-run/reconcile view in the Control Center.

### Authorization and security contract

Only maintainers, administrators and owners may create or modify sessions.
Every endpoint must repeat authentication, role authorization, same-origin and
CSRF checks; possession of a session ID alone grants nothing. Bind a session to
its creator and tenant, with explicit administrator takeover recorded in the
audit log. Use opaque IDs rather than source paths, reject user-controlled path
components, prohibit overwrites, cap concurrent sessions/chunks per principal
and IP, and rate-limit failed digest attempts. Do not log cookies, tokens,
chunk bodies or sensitive paths.

Treat client digests as claims. Verify each chunk on receipt and compute the
whole-file SHA-256 server-side during finalize. Preserve original bytes; MIME,
extension and TIFF decoding checks do not transform them. All results remain
`unverified`, maintainers-only and `unpublished` until the existing scientific
review and explicit publication gates succeed.

### Resumable-intake acceptance tests

- Interrupt a multi-file upload after arbitrary chunks, restart the gateway,
  reconnect from a fresh browser, and transfer only missing chunks.
- Retry a committed chunk and finalize request; prove byte-for-byte idempotence,
  one immutable release, one catalog source and one audit operation.
- Reject wrong ranges, sizes and hashes; overlapping/conflicting chunks; path
  traversal, links, encrypted or bomb archives; too many files; oversized TIFFs;
  unauthorized users; cross-user session IDs; CSRF; and concurrent finalize.
- Unmount CEDAR and place a writable local directory at the mount path; prove
  that creation, chunk upload and finalize all fail closed without writing to
  the VM root filesystem. Repeat for read-only, stale and full mounts.
- Exercise byte, inode, global, account, dataset and reserved-capacity limits,
  including two sessions racing for the last reservation. Verify `507` leaves
  existing data intact and releasing/cancelling a session returns its reserve.
- Kill the process immediately before and after chunk rename, database commit,
  final-file `fsync`, receipt write, release rename and catalog registration.
  Reconciliation must yield one explainable state with no published partials.
- Prove the janitor cannot follow links, leave the attested root, delete active
  sessions, or delete finalized/unknown directories; verify dry-run and audit
  totals before enabling deletion.
- Load-test at least 1 TiB total, 10,000 source files, concurrent curators, slow
  clients and proxy timeouts. Record throughput, p95 API latency, peak memory,
  peak temporary amplification, recovery time, CEDAR load and index duration.
- Back up the session database and manifests, restore them with finalized
  releases into an isolated environment, and demonstrate resume, reconciliation
  and rebuild of the catalog without publication-state escalation.

The one-command CryoStack backup treats the configured intake root as one
component and copies it under the same volume lock used by intake writers. It
includes open manifests/chunks, janitor audit records, receipts, and finalized
releases, and refuses links. `verify` and `drill` establish copy integrity;
they do not replace the required isolated resume/reconciliation/publication-
state rehearsal or authorize a production restore.

Navigation-only map coverage is configured independently from radar assets:

```text
CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS=/srv/cryostack/datasets
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_ROOT=/srv/cryostack/datasets/spri/navigation
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_FLIGHTS=125,126,127,128,137,138,139,141,143,149
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_DATASET=frozen-legacies-spri-navigation
CRYOSTACK_FROZEN_LEGACIES_NAVIGATION_TITLE=SPRI archival radar navigation
```

The navigation root must be beneath an approved storage root. With no
navigation root configured, the endpoint returns an empty optional collection
and the remainder of Frozen Legacies continues to operate. A misconfigured or
unavailable root is not allowed to prevent the static datasets from loading.

## RIGGS scientific-context intake

RIGGS stations are independent reference observations, not manual or
automatic Frozen Legacies picks. The layer stays hidden unless the operator
installs a CSV and a provenance manifest together on an approved storage root:

```text
CRYOSTACK_FROZEN_LEGACIES_RIGGS_CSV=/durable/reference/riggs_stations.csv
CRYOSTACK_FROZEN_LEGACIES_RIGGS_MANIFEST=/durable/reference/riggs.manifest.json
```

The CSV fields are `Station`, `Latitude`, `Longitude`, `h_i (radar), m`, and
`h_i (seismics), m`. Coordinates may be decimal degrees or degrees/minutes/
seconds with hemisphere letters. A station uses the seismic thickness when
present and otherwise the radar thickness, while preserving both original
values in its map properties.

The manifest is deliberately strict. Before the data owner supplies a citation,
an intake may set `"citation_pending": true` with both `citation` and
`source_url` empty. That state is visibly provisional and publication-ineligible;
partial provenance is rejected. Once known, replace it with the complete form:

```json
{
  "schema": "cryostack.frozen_legacies.riggs_manifest",
  "version": 1,
  "title": "RIGGS ice-thickness stations",
  "citation": "Full scientific citation supplied by the data owner",
  "source_url": "https://authoritative.example/dataset-record",
  "sha256": "sha256-of-the-exact-csv"
}
```

Both files must resolve inside `CRYOSTACK_FROZEN_LEGACIES_STORAGE_ROOTS`.
Checksum, schema, required fields, coordinate ranges, unique station IDs, and
positive thickness values are checked before any point is returned. Do not
transcribe points from a figure or generate substitute observations. The
current LYRA source bundle references `Data/RIGGS/riggs_stations.csv` but does
not contain that file, so production remains unconfigured until the data owner
provides and approves the actual table and citation.

## SPRI navigation intake (October 2026)

The received `RadarFilmStudio.zip` archive has SHA-256:

```text
177c92df4cc0f690db666217bb0c7982ebb419fe5bd1d6c1c385abcb23f7ab8d
```

It contains 61 CSV files with columns `CBD,LAT,LON,THK,SRF`. The first release
targets flights `125, 126, 127, 128, 137, 138, 139, 141, 143, 149`. All ten
tables have ordered, unique CBD values; valid Antarctic latitude/longitude;
and populated thickness and surface fields. The intake manifest records every
file's size, row count, columns, and SHA-256 digest.

Some tracks cross longitude ±180 degrees. CryoStack keeps the source positions
unchanged and splits only the GeoJSON display line at the antimeridian. The
split introduces interpolated boundary vertices for rendering; they are not
scientific observations.

## Associating TIFFs

Keep A-scope and Z-scope source imagery in separate durable subdirectories.
TIFF identity comes from flight and CBD range in its filename. A source's
navigation template associates the corresponding flight CSV during indexing.
Until imagery is present, navigation is validated intake material but is not a
radar asset and must be shown as `imagery unavailable`, not as a broken file.

Before promotion, verify each TIFF is a decodable, single-page 8- or 16-bit
grayscale image and compare its CBD range with the flight table. Preserve the
original TIFF; previews and PDFs are derived products and must record their
source digest and generator version.

## External transfer guidance

For an immediate, limited intake, use Dropbox Desktop on an operator machine
and transfer only approved flights to scratch with resumable `rsync`. Do not
place personal browser credentials on the VM. The production path should use
an institution-approved, read-only Dropbox service integration and copy into
CEDAR. Access tokens belong in the service secret store, never in a data-source
record, command history, manifest, or repository.

Maintain a free-space reserve on scratch and the VM. Transfers must fail before
crossing the configured reserve; deleting data automatically to make room is
not permitted.

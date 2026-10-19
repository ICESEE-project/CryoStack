# Frozen Legacies intake manifests

Frozen Legacies intake manifests describe a dataset before an operator makes
it visible through the catalog. They do not move files, publish data, or infer
scientific observations. The version-1 implementation is
`radar/intake_manifest.py`.

Each available item records a relative storage key, byte count, SHA-256,
provenance inherited from the dataset, an explicit scientific status, and its
relationship to other products. Supported roles cover source radar TIFFs,
radargrams, digitized radar, navigation, automatic-picker output, and PDF
display derivatives. Automatic output is always `unvalidated`.

An expected but absent product is represented by `availability: unavailable`,
`scientific_status: not-scientific`, and a reason. Such a placeholder cannot
carry a storage key, byte count, or digest and is never offered to the catalog
indexer. It must not be replaced with generated coordinates, picks,
calibration observations, or other substitute scientific data.

## Indexer integration contract

1. Parse JSON and call `validate_manifest` before reading any object.
2. Load the run-specific checkpoint with `read_checkpoint`.
3. Inspect `duplicate_items`. Repeated storage keys are rejected; equal
   size/SHA-256 declarations are reported for operator review because a
   byte-identical archival copy can be intentional.
4. Submit `pending_items` to the existing catalog indexer in bounded batches.
5. Complete the catalog database transaction for one item or batch.
6. Only then call `complete_item` and `write_checkpoint`. The checkpoint write
   is atomic.
7. On a failed item, call `fail_item` and atomically write the checkpoint. The
   bounded failure record contains its declaration fingerprint, attempt count,
   time, and a path-scrubbed error; it never marks the item complete.
8. On interruption, repeat from step 2. An item is skipped only when its
   canonical declaration has the same fingerprint. Changed content or
   metadata is therefore reconsidered without duplicating unchanged work.
9. Finish the existing catalog `index_run` only after every pending item has
   succeeded. Missing detection remains the catalog's responsibility and must
   retain its mass-missing safeguards.

The checkpoint is an advisory restart hook, not the authoritative catalog.
Its directory must be on configured durable application storage when this
contract is wired to a production provider. This milestone does not configure
CEDAR, copy production data, or deploy an intake worker.

For unusually large sources, set positive `max_index_objects` and/or
`max_index_bytes` in the source's non-secret configuration. Crossing a bound
ends the run as `needs_confirmation`, retains its committed batches, and does
not mark unseen files missing. Indexing checks cancellation after every listed
object, limits in-flight header work to 500 objects, and retains navigation
metadata for at most 128 flights. Retrying is idempotent because unchanged
catalog objects are skipped.

## Relationship examples

- A `digitized-radar` item uses `digitizes` to name its `raw-tiff`.
- An `automatic-output` item uses `derived-from` to name the source TIFF or
  digitized product and remains scientifically unvalidated.
- A `radargram` or `preview-pdf` may use `visualizes` or `derived-from` while
  remaining a derivative rather than replacing the scientific source.
- Navigation may use `navigation-for` to identify the imagery it locates.

Relationship targets must exist in the same manifest. The validator rejects
path traversal, duplicate IDs, dangling/self relationships, invalid digests,
automatic output presented as validated source data, and placeholders that
claim file identity.

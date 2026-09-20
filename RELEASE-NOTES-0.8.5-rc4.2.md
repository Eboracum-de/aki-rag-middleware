# AKI RAG Middleware 0.8.5-rc4.2

**Release date:** 20 September 2026

## Scope

`0.8.5-rc4.2` is a narrow post-review hotfix on top of `0.8.5-rc4.1`. It does not change retrieval architecture, source-scope semantics, Qdrant data formats, Mail sync state, or the public authorization model.

## Fixes

### Complete Neo4j recovery after deferred startup initialization

If Neo4j is unavailable while the API starts, schema initialization is deliberately deferred so the optional/degradable graph backend does not prevent the API from starting. RC4.1 retried only the ResearchFinding schema subset when Neo4j later became reachable through the Research Findings endpoint.

RC4.2 retries the full idempotent `GraphStore.ensure_schema()` upgrade before marking the runtime schema as ready. Base constraints/indexes, entity-kind backfills, historic decision backfills and ResearchFinding schema upgrades therefore recover together.

### Preserve app-password revocation after credential decryption failures

Temporary self-service Findings-curation sessions use short-lived Nextcloud app passwords encrypted in `runtime/users.sqlite`. RC4.1 kept API startup alive when one such row could not be decrypted, but deleted the local row.

A decryption failure can also be caused by a temporarily wrong or restored master key. Deleting the row would destroy the information needed to revoke the still-valid Nextcloud app password later. RC4.2 instead marks the row `revocation_pending`, keeps it locally unusable, and retries decryption/revocation on a later startup. Successful revocation still deletes the row normally.

## Validation

Private development CI for the RC4.2 code baseline completed successfully on Python 3.13:

- **452 tests passed**
- Python compile check passed
- shipped shell-script syntax check passed

The two new regression cases cover full Neo4j schema recovery and recovery of pending curation-session revocation after the correct master key is restored.

## Upgrade notes

RC4.2 is intended as a drop-in hotfix for RC4/RC4.1 installations. There is no Qdrant reindex requirement and no Mail sync-state reset caused by these fixes. Existing installer rerun safeguards and schema migrations remain applicable; as usual, preserve deployment state and credentials before an upgrade.

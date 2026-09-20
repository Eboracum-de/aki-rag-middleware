# AKI RAG Middleware 0.8.5-rc4.1

**Release date:** 2026-09-20  
**Status:** public beta / hotfix release candidate  
**License:** GNU AGPL-3.0-only

`0.8.5-rc4.1` is a conservative security, correctness and operational hotfix on top of `0.8.5-rc4`. It does not introduce a new retrieval architecture or new end-user features.

## Security and authorization hardening

- Self-service Finding curation now fails closed when live Nextcloud ACL is disabled or does not return an enabled authorization decision. Unfiltered Findings are never treated as authorized evidence.
- The standard installer no longer sources `install/install-state.env` as shell code. An existing prefix is validated first and only allowlisted state keys with validated values are parsed as data.
- Admin and self-service Finding guards no longer depend on a global newest-2,000 Findings window. Bulk admin actions batch their visibility check rather than repeating a global list plus live ACL request for each selected Finding.

## Stability and correctness

- Super-Light can place the bundled nginx on alternate host ports with `--proxy-http-port` / `--proxy-https-port`, allowing Nextcloud/Apache to retain public 80/443 on a shared host while proxying only the RAG path prefixes.
- ResearchRun reconstruction loads the exact Findings referenced by each run, so older runs do not disappear merely because the installation contains more than 2,000 Findings.
- Startup cleanup isolates undecryptable ephemeral curation-session rows. An unusable temporary secret no longer prevents the whole API from starting.
- Nextcloud Login Flow, credential revocation and self-service live-ACL work no longer block the FastAPI event loop.
- The optional graph-evidence enqueue hook no longer references an undefined `source_scopes` variable.
- Super-Light waits for Neo4j to become schema-ready and retries the idempotent initialization instead of failing on an early incomplete Bolt handshake during container startup.
- Super-Light preserves existing admin credentials on rerun, persists regenerated runtime secrets when a legacy key is missing, and uses the configured `RAG_ADMIN_USER` consistently for nginx Basic Auth.

## Neo4j schema consolidation

- `docs/NEO4J-SCHEMA.md` is the canonical internal application-schema reference.
- Optional Neo4j properties are read in a warning-safe form instead of relying on synthetic property-token marker nodes.
- Missing constraints/indexes and deterministic compatibility backfills are applied idempotently.
- Standard and Super-Light installer reruns apply the schema upgrade to an existing Neo4j store; API startup also attempts the non-destructive upgrade for independently managed deployments.
- Existing graph data is not intentionally deleted or reclassified by this migration.
- Sparse optional relationship reads use `type(r)` guards, avoiding `UnknownRelationshipTypeWarning` noise when relationships such as `MENTIONS_NAME` or `MERGED_INTO` have never been created.

## Validation

The private hotfix branch passed the complete automated regression suite after the functional fixes:

- **450 tests passed**
- Python compile check passed
- shell syntax checks passed

The Super-Light rerun was field-tested against an existing RC4 installation and its existing Neo4j store. The installer waited through the initial Bolt startup race, completed the idempotent schema upgrade, and the subsequent Admin/diagnostic paths no longer emitted the prior `UnknownPropertyKeyWarning` or sparse `UnknownRelationshipTypeWarning` noise.

## Upgrade scope

This hotfix is intended as an in-place update from `0.8.5-rc4`. Use the normal installer rerun path with the same deployment profile/options used for the existing installation. The installer must preserve the existing application data and add only the required non-destructive schema/runtime fixes.

The larger RC5 work remains separate: prompt internationalization, optional ACL-aware retrieval prefiltering, extracted-content hash deduplication, dependency hardening and broader structural cleanup are not part of this hotfix.

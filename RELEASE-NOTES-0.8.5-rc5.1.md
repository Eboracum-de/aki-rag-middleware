# AKI RAG Middleware 0.8.5-rc5.1

**Date:** 22 September 2026  
**Status:** post-RC5 public-beta maintenance release

## Purpose

`0.8.5-rc5.1` is a deliberately small follow-up to the validated `0.8.5-rc5` baseline. It does not change AKI's retrieval architecture, live-ACL authorization boundary or deployment profiles.

The release focuses on clearer project positioning and one bounded Super-Light backup/inventory correction.

## Existing-estate positioning

The README now presents AKI as an **AI gateway for existing Nextcloud deployments**:

> **Keep your Nextcloud. Add modern AI around it.**

The deployment model is stated more directly:

- keep Nextcloud as the document store and authorization authority;
- reuse an existing FullTextSearch / Elasticsearch estate;
- do not require document migration into a separate AI knowledge base;
- do not require full-corpus vectorization for the Super-Light path;
- add Qdrant, reranking and Graph-Lite only where they provide value.

For installations where the required Nextcloud, Elasticsearch and model endpoints already exist, a typical Super-Light installation can be up and running in under 10 minutes. This is an operational observation, not an installation-time guarantee; network speed, host performance, package/image downloads and site-specific configuration affect the actual duration.

## Super-Light backup CA path normalization

Dockerized Super-Light configurations may refer to bundled CA files by their container-visible path, for example:

```text
/app/runtime/ca/nextcloud-ca-bundle.pem
```

Backup inventory runs against the host installation tree. `0.8.5-rc5.1` maps that known `/app/runtime/ca/...` alias back to an existing host `runtime/ca/...` file and therefore no longer reports the bundled CA as an external operator-owned dependency.

The mapping is deliberately narrow:

- only the known `/app/runtime/ca/...` alias is handled;
- the mapped file must exist below the AKI installation root;
- path resolution must remain inside that root;
- genuinely external absolute CA paths remain external and are still reported to the operator.

A regression test covers the Super-Light container-path case.

## RC5 review hardening

A full static/security review of the complete `0.8.5-rc4.3` → `0.8.5-rc5` public delta identified several bounded follow-up issues. `0.8.5-rc5.1` includes the validated fixes rather than changing the broader RC5 architecture:

- Finding cleanup re-checks curator status, suppression state, curated-entity links, relation-observation references and remaining ResearchRun provenance inside the actual Neo4j write statements, closing the read/write race window.
- A resolved conversation reset boundary suppresses history-aware query rewriting, including natural-language control workflows.
- The bundled nginx maintenance fallback intercepts only 502/504 connectivity failures; a genuine 503 from a running Admin API remains visible as the upstream service response.
- Best-effort AKI Recherche chat-archive provenance registration uses a short timeout so a completed chat answer is not held for a long failing side request.
- Damaged chat metadata no longer prevents deletion of the fixed archive files.
- Damaged chat metadata also no longer blocks saving a repaired conversation; rename returns a controlled client error when the stored record itself is unreadable.
- Chat-archive provenance registration is now user-scoped end to end: the Nextcloud app forwards the current UID, the provider propagates it to the middleware, and the middleware requires live Nextcloud ACL authorization for the exact `files:<id>` before changing source-origin metadata. Registration remains best-effort and fails closed if live ACL is unavailable.
- The archive path itself is also server-derived: AKI resolves the visible file through the same authenticated Nextcloud WebDAV SEARCH, requires the canonical user-relative path to be below the configured chat-archive root and to match the submitted path, and persists only that canonical path.
- If chat metadata is damaged, save/delete may recover the existing managed Markdown archive by its unique chat-ID filename suffix. Ambiguous matches are deliberately left unresolved instead of guessing.
- ACL duplicate promotion now clears identity, ownership, path and source metadata inherited from an unauthorized ranked representative before copying the authorized duplicate. Legacy duplicate records with only a file ID receive a canonical `files:<id>` document identifier.
- The AKI Recherche documentation is aligned with app version 0.2.6 and Markdown chat archives.
- Elasticsearch filename lookup now has behavioral regression coverage for requesting and mapping the Nextcloud document hash used by duplicate detection.

## Scope and compatibility

The RC5 architecture and security model remain unchanged:

- Nextcloud remains the final authorization authority for private document evidence;
- live WebDAV ACL remains mandatory before private document text reaches verifier or answer roles;
- Super-Light may remain Elasticsearch-centric without Qdrant;
- existing configuration and deployment profiles remain valid;
- the bundled Super-Light compose file tags the locally built AKI image as `aki-rag:0.8.5-rc5.1`, avoiding accidental reuse of an older RC4.3 image after a source update;
- no schema migration or new mandatory configuration key is introduced by this release.

The roadmap was also cleaned up to remove items that are already implemented in the current UI or by the CA-path correction.

## Deliberately deferred

Direct `/use` document selection remains independent of Research-Finding enrichment in `0.8.5-rc5.1`.

A correct implementation must create a semantically valid structured QueryFrame and run Candidate-Verifier-derived enrichment as a side pipeline without changing the direct answer path. The release does not fabricate curation metadata merely to satisfy the earlier target version.

Larger Docker-secret, schema, platform-abstraction and model-profile work also remains outside this maintenance release.

## Validation

The pre-finalization `0.8.5-rc5.1` development tree passed:

- Python compile checks;
- shipped shell syntax checks;
- **553 automated tests**.

The exact public release delta should be reviewed again before merge.

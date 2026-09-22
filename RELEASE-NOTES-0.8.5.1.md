# AKI RAG Middleware 0.8.5.1

**Date:** 22 September 2026  
**Status:** post-RC5 public-beta maintenance release

## Purpose

`0.8.5.1` is a deliberately small follow-up to the validated `0.8.5-rc5` baseline. It does not change AKI's retrieval architecture, live-ACL authorization boundary or deployment profiles.

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

Backup inventory runs against the host installation tree. `0.8.5.1` maps that known `/app/runtime/ca/...` alias back to an existing host `runtime/ca/...` file and therefore no longer reports the bundled CA as an external operator-owned dependency.

The mapping is deliberately narrow:

- only the known `/app/runtime/ca/...` alias is handled;
- the mapped file must exist below the AKI installation root;
- path resolution must remain inside that root;
- genuinely external absolute CA paths remain external and are still reported to the operator.

A regression test covers the Super-Light container-path case.

## Scope and compatibility

The RC5 architecture and security model remain unchanged:

- Nextcloud remains the final authorization authority for private document evidence;
- live WebDAV ACL remains mandatory before private document text reaches verifier or answer roles;
- Super-Light may remain Elasticsearch-centric without Qdrant;
- existing configuration and deployment profiles remain valid;
- no schema migration or new mandatory configuration key is introduced by this release.

The roadmap was also cleaned up to remove items that are already implemented in the current UI or by the CA-path correction.

## Deliberately deferred

Direct `/use` document selection remains independent of Research-Finding enrichment in `0.8.5.1`.

A correct implementation must create a semantically valid structured QueryFrame and run Candidate-Verifier-derived enrichment as a side pipeline without changing the direct answer path. The release does not fabricate curation metadata merely to satisfy the earlier target version.

Larger Docker-secret, schema, platform-abstraction and model-profile work also remains outside this maintenance release.

## Validation

The pre-finalization `0.8.5.1` development tree passed:

- Python compile checks;
- shipped shell syntax checks;
- **542 automated tests**.

The exact public release delta should be reviewed again before merge.

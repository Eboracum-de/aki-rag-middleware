# AKI RAG Middleware 0.8.5-rc3

**Release date:** 2026-09-17  
**Status:** first public release candidate / public beta  
**License:** GNU AGPL-3.0-only

`0.8.5-rc3` is the first release intended for publication in the public upstream repository. Earlier RC and Graph-Lite draft identifiers were internal development baselines.

## What this release is for

The release is aimed at organizations that already have a Nextcloud document estate and want RAG/research functionality without replacing Nextcloud as the document store or authorization authority.

The most field-tested path is **Super-Light + Docker**, reusing Nextcloud FullTextSearch / Elasticsearch and an external or local OpenAI-compatible LLM. The same codebase can scale to Qdrant, reranking and richer Neo4j/Graph-Lite workflows.

## Highlights

- live Nextcloud ACL verification before private document evidence reaches verifier/answer roles;
- source scopes for normal documents, mail archive, web archive and saved chats, plus separate live web research;
- UI-independent OpenAI-compatible provider interface with bundled AKI Recherche and support for external clients such as OpenWebUI;
- Super-Light deployment without mandatory Qdrant or local reranker;
- optional Qdrant semantic retrieval, reranker and Neo4j/Graph-Lite expansion;
- per-user Nextcloud Login Flow / app-password identity binding and encrypted credential storage;
- IMAP mail import with provenance metadata and attachments;
- web research with text evidence first and background Playwright PDF rendering;
- curated Research Findings / Graph-Lite administration with entity grouping and bulk decisions;
- conservative completeness handling for explicit list/all-document requests;
- local/remote LLM roles with explicit disclosure budgets.

## RC3-specific fixes over the internal RC2/Graph-Lite drafts

- open Findings remain the default curation view;
- entity-grouped checkbox/bulk curation and one-action suppression of findings without entities;
- durable manually curated mentions and claims across later graph re-indexing;
- dependent claims become `review_required` when a curated entity is changed;
- ResearchFinding claim evidence prefers the persisted EvidenceFrame over the query intent;
- Admin bulk-selection JavaScript moved to a CSP-compliant external asset;
- inline Admin event handlers removed; CSP permits scripts only from `self`;
- bulk curation now reports complete failure and partial-failure counts instead of silently looking successful;
- public repository/community documentation, contribution process and CLA added.

## Tested/reference baseline

- AKI Recherche target: Nextcloud 23+
- legacy acceptance host: openSUSE Leap 15.3
- Super-Light: Dockerized API/provider/Graph-Lite/Playwright with external Nextcloud, Elasticsearch and LLM
- regression-tested mappings: `super-light + dockerized` and `standard + native`

Resource figures in `README.md` are observed acceptance points, not guaranteed hard limits.

## Known limitations

This is a release candidate. Admin/Graph-Lite workflows remain deliberately conservative and still have usability work ahead. Full graph extraction is optional and can be compute-intensive. Web PDF rendering is best-effort and its background queue is not durable across API restarts. Mail backfill cutoff expansion still needs manual state handling in the current release.

See `docs/KNOWN-LIMITATIONS.md` before production deployment.

## Licensing and contributions

The public project is AGPL-3.0-only. Eboracum GmbH retains the option to offer separately negotiated commercial licenses. Accepted third-party contributions remain publicly available under AGPL-3.0-only; contributors retain ownership and grant the additional rights described in `CLA.md` only when a CLA is required and accepted.

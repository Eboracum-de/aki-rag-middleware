# AKI RAG Middleware

**Privacy-oriented RAG middleware for existing Nextcloud deployments — from legacy-friendly Elasticsearch-only retrieval to hybrid vector and graph-assisted research.**

[![License: AGPL-3.0-only](https://img.shields.io/badge/License-AGPL--3.0--only-blue.svg)](LICENSE)
[![Status: Release Candidate](https://img.shields.io/badge/status-release%20candidate-orange.svg)](CHANGELOG.md)

AKI RAG Middleware connects natural-language research to an existing Nextcloud document estate without replacing Nextcloud as the document store or authorization authority. It combines Nextcloud FullTextSearch / Elasticsearch with optional semantic retrieval, graph signals, mail ingestion, web research and archived chats behind an OpenAI-compatible provider interface.

The central security invariant is deliberately simple:

> **Retrieval systems propose candidates. Nextcloud remains the final authorization authority.**

Every document candidate is checked live against Nextcloud for the authenticated user before it can become answer evidence. If an otherwise relevant document is not authorized, it is removed rather than replaced by a weaker result merely to fill the context window.

> **Project status:** `0.8.5-rc4` — public-beta release candidate. RC4 consolidates user-scoped Findings/Graph-Lite hardening, self-service curation, installer rerun safeguards and the latest field-test fixes. The Super-Light deployment path remains the primary field-tested profile; see `docs/KNOWN-LIMITATIONS.md`.

## Why this project exists

Many organizations have useful document archives that predate modern AI stacks. Replacing those systems is often unnecessary, expensive or undesirable. AKI RAG is designed to add research capabilities around an existing Nextcloud installation while keeping operational complexity and external data exposure under administrator control.

The project focuses on six practical goals:

- **Legacy-friendly deployment.** The Super-Light profile reuses an existing Nextcloud FullTextSearch / Elasticsearch index and is tested on an openSUSE Leap 15.3 host. The bundled AKI Recherche UI targets Nextcloud 23+.
- **UI agnostic.** The middleware exposes an OpenAI-compatible provider path. The included AKI Recherche app is a slim Nextcloud-native UI; external OpenWebUI deployments can use the same middleware.
- **Small local footprint.** Super-Light runs without Qdrant and without a local reranker. On the current acceptance VM, the local middleware services used about **1.7 GiB RAM at idle** while Nextcloud, Elasticsearch and the LLM were external. This is an observed test point, not a guaranteed ceiling; 4 GiB remains the practical VM minimum when Chromium-based web archiving is enabled.
- **Integrated research sources.** Ordinary documents, imported mail, archived web evidence and saved AKI chats are distinct source scopes. Live public-web research remains a separate evidence arm.
- **Scale up without changing the core.** The same codebase can add Qdrant semantic retrieval, a reranker and richer Neo4j/Graph-Lite functionality when resources and use cases justify them.
- **Data minimization by design.** Retrieval, indexing, embeddings and ACL checks can remain local. LLM roles are independently configurable and may be local or remote. A fully local deployment is possible when local model and web-search choices are used.

## Architecture at a glance

```text
                  AKI Recherche / OpenWebUI / API client
                                |
                       OpenAI-compatible provider
                                |
                     Query rewrite / SearchSpec
                                |
                +---------------+---------------+
                |                               |
        internal document path              live web path
                |                               |
       Neo4j seed/alias context           search provider
                |                               |
       +--------+---------+               fetch + relevance
       |                  |                    gate
 Elasticsearch         Qdrant                   |
  required arm         optional                 |
       +--------+---------+                     |
                |                               |
          fusion / dedup                        |
                |                               |
        optional reranker                       |
                |                               |
        LIVE NEXTCLOUD ACL                      |
                |                               |
       optional verifier                        |
                +---------------+---------------+
                                |
                         answer model
                                |
                  sources + optional archives
```

Elasticsearch, Qdrant and Neo4j are retrieval systems, not authorization systems. The live Nextcloud ACL check is intentionally downstream of candidate retrieval and upstream of document evidence sent to verifier or answer roles.

## Deployment profiles

| Profile | Intended use | Local components | External dependencies |
| --- | --- | --- | --- |
| **Super-Light** | legacy/smaller servers, first deployment | API, provider, Neo4j Graph-Lite, Playwright; optional nginx | Nextcloud, FullTextSearch/Elasticsearch, LLM |
| **Standard** | larger/hybrid retrieval installations | native middleware plus optional Qdrant, reranker, Neo4j, OpenWebUI | Nextcloud, Elasticsearch; model backends as configured |

For the current 0.8.5 release-candidate line, the regression-tested deployment mappings are:

- `super-light + dockerized`
- `standard + native`

Super-Light is a profile of the same middleware, not a separate fork.

## Research sources

The middleware keeps source selection separate from retrieval-engine selection.

- `/documents` — ordinary Nextcloud documents
- `/mailarchive` — imported mail and attachments
- `/webarchive` — archived web-research evidence
- `/chatarchive` — saved AKI conversations
- live `/web` research — current public web evidence, separately fetched and checked

Archive origins are tracked by stable Nextcloud file IDs and mirrored into retrieval indexes so source scopes can be applied before candidate limits.

Archive scopes are optional. In particular, saved chats are useful as shared/flat-hierarchy working memory, but they are deliberate retained copies: a saved conversation can contain text derived from another document and then has its own Nextcloud file ID, ACL and lifecycle. Deployments that require revocation of an original document to remove every conversational copy should leave `/chatarchive` disabled or define a matching retention/purge process.

## Privacy and trust boundaries

A private document corpus does not need to be exposed wholesale to an external LLM provider. In the reference architecture:

- Nextcloud/Elasticsearch retrieval stays inside the administrator-controlled environment.
- Qdrant and embeddings may remain local.
- ACL authorization is checked live against Nextcloud.
- planner, verifier, evidence-control and answer roles are independently configurable.
- remote roles have bounded document/count/character budgets.
- full-document graph extraction is a separate opt-in trust decision and is disabled by default in the reference configuration.

Those controls reduce disclosure; they do not make remotely transmitted evidence non-sensitive. Administrators remain responsible for deciding which roles may use remote model providers.

AKI also distinguishes **shared retrieval knowledge** from **document evidence**. Curated names/aliases and shared Finding decisions may be reused across users so that the organization benefits from prior curation. That reuse does not grant access to the document that originally motivated the knowledge: document text still needs the current user's live Nextcloud authorization before it becomes answer evidence.

See `docs/PRIVACY-ARCHITECTURE.md`, `docs/THREAT-MODEL.md` and `SECURITY.md` for details.

## Compatibility and tested baseline

The project intentionally keeps support for older installations in scope rather than requiring a current Linux/Python stack everywhere.

Current public-beta reference points:

- **AKI Recherche:** Nextcloud 23+
- **Super-Light acceptance host:** openSUSE Leap 15.3
- **Document retrieval:** existing Nextcloud FullTextSearch / Elasticsearch
- **Internal PKI:** supported, including compatibility mode for older private certificate chains without disabling ordinary TLS verification
- **Answer provider:** OpenAI-compatible; local and remote model roles are independently configurable

Compatibility statements describe the current tested/project target, not a promise that every combination of Nextcloud, Elasticsearch, proxy and model backend is regression-tested.

For current Nextcloud deployments, the native baseline to evaluate is Nextcloud Context Chat. AKI is not intended to out-feature that supported ecosystem; it addresses a different operating model: reuse of an existing FullTextSearch estate, a replaceable OpenAI-compatible provider boundary, optional Graph-Lite and live Nextcloud authorization of concrete document candidates. See `docs/NEXTCLOUD-CONTEXT-CHAT.md` for the neutral comparison and current caveats.

## Quick start: Super-Light

Inspect the installation plan before changing the host:

```bash
sudo ./install/install.sh \
  --profile super-light \
  --deployment dockerized \
  --nextcloud-url https://cloud.example.org/nextcloud \
  --elasticsearch-url http://10.0.0.20:9200 \
  --elasticsearch-index my_index \
  --plan
```

Then install with the same arguments, removing `--plan` and adding the components you want. For an internal PKI, use repeatable `--ca-certificate FILE` arguments rather than disabling TLS verification.

Detailed installation and acceptance steps are in `install/INSTALL.md` and `docs/BETA-OPERATIONS.md`.

## Front ends

### AKI Recherche

The included `clients/nextcloud/akirag/` app is a slim Nextcloud-native research UI. It targets Nextcloud 23+, proxies server-side to the middleware, keeps the provider key out of browser JavaScript and stores saved conversations per user in Nextcloud.

### OpenWebUI

OpenWebUI can be used as an external client through the provider interface. The middleware does not depend on OpenWebUI-specific retrieval or knowledge features.

The same OpenAI-compatible boundary can be used by other local frontends, RAG systems, agents or research tools when an administrator deliberately registers them as trusted clients. A trusted-client key is an integration-server credential: keep it server-side and restrict externally reachable provider endpoints by network policy/reverse-proxy allowlists or equivalent controls where practical.

The API/provider boundary is intentional: front-end choice should not define the retrieval architecture.

## Optional scale-up path

A Super-Light deployment can remain Elasticsearch-centric indefinitely. Where the workload justifies it, the same middleware can add:

- **Qdrant** for semantic/vector retrieval,
- a **cross-encoder reranker**,
- **Neo4j** beyond seed/alias expansion,
- curated **Graph-Lite** entities, mentions and relation observations,
- local model services for a completely self-hosted processing path.

The graph layer is deliberately conservative: retrieved or LLM-derived observations are not automatically promoted to global facts merely because they were extracted.

## Documentation

- `install/INSTALL.md` — fresh-machine installation
- `docs/BETA-OPERATIONS.md` — beta runbook and acceptance checklist
- `docs/ARCHITECTURE.md` — architecture and trust model
- `docs/PRIVACY-ARCHITECTURE.md` — local/remote processing boundaries
- `docs/THREAT-MODEL.md` — adversaries, shared retrieval knowledge, ACL and archive boundaries
- `docs/DATA-LIFECYCLE.md` — deletion, backup/restore and derived-store lifecycle
- `docs/NEXTCLOUD-CONTEXT-CHAT.md` — relationship to Nextcloud's native Context Chat architecture
- `docs/TECHNICAL-REFERENCE.md` — detailed configuration and APIs
- `docs/ADMINISTRATION.md` — user, credential, mail, web and graph administration
- `docs/GRAPHLIGHT-FINDINGS.md` — Findings curation and Graph-Lite safety boundary
- `docs/KNOWN-LIMITATIONS.md` — known limitations and deferred polish
- `docs/ROADMAP.md` — explicitly deferred RC5 / 0.8.6 work
- `docs/DEVELOPMENT.md` — repository layout and test baseline
- `SECURITY.md` — security model and vulnerability reporting
- `CONTRIBUTING.md` — contribution and licensing policy
- `CLA.md` / `docs/CLA-PROCESS.md` — contributor rights without copyright assignment
- `CODE_OF_CONDUCT.md` — community conduct expectations
- `RELEASE-NOTES-0.8.5-rc4.md` — current release notes
- `RELEASE-NOTES-0.8.5-rc3.md` — first public release notes

## Development and tests

```bash
python -m pytest
```

Before a release candidate is tagged, the project also performs syntax/configuration checks, blank-VM installation/acceptance for the intended profile, manifest regeneration and a final scan for runtime state and secrets.

Runtime databases, environment secrets, TLS material and local deployment state must never be committed.

## License and commercial licensing

The public source is licensed under **GNU AGPL-3.0-only** unless a file states otherwise. See `LICENSE` and `COPYRIGHT`.

Eboracum GmbH intends to preserve the option of offering the same code under separate commercial/proprietary terms for organizations that require an alternative license. This does **not** withdraw or reduce the rights already granted for AGPL releases.

Because dual licensing requires a clean rights chain, non-trivial copyrightable contributions require the project CLA before merge. **Contributors retain ownership**; the CLA is an additional non-exclusive grant and commits accepted contributions to continued public AGPL availability.

See `CONTRIBUTING.md`, `CLA.md` and `COMMERCIAL-LICENSING.md`.

## Project status and maintenance

This is a small maintainer-led project. Public release does not imply an SLA or guaranteed support lifetime.

If active development ends, the preferred lifecycle is to mark the project as maintained only for critical fixes and eventually archive the repository rather than erase the public history. Forks remain part of the freedoms provided by the AGPL.

See `docs/PROJECT-GOVERNANCE.md`.

## Trademark notice

AKI RAG Middleware is an independent project and is not affiliated with or endorsed by Nextcloud GmbH. “Nextcloud” is used descriptively to identify compatibility with the Nextcloud software platform. Nextcloud and related marks are trademarks of Nextcloud GmbH.

See `TRADEMARKS.md`.

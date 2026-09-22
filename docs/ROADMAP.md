# Roadmap

This file records implemented RC5 direction together with follow-up work that is intentionally deferred beyond the current `0.8.5-rc5` release-candidate baseline.

## Deferred operational/security polish

The following items are deliberately deferred because they do not block the validated RC5 deployment paths:

- reduce plaintext global-secret exposure in Dockerized/Super-Light operation: migrate suitable API keys/passwords from Compose environment materialization to Docker secrets or file-mounted credentials where practical, avoid support workflows that render full Compose configuration, and document Docker-daemon/group access as a privileged/root-equivalent boundary. This hardening can reduce accidental disclosure through `docker-compose config`/inspection but is not intended to protect secrets from a Docker administrator;
- normalize container-visible `/app/...` configuration paths back to their host installation equivalents in the backup inventory where the mapping is unambiguous, so bundled Super-Light CA files do not produce a misleading external-path warning even though `runtime/ca/` is already included;
- pin the Microsoft Playwright base image by immutable digest in addition to the existing version tag/package pins;
- make the Standard `--plan` wording distinguish a fresh Playwright default-off install from a rerun that preserves an existing `web.yaml` choice;
- bound each Neo4j schema-readiness attempt so periodic installer progress output cannot be delayed by one long connection attempt;
- reduce synchronous WebDAV archive latency, preferably with bounded parallel writes / fewer file-ID `PROPFIND` round trips while preserving immediate `/use:Wn` and answer-finalization semantics.

## 0.8.5-rc5 delivered items

### Optional ACL-aware retrieval prefilter

RC5 introduces a deliberately conservative **opt-in** prefilter before candidate limits/reranking. It is configured under `acl.prefilter.enabled` and remains off by default.

The first implementation uses only the Nextcloud FullTextSearch metadata `owner`, `users` and `groups` in Elasticsearch; the same fields are already preserved in Qdrant payloads. The bundled AKI Recherche frontend derives the user's Nextcloud groups server-side from the authenticated Nextcloud session and forwards them only as a retrieval hint. The middleware derives the actual Nextcloud login from the stored live-ACL credential rather than trusting the frontend user header.

RC5 v1 intentionally does **not** evaluate Circles. Deployments that rely on Circle-only shares should leave the prefilter disabled until Circle membership is implemented. If a trusted frontend does not provide usable Nextcloud group context, the middleware skips prefiltering for that request and falls back to the established unfiltered retrieval path.

Security/behavioral constraints:

- live WebDAV ACL remains the mandatory final authorization boundary;
- stale or forged indexed ACL metadata can affect recall/ranking but cannot grant document access;
- no adaptive backfill is added after final live-ACL denials;
- Graph retrieval remains unprefiltered in v1 and is still subject to final live ACL;
- the prefilter may be disabled globally at any time without changing authorization semantics.

### Exact extracted-content duplicate detection — implemented in RC5

RC5 reads Nextcloud FullTextSearch's document `hash` as the primary exact duplicate signal where available. In the current Nextcloud FullTextSearch implementation this is an MD5 of the **extracted indexed content**, not a raw-file byte hash, so AKI treats only a valid 32-hex value as an *exact extracted-content duplicate* signal.

Duplicate grouping retains every distinct Nextcloud file ID in `duplicate_variants`. Live ACL checks the ranked representative **and each retained variant**. If the representative is denied but an identical copy is authorized, the authorized copy is promoted and denied metadata/snippets are discarded. Near-text/OCR and same-stem format-variant detection remain separate secondary signals.

A later statistics cleanup may use distinct extracted-content hashes rather than distinct file IDs for independent-source counts where that semantic is appropriate.

### Dependency hardening and Transformers 5 evaluation

Keep `transformers==4.57.6` as the RC4 baseline for now. Dependabot's direct 5.10.1 bump is not mergeable as-is because Transformers 5.10.1 requires `huggingface-hub>=1.5,<2`, while the current baseline intentionally pins `huggingface-hub>=0.24,<1`.

For RC5:

- test a coordinated Transformers 5.x + Hugging Face Hub 1.x upgrade on a dedicated branch rather than accepting an isolated major bump;
- run the full regression suite plus a real local reranker smoke test with the configured cross-encoder model before changing the baseline;
- document/automate reachability triage for dependency advisories: distinguish vulnerable APIs from actually exercised AKI paths, especially where the local reranker only imports `AutoTokenizer` and `AutoModelForSequenceClassification` with `local_files_only=True`;
- split optional heavyweight ML dependencies from the core/server dependency set where practical (for example core vs. local-reranker requirements), so TEI/Super-Light deployments do not install Transformers merely because another profile can use it;
- keep Dependabot major-version updates non-automatic; security updates within the supported major line should still be reviewed promptly.

### Backup / restore and credential-key lifecycle

RC5 now provides the console-first `install/backup-restore.sh` workflow:

- `create TARGET`: requires maintenance mode, checkpoints/integrity-checks AKI SQLite state, creates a timestamped recovery set and verifies it before publishing;
- `verify BACKUP`: verifies SHA-256 checksums, SQLite integrity and credential decryption with the included master key;
- `restore BACKUP --yes`: requires maintenance mode and explicit confirmation, verifies first, restores only the AKI-owned state described by the recovery format and leaves the service in maintenance mode afterwards.

The first recovery format includes configuration/runtime state,
`runtime/users.sqlite`, the matching credential master key, relevant AKI SQLite
state, private CA/TLS/operator state below the installation prefix and bundled
Neo4j when selected. Qdrant remains deliberately rebuildable and is not included
in v1. Nextcloud/Elasticsearch remain outside AKI backup ownership, and external
Neo4j requires its own operator-managed backup.

Restore is intentionally conservative: the same supported deployment
profile/mode and installation prefix are required. Version drift is warned about
and the operator must complete smoke/schema/ACL checks before leaving maintenance
mode.

`credential-key rotate` remains a follow-up. It should require maintenance,
create a recovery copy of `users.sqlite` plus the old key, re-encrypt every
reversible secret with a new key, verify every row and only then commit the new
key.

### Lazy ACL cleanup for uncurated Findings

RC5 now implements the first narrow cross-store lifecycle step without introducing a background purge worker. The Finding live-ACL checks in RAG Admin and `/curation/` self-clean stale **uncurated** user provenance after a successful definitive denial of a numeric Nextcloud file.

The implementation deliberately:

- removes only the denied canonical user's `ResearchRun-[:PRODUCED]->ResearchFinding` provenance;
- garbage-collects the shared Finding only when it is uncurated and no ResearchRun references it;
- preserves Finding curator state/suppression, `CURATED_ENTITY` mappings and Finding-derived RelationObservations/claims;
- performs no deletion on ACL/backend/TLS/network/credential failure or on non-numeric/non-Nextcloud document identifiers;
- remains independent from Qdrant synchronization.

A future explicit `purge-document` workflow may coordinate deletion across derived stores after an authoritative document-lifecycle event. A periodic full ACL reconciler is intentionally deferred until operational need justifies it.

### Smaller RC5 follow-ups

- Reduce presentation drift between RAG-Admin Finding curation and `/curation/` by sharing more of the Finding view/presentation logic while keeping their authorization/session boundaries separate.
- Make the global self-service gate and Login-Flow identity behavior more explicit in the UI.
- Consider controlled expansion of self-service beyond a user's own ResearchRuns only after the ACL/provenance semantics are specified and tested.

## 0.8.6 direction

### Platform/resource abstraction

Keep Nextcloud as the reference platform, but move Nextcloud-specific resource, identity and authorization semantics behind explicit interfaces rather than forking the Planner/RRF/Reranker/Graph/LLM core for every groupware platform.

The intended migration is evolutionary and compatibility-preserving:

- introduce a structured `ResourceId` / `ResourceRef` with a stable serialization (for example `resource://nextcloud/files/66732`) while continuing to accept legacy `files:<id>` values during migration;
- model an AKI `Principal` separately from frontend-scoped external identity, platform identity and credential bindings;
- replace boolean authorization with an explicit decision such as `ALLOW / DENY / UNKNOWN`, preserving the current fail-closed/no-delete-on-backend-error distinction;
- identify explicit capability boundaries for resource lookup/content, authorization and identity, with archive/changes/contacts/mail remaining optional capabilities;
- keep retrieval backends (Elasticsearch, Qdrant, Graph) orthogonal to platform authorization/content semantics so an ownCloud/Pydio/SharePoint port can reuse the same retrieval implementation where appropriate;
- avoid introducing a monolithic `NextcloudPlatformAdapter` merely to create an abstraction. Stabilize the core types/boundaries first and move concrete behavior behind narrowly scoped providers incrementally.

This is an architectural 0.8.6 task, not an RC5 compatibility claim.

### Model profiles

The next minor line may expose richer **multi-model/model-profile selection** rather than adding it late to the 0.8.5 RC series. The current role-specific backend configuration remains the 0.8.5 contract; model-profile UX, selection policy and compatibility rules should be designed and tested as an explicit 0.8.6 feature.

## Post-0.8.6 provider decomposition

After the 0.8.6 resource/principal groundwork is stable, prefer a small provider split over a large platform-specific facade. The first useful interfaces are expected to be conceptually:

```python
class SearchProvider:
    def search(self, query, limit): ...

class ContentProvider:
    def get_content(self, document_id): ...

class AuthorizationProvider:
    def authorize(self, principal, document_ids): ...
```

The current Nextcloud deployment can initially map these to `ElasticsearchSearchProvider`, `ElasticsearchContentProvider` and `NextcloudAuthorizationProvider`. Only after those boundaries are proven should additional authorization implementations such as ownCloud, Pydio or SharePoint be added. Identity/capability interfaces can then be split out when a concrete second platform requires them rather than forcing a large speculative abstraction up front.

This keeps a future port close to an adapter exercise instead of a fork of the Planner/RRF/Reranker/Graph/LLM core.

# Roadmap

**Baseline:** `0.8.6-rc1`

This roadmap starts from the capabilities already delivered in the 0.8.6 release
candidate. Historical work completed in 0.8.5 and earlier belongs in the
CHANGELOG and release notes rather than in the forward-looking roadmap.

## 0.8.6-rc1 baseline

The current release candidate establishes the SunaQ product and architecture
baseline:

- user-visible research profiles **Schnell**, **Gründlich** and **Tief** with
  per-user entitlements;
- request-local model/profile configuration and role-specific LLM routing;
- startup-loaded administrator-owned model packages and prompt packs;
- live Nextcloud ACL as the final authorization boundary for private evidence;
- client-neutral source scopes with ordinary documents as the implicit provider
  default;
- SunaQ Recherche 0.3.0 with profile selection, source chips, progress and
  deterministic follow-up actions;
- SunaQ Admin for user/model permissions, credentials, Graph-Lite and Findings
  curation;
- Super-Light as the Elasticsearch-centric deployment profile, with optional
  Neo4j seeds/Graph-Lite and no required Qdrant/local reranker;
- fresh-install prefix `/opt/sunaq` with legacy-installation compatibility;
- explicit maintenance mode, smoke diagnostics and console backup/restore for
  SunaQ-owned operational state;
- optional ACL metadata prefilter, exact extracted-content duplicate grouping,
  Research Findings and lazy ACL-based cleanup of uncurated Finding provenance.

The rc1 profile comparison deliberately varies **budget only**. All shipped
profiles currently use one retrieval round, Evidence Review is off and planner
thinking is off.

## Near term: 0.8.6-rc1.1 / rc2 candidates

These items are suitable for the first follow-up release(s) after rc1. They
should be implemented independently so field results remain attributable.

### Simplify retrieval/completeness logic

Remove the legacy **Exhaustive Mode** now that research depth is represented by
explicit SunaQ profiles. This includes:

- exhaustive-intent planner branches;
- `exhaustive_verification_candidate_limit` and related special-case limits;
- exhaustive-only answer/warning paths;
- obsolete completeness wording, tests and documentation.

Completeness should remain conservative: SunaQ may report bounded or
near-capacity retrieval, but it should not imply global corpus completeness merely
because a question asks for "all" documents.

### Profile tuning

Use real rc1 workloads to tune Schnell/Gründlich/Tief rather than changing the
first release-candidate experiment prematurely.

Likely experiments include:

- adjusting candidate and answer-context budgets;
- evaluating whether Tief needs a larger window in normal corpora;
- introducing an additional retrieval round for Gründlich/Tief only when evidence
  gaps justify it;
- evaluating model/planner thinking with strict time and token limits. Reasoning
  loops observed with smaller Qwen models are a known operational risk;
- improving deterministic follow-up actions from verifier/retrieval signals.

These should remain separate experiments: budget, retrieval rounds and model
reasoning must not be changed together if their effect is to be measurable.

### SunaQ naming/schema cleanup

Finish non-breaking removal of legacy product names from active data structures
while retaining explicit upgrade compatibility where required.

In particular:

- migrate the Neo4j secondary label `AKIResearchFinding` to
  `SunaQResearchFinding`;
- keep legacy `akirag` app configuration and `.akirag.json` chat metadata
  readable as compatibility input, while all newly written state uses SunaQ
  naming;
- continue removing legacy display strings without renaming stable protocol,
  environment or database identifiers merely for cosmetics.

### Installer and client polish

- pull all selected container images during installation so
  `maintenance-mode.sh off` normally starts already-downloaded services instead
  of discovering registry/image problems at that point;
- live-refresh the SunaQ model selector after entitlement changes without
  requiring a tab reload;
- continue minor layout/accessibility polish where it does not complicate the
  deliberately thin Nextcloud client;
- expose useful pre-answer progress to generic OpenAI-compatible streaming clients
  only if it can be done without destabilizing the current provider/SSE path.

## Before 1.0

The following work is more important than additional UI features.

### Security and operational hardening

- reduce exposure of global service secrets through Docker Compose environment
  materialization by using file-mounted credentials or Docker secrets where
  practical;
- pin the Playwright base image by immutable digest;
- bound individual Neo4j readiness/schema attempts so one network call cannot
  stall installer progress reporting for a long interval;
- keep dependency upgrades deliberate, including a coordinated Transformers 5 /
  Hugging Face Hub evaluation and a real reranker smoke test;
- split heavyweight optional ML dependencies from the core/server requirement set
  where practical.

### Lifecycle and recovery

- provide an explicit plan/execute `purge-document` workflow for SunaQ-owned
  derived stores without pretending to control Nextcloud/Elasticsearch lifecycle;
- add a supported credential-master-key rotation workflow with recovery copy,
  full re-encryption and verification before commit;
- improve lifecycle reporting so an administrator can see which SunaQ-owned
  derived stores contain state for a document;
- keep chat/web archive retention explicit because archived copies have their own
  Nextcloud file IDs, ACLs and lifecycle.

### Retrieval and ACL behaviour

- evaluate Circle-aware ACL metadata prefiltering without weakening the mandatory
  live-ACL authorization boundary;
- investigate a bounded pre-rerank/pre-window ACL strategy for narrow-rights users
  without introducing unbounded adaptive fetching or an authorization oracle;
- reduce unnecessary entity-resolution diagnostic detail before treating that
  surface as an ordinary end-user API contract;
- consider distinct extracted-content hashes for statistics where independent
  source counts should not treat exact copies as separate evidence.

### Web and archive performance

Reduce synchronous WebDAV archive latency while preserving immediate provenance
and source usability. Prefer bounded parallelism and fewer file-ID
`PROPFIND` round trips over changes that weaken archive consistency.

## 1.x architecture

### Reasoning/backend abstraction

SunaQ should remain the evidence, retrieval and authorization authority while the
downstream reasoning component remains replaceable.

The intended boundary is:

```text
question/task
    -> SunaQ retrieval + ACL + evidence
    -> reasoning/task backend
    -> answer or proposed action
```

A future backend contract may support local/remote LLMs, specialist agents and
workflow engines. Such a backend may recommend another search, but SunaQ remains
responsible for source policy, ACL, retrieval budgets and the evidence returned.

External side effects require a separate capability/approval boundary. A model or
agent should propose an action; SunaQ/operator policy decides whether that action
may be executed.

### Platform/resource abstraction

Nextcloud remains the reference platform. A second platform should not require a
fork of the Planner/RRF/Reranker/Graph/provider core.

Introduce narrow interfaces only when a concrete second platform requires them,
for example:

```python
class SearchProvider:
    def search(self, query, limit): ...

class ContentProvider:
    def get_content(self, resource_id): ...

class AuthorizationProvider:
    def authorize(self, principal, resource_ids): ...
```

Longer term this may include:

- a structured `ResourceId` / `ResourceRef` while accepting legacy
  `files:<id>` identifiers during migration;
- a SunaQ `Principal` distinct from frontend-scoped external identity,
  platform identity and credential bindings;
- explicit `ALLOW / DENY / UNKNOWN` authorization decisions;
- narrowly scoped providers for Nextcloud first and, only when justified by a
  real integration, ownCloud/Pydio/SharePoint or another content platform.

Avoid a speculative monolithic platform adapter. The current Nextcloud security
and retrieval semantics should first be represented by small, proven boundaries.

## Lower-priority product work

- reduce presentation drift between SunaQ Admin Findings curation and
  end-user `/curation/` while preserving their different authorization models;
- consider controlled expansion of self-service curation only after
  cross-user/privacy semantics are explicit;
- add a dedicated per-binding delete action in SunaQ Admin;
- improve mail backfill state so moving `mail.not_before` to an earlier date can
  safely reopen the historical UID range without manual cursor repair;
- evaluate more durable background handling for Playwright render jobs where
  deployments need it.

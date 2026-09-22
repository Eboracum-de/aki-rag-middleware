# Known limitations

**Reference:** `0.8.5-rc5`

This file records current limits so that beta expectations match the code. Items
listed here are not necessarily defects; several are deliberate scope boundaries.

## Installation and deployment

- Only `standard + native` and `super-light + dockerized` are supported/tested
  deployment mappings in 0.8.5.
- Installer/rerun preflight validates the install source, non-empty install
  prefix, CA files and Docker availability before destructive refresh steps, and
  refuses a running existing AKI stack. Explicitly supplied Nextcloud and
  Elasticsearch URLs receive a best-effort, non-fatal host-`curl` reachability/TLS
  probe after prerequisites are available. This is an early typo/connectivity
  diagnostic only and cannot prove that an authenticated endpoint, model backend
  or later runtime path will remain usable; use the smoke/acceptance checks and
  archive the generated `install/last-install-command.sh` for reproducible reruns.
- Super-Light intentionally relies on external Nextcloud, Elasticsearch and LLM
  services. Their availability and backup are outside the local Compose stack.
- Super-Light still supplies several global service secrets through Compose environment files. A non-root account that can operate the Docker daemon/Compose stack can therefore render or inspect those values (for example with `docker-compose config`). Treat Docker-daemon access as privileged/root-equivalent, do not share full rendered Compose output, and restrict membership/access accordingly. Moving routine service-secret delivery to Docker secrets or file-mounted credentials is deferred hardening rather than an RC5 release blocker.
- Bundled nginx and OpenWebUI are opt-in in Super-Light. AKI Recherche is the
  reference user UI for the current beta.
- The locally built Playwright renderer pins Playwright/Python package versions and the
  Microsoft base-image tag (`v1.62.0-noble`), but the base image is not yet pinned by
  immutable digest. Digest pinning is deferred dependency hardening.

## Contact seeds and Admin UI

- The internal `canonical_user_id` remains part of the database model, but normal
  UI/CLI administration is keyed by Nextcloud server/login. Scripts should avoid
  exposing UUIDs as operator input unless doing low-level diagnostics.
- Legacy global `NEXTCLOUD_USERNAME` / `NEXTCLOUD_APP_PASSWORD` CardDAV settings
  remain only for compatibility. Multi-user seed sync should reuse Login-Flow
  credentials.

## Retrieval and completeness

- RAG retrieval is bounded. A request is not globally exhaustive merely because it
  asks for documents. Completeness/counting intent has separate limits and must
  fail conservatively when those limits prevent a defensible complete result.
- Standard and Super-Light use different normal verifier windows: 6 and 10
  authorized candidates respectively. Bounded/exhaustive limits are configured
  separately.
- Super-Light has no local reranker. Deduplication is independent and remains
  active, but Elasticsearch ranking plus verifier behavior can still be less
  precise than a well-tuned reranked standard deployment on difficult corpora.
- Exact duplicate grouping can use Nextcloud FullTextSearch's valid 32-hex
  `hash` (MD5 of extracted FullTextSearch content, not a raw-file byte hash) as
  the primary exact-content signal. Distinct Nextcloud file IDs remain separate ACL
  variants; an authorized identical copy may be promoted when the ranked variant is
  denied. Near-text/OCR and same-stem format variants remain secondary signals.
- Conversational reference resolution is LLM-based and language-neutral rather than
  gated by a German keyword list. When prior chat is actually required, up to three
  documents from the immediately preceding answer context are re-resolved through
  the current user's live ACL and current source-scope policy before joining the
  normal verifier pool. This is short-lived turn continuity, not persistent entity
  memory; structured conversation entity state remains a later enhancement.
- Query rewriting is intentionally conservative. The model emits a small SearchSpec with a Nextcloud-compatible `elastic_query` and a natural
  `semantic_query`; it never emits raw Elasticsearch JSON DSL. Grammatical normalization is allowed,
  but factual synonyms must not be invented and explicit names/identifiers/years must
  not be silently discarded. Additional retrieval rounds are optional and remain
  bounded by administrator configuration.
- ACL-denied documents are removed without adaptive backfill of lower-ranked candidates.
  This can yield less evidence even when an authorized document existed below the
  bounded final window. The current order is retrieval/fusion, optional reranking,
  then live ACL. A fixed bounded pre-rerank ACL pool is a possible future
  optimization, but "keep fetching until N authorized results exist" is not part of
  the design because it creates variable work and another inference/timing surface.
- The optional RC5 ACL metadata prefilter evaluates owner/direct-user/group
  metadata. Nextcloud Circles are not considered in this first version; Circle
  support may be added in a later update. Leave the prefilter disabled where
  Circle-only shares must remain discoverable.
- Shared Neo4j names/aliases can influence retrieval across users by design. They are
  retrieval knowledge, not answer evidence. The current search API still exposes
  fairly rich entity-resolution diagnostics (matched forms/candidates/search forms);
  this diagnostic surface should be minimized or gated before it is treated as a
  normal end-user contract.

## Web Research and archive

- Cookie/overlay cleanup is best effort. Persistent per-host browser state reduces
  repeated consent prompts but does not guarantee that every CMP will disappear.
- Login walls, paywalls, CAPTCHAs and access controls are not bypassed or removed.
- A Playwright PDF is a readable snapshot, not a complete WARC/WACZ/forensic
  archive. Dynamic/video-heavy content can still render incompletely.
- Raw HTML, when enabled, contains the fetched main response rather than a package
  of every referenced resource.
- Background PDF rendering uses an in-process bounded task queue. If the API container is restarted while a render is pending, that render job is not durable and its sidecar may remain `pending`; text evidence and the answer are unaffected.
- Playwright PDF rendering is backgrounded, but the WebDAV archive write that creates the run directory, text snapshots, metadata/fetch-log material and initial `recherche.md` is still synchronous. On higher-latency Nextcloud/WebDAV paths this archive phase can dominate Web Research response time even when search/fetch/relevance are fast. This is a performance limitation, not an evidence or renderer failure.
- Web pages, incoming mail and saved chats can contain adversarial or instruction-like
  text. Structured verifier/Graph schemas and evidence separation reduce risk, but
  0.8.5 does not claim a complete prompt-injection defense. See `THREAT-MODEL.md`.

## AKI Recherche

- AKI 0.2.6 targets Nextcloud 23+. Saved chats live as readable Markdown in the user-owned visible `AKI-Chats/` Nextcloud folder, with hidden `.akirag.json` sidecars for machine state. Chats last written by older app versions remain HTML until that conversation is saved or renamed again. Chat archives are a separate, optional `/chatarchive` source scope, not automatically trusted as primary document evidence. A saved chat is a new Nextcloud file with its own ACL/lifecycle; revoking the original source document does not automatically erase text already copied into the chat. Strict revocation deployments should leave chat archive disabled or define a retention/purge process.
- The app is deliberately thin. Advanced provider diagnostics and administration
  remain in RAG Admin rather than being duplicated in AKI.

## Graph

- CardDAV seeds and `AKI Recherche` findings are lightweight graph inputs. Full
  document graph extraction remains comparatively expensive and opt-in.
- `AKI Recherche` stores only positive, direct, verifier-supported findings; it
  does not turn query hypotheses into global facts automatically. Research Findings are admin-visible and may be manually curated into document-grounded entity mentions and claims. They are still not automatically promoted into global facts or retrieval/query expansion.
- Equivalent Findings remain shared/deduplicated curation objects, while per-user
  observation provenance is represented through
  `CanonicalUser -> ResearchRun -> ResearchFinding`. Findings, Observations and
  Relations in RAG Admin require a selected canonical-user context and are filtered
  fail-closed through that user's current Nextcloud live ACL before evidence is
  rendered. **RAG Admin itself is nevertheless a trusted operator surface, not a
  personal Nextcloud-user surface:** an authenticated RAG administrator may select
  another configured user's context and thereby inspect evidence that *that selected
  user* may currently access. Do not expose RAG Admin to ordinary users or treat the
  administrator's own Nextcloud ACL as an isolation boundary.
- Optional self-service curation is narrower: a user sees only ResearchRuns produced
  for that canonical user and only Findings whose supporting document still passes
  that user's temporary Login-Flow credential. Shared Entity/Finding/Claim decisions
  can still affect later users because curation knowledge is intentionally global.
- Graph extraction worker startup and automatic enqueue of cited documents are off
  by default in the reference configuration.

## Mail

- The schema supports multiple mail accounts per canonical user, but the beta Admin
  UI is still oriented around the common one-account-per-user workflow.
- Mail credentials and Nextcloud credentials share the generic CredentialStore but
  are different services. Direct SQL updates by username are unsafe and unsupported.
- Raw EML is off by default for newly created accounts. The normalized mail, attachments, provenance headers and raw-message SHA-256 are retained; enable EML explicitly when forensic/raw-message retention is required.

## Operations

- There is no unified cross-store `purge-document` / data-subject workflow that
  proves deletion across Elasticsearch, Qdrant, Neo4j, optional RetrievalRecords
  and retained archive derivatives. RC5 does perform lazy Neo4j self-cleanup when
  a successful live-ACL check definitively denies a user's numeric Nextcloud file:
  only that user's provenance edges for still-uncurated ResearchFindings are
  removed, and globally orphaned uncurated Findings are garbage-collected.
  Curated Findings are preserved, and ACL/backend/credential errors never trigger
  deletion. See `DATA-LIFECYCLE.md`.
- The RC5 console recovery workflow covers AKI-owned configuration, SQLite,
  credential/master-key state and bundled Neo4j. It does not back up Nextcloud,
  Elasticsearch, Qdrant, external Neo4j, OpenWebUI/Playwright state or model
  caches. Restore currently requires the same supported deployment profile/mode
  and installation prefix. Master-key rotation remains a separate follow-up.
- Global service secrets such as provider/backend API keys still live in protected
  environment files rather than a dedicated external secret manager.
- The measured 4 GiB Super-Light success point is not a hard upper bound. Chromium
  produces transient memory peaks; capacity should be verified under the intended
  Web Research workload.
- Elasticsearch unavailability is translated to a friendly service-unavailable
  response, but the middleware cannot answer private document questions while its
  required Super-Light document arm is down.

### Verifier/Answer budgets

- The verifier and answer model may intentionally be different backends, so their
  remote limits remain separate in the current release candidate. The current configuration still has
  overlapping candidate/document caps (`bounded_verification_candidate_limit`,
  `REMOTE_VERIFIER_MAX_CANDIDATES`, `REMOTE_ANSWER_MAX_DOCUMENTS`, character
  budgets). These should be consolidated behind a small set of base values with
  empty per-role overrides inheriting the base value in a later cleanup.
- A verifier batch is not a retrieval round. If one retrieval round yields more
  candidates than one verifier batch, batching should consume the existing
  candidate pool before a new query rewrite/retrieval round is started.

## Identity administration

- Open identity candidates are grouped by transitive active `SAME_AS` component,
  so several source-specific ContactRecords for one confirmed identity do not
  create a combinatorial review queue. RAG Admin can filter the queue by canonical
  Nextcloud user and shows CardDAV user/address-book provenance for both sides.
  The filter is an administrative work-queue view, not an ACL boundary.
- End-user `/curation/` currently covers Research Findings only. Self-service
  `SAME_AS` / `NOT_SAME_AS` identity decisions are not yet exposed because a
  user-facing implementation must avoid revealing ContactRecords that exist only
  in another user's private address book.
- Nextcloud Login Flow must be completed by the actual target user. Nextcloud impersonation/"Nachahmen" does not safely pre-create another user's app password and can bind an external client identity to the impersonator's Nextcloud account. Revoke erroneous Nextcloud app passwords and remove the corresponding binding before reuse.
- The current Admin UI does not yet expose a dedicated per-binding delete button in RAG Admin.

## Mail backfill cutoff changes

The current mail state records UID cursors but not the effective `mail.not_before` value used when a historical backfill completed. If an account is first backfilled with a later cutoff (for example 2024) and the administrator later moves `not_before` earlier (for example 2020), the stored `backfill_before_uid=1` may keep the newly eligible older messages closed. Until the state schema is extended, the affected mailbox backfill cursor must be reopened manually after such a cutoff expansion.

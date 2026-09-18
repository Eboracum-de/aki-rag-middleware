# Known limitations

**Reference:** `0.8.5-rc3`

This file records current limits so that beta expectations match the code. Items
listed here are not necessarily defects; several are deliberate scope boundaries.

## Installation and deployment

- Only `standard + native` and `super-light + dockerized` are supported/tested
  deployment mappings in 0.8.5.
- The Super-Light `--ca-certificate` path/PEM check is not the first global
  installer preflight. A bad path aborts safely but can do so after earlier setup
  work. Correct the input and rerun the installer.
- Super-Light intentionally relies on external Nextcloud, Elasticsearch and LLM
  services. Their availability and backup are outside the local Compose stack.
- Bundled nginx and OpenWebUI are opt-in in Super-Light. AKI Recherche is the
  reference user UI for the current beta.

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
- Query rewriting is intentionally conservative. The model emits a small SearchSpec with a Nextcloud-compatible `elastic_query` and a natural
  `semantic_query`; it never emits raw Elasticsearch JSON DSL. Grammatical normalization is allowed,
  but factual synonyms must not be invented and explicit names/identifiers/years must
  not be silently discarded. Additional retrieval rounds are optional and remain
  bounded by administrator configuration.
- ACL-denied documents are removed without backfilling lower-ranked candidates.
  This can yield less evidence rather than a weaker synthetic answer; that is a
  deliberate security/quality rule.

## Web Research and archive

- Cookie/overlay cleanup is best effort. Persistent per-host browser state reduces
  repeated consent prompts but does not guarantee that every CMP will disappear.
- Login walls, paywalls, CAPTCHAs and access controls are not bypassed or removed.
- A Playwright PDF is a readable snapshot, not a complete WARC/WACZ/forensic
  archive. Dynamic/video-heavy content can still render incompletely.
- Raw HTML, when enabled, contains the fetched main response rather than a package
  of every referenced resource.
- Background PDF rendering uses an in-process bounded task queue in RC3. If the API container is restarted while a render is pending, that render job is not durable and its sidecar may remain `pending`; text evidence and the answer are unaffected.

## AKI Recherche

- AKI 0.2.3 targets Nextcloud 23+. Saved chats live in the user-owned `AKI-Chats/` Nextcloud folder. They are a separate `/chatarchive` source scope, not automatically trusted as primary document evidence.
- The app is deliberately thin. Advanced provider diagnostics and administration
  remain in RAG Admin rather than being duplicated in AKI.

## Graph

- CardDAV seeds and `AKI Recherche` findings are lightweight graph inputs. Full
  document graph extraction remains comparatively expensive and opt-in.
- `AKI Recherche` stores only positive, direct, verifier-supported findings; it
  does not turn query hypotheses into global facts automatically. Research Findings are admin-visible and may be manually curated into document-grounded entity mentions and claims. They are still not automatically promoted into global facts or retrieval/query expansion.
- Graph extraction worker startup and automatic enqueue of cited documents are off
  by default in the reference configuration.

## Mail

- The schema supports multiple mail accounts per canonical user, but the beta Admin
  UI is still oriented around the common one-account-per-user workflow.
- Mail credentials and Nextcloud credentials share the generic CredentialStore but
  are different services. Direct SQL updates by username are unsafe and unsupported.
- Raw EML is off by default for newly created accounts. The normalized mail, attachments, provenance headers and raw-message SHA-256 are retained; enable EML explicitly when forensic/raw-message retention is required.

## Operations

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
  remote limits remain separate in rc3. The current configuration still has
  overlapping candidate/document caps (`bounded_verification_candidate_limit`,
  `REMOTE_VERIFIER_MAX_CANDIDATES`, `REMOTE_ANSWER_MAX_DOCUMENTS`, character
  budgets). These should be consolidated behind a small set of base values with
  empty per-role overrides inheriting the base value in a later cleanup.
- A verifier batch is not a retrieval round. If one retrieval round yields more
  candidates than one verifier batch, batching should consume the existing
  candidate pool before a new query rewrite/retrieval round is started.

## Identity administration

- Nextcloud Login Flow must be completed by the actual target user. Nextcloud impersonation/"Nachahmen" does not safely pre-create another user's app password and can bind an external client identity to the impersonator's Nextcloud account. Revoke erroneous Nextcloud app passwords and remove the corresponding binding before reuse.
- RC3 does not yet expose a dedicated per-binding delete button in RAG Admin.

## Mail backfill cutoff changes

The current mail state records UID cursors but not the effective `mail.not_before` value used when a historical backfill completed. If an account is first backfilled with a later cutoff (for example 2024) and the administrator later moves `not_before` earlier (for example 2020), the stored `backfill_before_uid=1` may keep the newly eligible older messages closed. Until the state schema is extended, the affected mailbox backfill cursor must be reopened manually after such a cutoff expansion.

# AKI RAG Middleware 0.8.5-rc4

**Release date:** 2026-09-19  
**Status:** public beta / release candidate  
**License:** GNU AGPL-3.0-only

`0.8.5-rc4` consolidates the field-tested hardening work after RC3. The main theme is not a new retrieval architecture, but making multi-user Findings/Graph-Lite administration, self-service curation and installer reruns match the intended security and operational model.

## Highlights

- user-specific ResearchRun provenance through `CanonicalUser -> ResearchRun -> ResearchFinding`;
- live Nextcloud ACL filtering for Findings, Observations and Relations in the selected RAG-Admin user context;
- optional end-user `/curation/` with Nextcloud Login Flow, temporary encrypted app passwords, CSRF protection and hard session expiry;
- per-user permission plus global switch for self-service curation;
- ResearchRun-level and per-produced-Finding dismissal without deleting shared Findings/provenance;
- durable Entity/non-Entity form decisions, exact name/curated-alias defaults and reversible Finding Entity curation;
- document-grounded Mention/Claim workflows with versioned relation ontology and review/withdrawal state;
- relation targets no longer become Entity candidates solely because they were verifier relation targets;
- stronger installer rerun/preflight safeguards, install-prefix protection and archived exact install command;
- repaired Super-Light/standard installer script integrity and shell-syntax regression coverage;
- fixed AKI Recherche chat-history access for normal users on Nextcloud 23 and field-tested it with a second user;
- refreshed security, privacy, lifecycle and administration documentation.

## Multi-user and ACL boundary

Nextcloud remains the final authorization authority for document evidence.

For RAG Admin, RC4 requires a selected canonical-user context for Findings/Observations/Relations and applies that selected user's current live Nextcloud ACL before rendering supporting document evidence. RAG Admin itself remains a **trusted operator surface**: its administrator can deliberately switch to another configured user's context and is not constrained by the administrator's own personal Nextcloud ACL.

Self-service curation is narrower. The user authenticates through Nextcloud Login Flow and currently sees only that canonical user's own ResearchRuns plus Findings whose supporting document still passes the temporary Nextcloud credential.

Shared Entity/Finding/Claim curation remains organization-level knowledge and may be reused across users; it never grants access to the supporting file.

## Findings / Graph-Lite changes

- Admin curation is research-run centered rather than a corpus-wide unscoped Finding inbox.
- Equivalent Findings can share one curation decision while preserving per-run user/query provenance.
- Entity decisions write directly; technical JSON preview is optional.
- Unique canonical-name / curated-alias matches can be accepted as defaults.
- Similar existing Entities can be assigned or used to create a contextual alias.
- Manual document Mentions and Claims survive later machine graph refreshes.
- Changing a curated endpoint marks dependent claims `review_required` instead of leaving stale claims active.
- Active manual claims can be withdrawn without deleting their provenance.
- Relation sources can remain Entity candidates; target-only relation text is no longer promoted unless independently extracted as an Entity/mention.

## Installer / operations

- Non-empty unrelated install prefixes are refused before destructive refresh steps.
- Existing running AKI stacks are rejected by rerun preflight; stopped installations can be repaired/rerun.
- Required source paths, CA files, prefix writability and Docker availability are checked early.
- The exact effective installer invocation is stored as `install/last-install-command.sh` for reproducible reruns.
- Shell syntax is checked for all shipped shell scripts in CI.

## Test baseline

The RC4 freeze baseline on 19 September 2026 completed:

- **426 pytest tests passed** on Python 3.13;
- Python compile check passed;
- shipped shell syntax check passed.

The Super-Light path has also been field-tested against a real two-user Nextcloud setup during the RC4 hardening cycle, including normal-user AKI chat-history access after the NC23 annotation compatibility fix. Operators should still run the acceptance checklist from `docs/BETA-OPERATIONS.md` on their own deployment.

## Known limitations / explicitly deferred

RC4 keeps the current post-ranking live ACL design. It does **not** yet use FullTextSearch ACL metadata as an Elasticsearch/Qdrant prefilter, and retrieval deduplication does **not** yet use the FullTextSearch extracted-content `hash` as its primary exact duplicate key.

Those items, including Circle-aware optional prefiltering and ACL-safe duplicate groups across distinct Nextcloud file IDs, are tracked for RC5 in `docs/ROADMAP.md`.

Other deferred polish includes reducing presentation drift between RAG-Admin and self-service Finding curation.

Richer multi-model/model-profile selection is intentionally moved out of the 0.8.5 RC series and is an `0.8.6` direction.

See `docs/KNOWN-LIMITATIONS.md`, `docs/THREAT-MODEL.md` and `docs/ROADMAP.md` before production deployment.

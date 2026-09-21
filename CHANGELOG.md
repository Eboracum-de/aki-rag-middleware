# Changelog

## Unreleased installer hotfix

- Fix Super-Light reruns that appended newly introduced runtime keys with a literal `\\n`, which could hide `RAG_PROVIDER_INTERNAL_KEY` from Docker and make secure-runtime validation fail after an upgrade. A narrow repair step also normalizes already affected `runtime.env` files.
- Fix Standard reruns to regenerate internal machine keys when legacy/example `replace-me` placeholders are present.
- Recreate a missing `install/.env` from `.env.example` before the Standard Docker Compose stopped-stack preflight so an interrupted installation remains repairable without bypassing the safety check.

## 0.8.5-rc4.3 – 2026-09-20

- Complete rc4.3 blank-VM acceptance for both supported deployment mappings (Standard/native and Super-Light/dockerized), align current documentation/version locks to rc4.3, and record deferred Playwright/Neo4j/WebDAV polish without changing the accepted runtime behavior.
- Add explicit Standard installer switches `--with-playwright` / `--no-playwright`; they update `archive.renderer.enabled`, while reruns without either switch preserve the existing `web.yaml` choice.
- Make reranking explicitly opt-in: Standard now defaults to `reranker.backend: none`, missing reranker configuration is treated as disabled, and the installer no longer downloads a Hugging Face reranker model unless `--with-reranker-download` is requested. TEI/local reranking remains available for controlled comparison tests.
- Restore Standard-profile lifecycle management for the optional Playwright web-archive renderer: declare it as a Compose `renderer` profile, build/start it automatically when `archive.renderer.enabled=true`, remove it when disabled, persist `LOCAL_PLAYWRIGHT` state and expose its health in `status.sh`/smoke diagnostics.
- Centralize outbound Nextcloud TLS under `nextcloud.verify_tls` / `nextcloud.ca_file` for Login Flow, live ACL, CardDAV, mail WebDAV and web archive; add repeatable `--ca-certificate` support to Standard as well as Super-Light so private Nextcloud CAs are scoped to Nextcloud traffic without replacing public OpenAI/Hugging Face trust. Standalone Nextcloud workers now also apply the configured X.509 strict compatibility policy.
- Add fail-closed machine authentication and explicit `PUBLIC` / `TRUSTED_PROVIDER` / `INTERNAL` / `ADMIN` / `USER` zones for the internal FastAPI API. `RAG_INTERNAL_API_KEY` authenticates the service plane while the separate `RAG_PROVIDER_INTERNAL_KEY` proves trusted-provider role; USER routes additionally require a usable scoped identity before the existing Nextcloud live ACL authorizes evidence.
- Inject the internal machine credential only from trusted nginx API/auth locations after the proxy's administrator/access authentication layer. Keep `/live`, RAG Admin and self-service curation on their existing dedicated authentication models.
- Refuse accidental non-loopback native API binding unless `RAG_ALLOW_REMOTE_INTERNAL_API=true` is explicitly set, and authenticate direct health/status probes.
- Generate and preserve both internal machine-role keys on Standard and Super-Light installer reruns without rotating existing valid keys; nginx receives only the general internal key, never the provider-role secret.
- Harmonize the common Standard/Super-Light installer CLI: both profiles accept the same Nextcloud/Elasticsearch connection switches and symmetric OpenWebUI/proxy enable/disable flags plus proxy listen-port overrides.
- Preserve prior OpenWebUI/proxy selections on rerun by default, while making `--no-openwebui` and `--no-proxy` authoritative overrides; Standard removes explicitly disabled containers but retains persistent volumes.
- Allow Standard installer connection overrides to update `config.yaml` without replacing unrelated site configuration.
- Add a fail-closed Standard rerun preflight: report recognized existing installations, detect native PID-file processes, active `rag-*.service` units and running Compose services, and abort before modifications when services are active or their state cannot be verified.
- Fix Standard Neo4j schema initialization after Compose startup by running `python -m rag.graph` from the application root rather than `$PREFIX/install`; add 10-second progress notices while Neo4j/schema readiness is pending.
- Probe Standard nginx health on the configured HTTPS listen port instead of hard-coding 443.

## 0.8.5-rc4.2 – 2026-09-20

- Retry the **complete idempotent Neo4j schema upgrade** when the API recovers from a startup-time Neo4j outage before persisting Research Findings; do not mark Findings schema readiness after applying only the ResearchFinding subset.
- Retain undecryptable temporary Findings-curation sessions as locally unusable `revocation_pending` rows instead of deleting them. This preserves the automatic Nextcloud app-password revocation path when a valid master key is temporarily unavailable or later restored.
- Add regressions for both recovery paths. Private CI baseline: **452 tests passed**, plus Python compile and shipped-shell syntax checks.

## 0.8.5-rc4.1 – 2026-09-20

- Document the complete Super-Light installer CLI and support reproducible alternate nginx listen ports (`--proxy-http-port` / `--proxy-https-port`) for same-host Nextcloud/Apache deployments; add a path-scoped Apache reverse-proxy example that leaves the Nextcloud root untouched.
- Preserve Super-Light admin credentials across reruns, persist regenerated runtime secret keys when legacy entries are missing, use the configured admin username consistently for nginx Basic Auth, and report successful Neo4j schema readiness explicitly.
- Make sparse/optional Neo4j relationship reads warning-safe in admin diagnostics, entity/merge lookup, relation views and legacy backfills, avoiding `UnknownRelationshipTypeWarning` when types such as `MENTIONS_NAME` or `MERGED_INTO` have never yet been created.
- Consolidate the Neo4j application schema: document the complete node/relationship/property contract, replace synthetic property-token markers with warning-safe optional reads, add missing indexes and idempotent legacy backfills, and run the full schema upgrade from standard/Super-Light installers plus a nonfatal API-startup fallback.
- Fail closed in self-service Finding curation when live Nextcloud ACL is disabled or an ACL decision is unavailable instead of exposing the unfiltered Finding set.
- Treat `install-state.env` strictly as allowlisted data after validating the installation prefix; never execute state-file contents as shell code.
- Remove global 2,000-Finding lookup windows from single-Finding guards and ResearchRun reconstruction; load the exact produced/selected Findings and batch ACL checks for bulk actions.
- Keep API startup available when an ephemeral curation-session row cannot be decrypted; discard the unusable local row while continuing cleanup of valid sessions.
- Move blocking Nextcloud Login Flow, revocation and self-service ACL work off the FastAPI event loop.
- Repair the optional graph-evidence enqueue hook so enabling it cannot fail on an undefined `source_scopes` variable.
- Make Super-Light wait for Neo4j schema readiness and retry the idempotent schema initialization during first start, avoiding an early Bolt-handshake race while the database is still coming up.
- Correct the RC4 validation baseline and public release-candidate lineage in the technical/install documentation.

Planned follow-up work is tracked in `docs/ROADMAP.md`.

## 0.8.5-rc4 – 2026-09-19

- Fix AKI Recherche chat-history endpoints for normal users on Nextcloud 23 by using parser-compatible multi-line `@NoAdminRequired` docblocks; field-tested with a second non-admin user.

- Stop promoting verifier relation targets solely from their target role into Entity curation; keep relation sources and independently extracted target mentions, and hide legacy `Relationsziel` candidates from existing Findings.

- Persist normalized global Entity/non-Entity form decisions so rejected phrases do not return in later Findings; lazily adopt historic manual observations when the schema backfill has not run, and let an explicit later assignment safely reverse the decision.
- Treat unique canonical-name and curated-alias matches as Finding defaults with a one-click bulk accept action, and add “Als Alias anlegen” for similar known Entities using the established contextual alias policy.
- Apply ordinary Finding Entity actions immediately while retaining the former technical JSON preview behind an optional “Details ansehen” button.

- Make Observations a real pending-review queue by default and repair exact status filtering, including defensive application-side enforcement and a dedicated manual Non-Entity view.
- Scope the Observations list/detail/mutation and Relations list to a selected Nextcloud user through the current live ACL of each supporting Document.
- Remove manually rejected Entity candidates from the curated Finding evidence view while retaining immutable verifier JSON only as a collapsed diagnostic; collapse JSON evidence in the Relations view as well.

- Replace per-pair Finding claim forms with one dynamically filtered Entity A / ontology relation / Entity B selector.
- Allow active Finding claims to be withdrawn without deleting their RelationObservation or audit provenance.
- Make persisted document Mentions explicit in the Finding UI, allow searched reassignment of already curated Entity mentions, and promote the “Mentions only” completion path when no relationship is evidenced.

- Abort the Super-Light installer preflight when any existing AKI RAG service is running; report a fully stopped existing stack as informational and allow the repair/rerun path.

- Apply unique exact seed/name resolution to EvidenceFrame-derived Entity candidates as well as QueryFrame Entities.
- Register the complete RelationObservation property contract at schema initialization and use property-safe reads for optional Finding claims, preventing Neo4j UnknownPropertyKeyWarning noise on stores without relation observations.

- Render Finding EvidenceFrames as readable criteria, mentions and relation observations while retaining expandable raw JSON for diagnostics.
- Surface named EvidenceFrame constraints and relation endpoints as curator-gated Entity candidates, add explicit existing-Entity search/assignment, and keep free-form verifier predicates separate from ontology claims.
- Add the controlled `SUPERVISORY_BOARD_MEMBER_OF` predicate for explicitly evidenced supervisory-board memberships; indirect references such as an “Aufsichtsratsschreiben” alone remain insufficient.

- Remove accidentally duplicated/corrupted tails from both profile installers; the CI shell-syntax gate now covers every shipped shell script.
- Fix ResearchRun dismissal when a run contains findings outside the selected user's current visible subset; validate the run/user context and live-visible evidence instead of rechecking every raw finding.
- Add single-run and checkbox-based bulk dismissal directly to the Research Findings list while preserving findings and provenance.
- Remove the obsolete standalone Nextcloud EML conversion shell script; supported mail ingestion uses the per-user IMAP importer and its normalized archive layout.
- Refuse non-empty install prefixes that are not recognized as AKI RAG installations, preventing accidental overwrite of unrelated application directories when running as root.
- Fix a provider regression in the Research Finding source-scope guard that could raise a 500 after the answer context was built.
- Record the exact installer invocation for reproducible Super-Light reruns and add an early rerun preflight for required source paths, CA files, install-prefix writability and Docker availability; report existing stack state without preventing repair of stopped services.
- Document the recommended rerun workflow and the location of `install/last-install-command.sh`.

- Align ResearchRun Findings with the final answer context instead of the wider Candidate-Verifier match pool, so curation reflects documents that actually reached the answer model.
- Record selected source scopes and supporting-document source origin in ResearchRun/Document provenance; reject known archive-origin Findings that fall outside an explicit source selection.
- Treat same-stem HTML/HTM/Markdown files as document-format variants alongside TXT/PDF/ODT/DOC/RTF, improving deduplication of legacy mail decompositions without lowering the near-text similarity threshold.

- Make the smoke test deployment-profile aware: dockerized Super-Light no longer fails for a missing host Python venv, configured-off Qdrant is reported as disabled, and Playwright renderer degradation is reported separately.
- Keep the optional Playwright renderer service alive when Chromium itself fails to launch, exposing the launch error through its live endpoint instead of entering a restart loop; Web search and non-rendered archive output remain available.
- Expose an explicit diagnostic reason when per-user Web archiving is disabled or has no target path.
- Allow a deliberately narrow web-only follow-up rewrite for short acronyms when the immediately preceding user query used the exact acronym inside a longer entity name (for example, FLG after FLG Automation), without enabling general chat-topic carry-over.

- Replace the corpus-wide Findings inbox with user-scoped ResearchRun curation: `CanonicalUser -> ResearchRun -> ResearchFinding -> Document`. ResearchRuns retain original query provenance while equivalent Findings remain globally deduplicated and reuse one shared curation decision.
- Apply current-user Nextcloud live ACL before Admin or end-user Finding evidence is listed or opened; unauthorized Findings are omitted from counts and legacy global no-entity suppression is no longer a user-context bypass.
- Add per-ResearchRun and per-produced-Finding dismissal as queue state without deleting provenance or globally suppressing the shared Finding.
- Add optional end-user `/curation/` self-service. It uses Nextcloud Login Flow, no RAG password, a separately encrypted temporary app password, HttpOnly/Secure/SameSite=Strict cookie, session-bound CSRF and a configurable hard absolute session lifetime (default 7200 seconds).
- Add per-canonical-user curation permission plus global `admin_user_context` / `user_self_service` controls. API startup invalidates and attempts to revoke all surviving temporary curation app passwords; failed revocations stay unusable as `revocation_pending`.
- Record curator identity on shared Entity/Finding/Claim decisions for audit provenance.

- Documentation hardening: add an explicit threat model, data lifecycle/backup/deletion guidance and a neutral relationship-to-Nextcloud-Context-Chat document.
- Clarify the intentional distinction between shared identity/alias/Finding curation and ACL-protected document evidence.
- Document the current post-ranking live-ACL/no-adaptive-backfill trade-off without claiming the proposed fixed pre-rerank ACL pool is implemented.
- Document optional Chat Archive retention semantics, prompt-injection/untrusted-content limits, the then-open Finding user-provenance gap, and the absence of a unified cross-store purge/key-rotation workflow; RC4 subsequently closes the Findings user-context/ACL gap through ResearchRun provenance and live-ACL views.
- Refresh stale internal RC wording and fix inconsistent/broken documentation passages.
- Refine the prompt-injection threat model: ordinary retrieval is constrained rather than agentic, while Graph persistence and Web-after query egress remain the relevant boundaries.
- Treat retrieved document/mail/web/chat text explicitly as untrusted evidence in verifier, evidence-control, answer and Web-after prompts; suppress secret-like/internal identifiers from derived public Web queries.
- Document trusted provider-client keys as integration-server credentials and recommend reverse-proxy network allowlists/mTLS as defense in depth for externally reachable frontends.
- Refine the Context Chat comparison around live WebDAV authorization, batched ACL cost, independent request processing, model choice and UI/integration agnosticism.
- Translate the consolidated technical reference to English.
- Translate the architecture baseline to English and remove evaluative/marketing-style wording in favor of neutral architecture descriptions and trade-offs.
- Clarify that Graph-Lite Research Findings are optional enrichment: ordinary retrieval/ACL/verification/answering works without Findings or curation, while curated graph knowledge can improve entity and relationship-oriented retrieval.
- Warn administrators not to perform another user's first Nextcloud authorization under the administrator's frontend identity; the current release has no supported binding-reassignment workflow.


## 0.8.5-rc3 – 2026-09-17

- First public release candidate / public beta under the AKI RAG Middleware project name.
- Consolidates the 0.8.5-rc2 field baseline and Graph-Lite draft work into one release identity.
- Findings administration defaults to open findings, groups unresolved work by entity text and supports checkbox-based bulk assignment / bulk not-an-entity decisions.
- Adds one-action suppression of open findings without entity text while preserving provenance.
- Preserves manually curated ResearchFinding mentions and claims across later graph re-indexing; entity changes mark dependent claims `review_required`.
- Moves Admin bulk-selection/confirmation JavaScript to a CSP-compliant external asset and removes blocked inline event handlers.
- Bulk entity curation reports total/partial failures instead of silently appearing successful.
- Adds public-repository documentation: community contribution policy, CLA without copyright assignment, Code of Conduct, commercial-licensing policy, governance, support/security guidance, issue/PR templates and release notes.
- Public project remains AGPL-3.0-only; Eboracum GmbH preserves the option to negotiate separate commercial licenses without withdrawing public AGPL rights.

## 0.8.5-rc2-graphlight-draft2 – 2026-09-17

- Findings admin now opens on **open findings** instead of the mixed Graph Inbox.
- Open findings are grouped by unresolved entity text; one finding can appear in multiple entity groups when several entity decisions remain.
- Added checkbox selection and bulk assign / bulk “not an entity” actions per entity group, with entity suggestions resolved once per group.
- Added one-action cleanup for open findings with no entity text; findings are suppressed, never deleted, so provenance remains auditable.
- Manual ResearchFinding MENTIONS survive later document relinking, including when the extractor no longer emits the curated surface form.
- Manual ResearchFinding claims survive replacement of machine-derived RelationObservations.
- Reassigning/suppressing a curated finding entity marks dependent manual claims `review_required` instead of silently leaving stale endpoints active.
- Manual claims now prefer the persisted EvidenceFrame as evidence text rather than copying the query intent.
- Regression suite: 373 tests.

## 0.8.5-rc2-graphlight-draft1 – 2026-09-17

- Experimental Graph-Lite Findings Inbox: explicit Entity Resolution from ResearchFindings into document-grounded EntityObservations/MENTIONS.
- Admin can map a finding entity to an existing Entity, create a corrected Person/Organization, or mark the candidate as not-an-entity.
- Multi-entity findings can be curated into language-neutral predicate IDs plus human-readable labels; these become document-grounded RelationObservation/Claim nodes with DERIVED_FROM_FINDING provenance, never direct global fact edges.
- Findings without entities remain auditable but are hidden from the default Graph Inbox as `no_entity`.
- Playwright renderer turns per-site navigation failures (including HTTP/2 protocol errors) into bounded HTTP 502 responses so background rendering records a failed snapshot without noisy ASGI tracebacks.
- Known mail limitation retained for follow-up: changing `mail.not_before` to an earlier date after a completed backfill does not yet reopen the historical cursor automatically.

## 0.8.5-rc2 – 2026-09-17

- Consolidate the RC1 field-test hotfixes into a fresh installable release baseline.
- Make the RAG Admin UI reverse-proxy safe by emitting path-only asset/navigation/form URLs and accepting forwarded host information for protected POSTs.
- Add background CardDAV synchronization with an Admin progress page, address-book discovery, conservative repair of malformed legacy vCards and safe deletion reconciliation after a complete successful source scan.
- Silence optional Neo4j property-key warnings by using defensive property access for sparse relationship properties.
- Add IMAP mailbox discovery to the Admin UI. Mailbox names/flags/`\Noselect` state come from the same IMAP `LIST` parser used by the importer.
- Default new mail accounts to `store_eml=false`; extend `.mailmeta.json` with raw-message SHA-256/byte length, UIDVALIDITY/import timestamp and selected technical transport/authentication headers. Attachments remain original files.
- Add `rag.mail_worker` as the common long-running scheduler for native/systemd and Docker/Super-Light. The worker re-reads enable flags and poll intervals instead of exiting when mail is disabled.
- Move optional Playwright HTML→PDF Web snapshots out of the synchronous answer path. Text evidence, metadata, fetch log and `recherche.md` are written first; sidecars transition `pending` → `complete`/`failed` in the background.
- Add `/hilfe` as a deterministic `/help` alias.
- Make leading natural instructions such as `(Nutze alle Dokumente)` reuse the complete previous document set without accidentally widening into a fresh repository search.
- Add one bounded completeness-repair pass for explicit `/use` tasks that require a row/item per selected document and omit sources. Date/value interpretation and ordering remain model responsibilities.
- Ship AKI Recherche 0.2.3: persistent per-user chats under `AKI-Chats/`, structured source references, safe Markdown tables, per-message timestamps, `/help` hint and input positioned directly after the conversation.
- Document the ACL model for private Mail/Web/Chat archives and normal Nextcloud sharing, current Findings boundaries, reverse-proxy deployment, mail provenance and background render limitations.
- Add AGPL-3.0-only release licensing files (`LICENSE`, `COPYRIGHT`, `CONTRIBUTING.md`) to the installable package.

## 0.8.5-rc1 – 2026-09-16

- Promote the simplified SearchSpec/query-rewrite pipeline and the Super-Light field-test line to 0.8.5-rc1.
- Add explicit source scopes `/documents`, `/mailarchive`, `/webarchive`, `/chatarchive` and live `/web`, orthogonal to retrieval-engine directives such as `/files` and `/vector`.
- Add persistent source-origin registry with mirrored `source_origin` filters in Elasticsearch/Qdrant, archive reconcile/restore, `.mailmeta.json`-preferred mail recovery and lightweight automatic registry-to-ES self-healing before retrieval.
- Register mail attachments as `mail_archive` at import time; archive path matching remains only a graceful recovery fallback.
- Add exhaustive verification budgets, complete `/use:all` handoff, AKI chat persistence/sidebar and Research Findings administration.
- Default `tls.x509_strict` to `false` while keeping ordinary CA/chain/hostname/validity verification enabled; `--x509-strict` explicitly enables the additional strict RFC-5280 checks.

## 0.8.4-rc3 – 2026-09-16

- Explicit completeness requests (for example “Suche alle …”) now verify up to the configured `exhaustive_verification_candidate_limit` even with a remote verifier backend. Ordinary/bounded searches retain the smaller remote safety cap. If Elasticsearch reports more candidates than the exhaustive window can verify, the answer now explicitly warns that the supposedly complete result may still be incomplete.

- Post-packaging hotfix: base the bounded-result completeness notice on the
  number of candidates actually checked by the verifier (including a lower
  remote-verifier cap), not only on the configured retrieval window.
- Add a narrow query-rewrite guard for named months: a model-generated hard
  token such as `+02` from user text `Februar 2023` is removed and the named
  month is retained as a soft lexical hint; normalized month constraints stay
  available to verification. Numeric-only user dates such as `02/2023` are
  unchanged.
- Make `Entity.entity_kind` a stable Neo4j/CardDAV property contract. New
  CardDAV persons write `Person`, unclassified organizations/units write an
  empty value, existing Entities are backfilled idempotently, and a schema
  marker creates the property token even on an empty graph. This removes the
  repeated `UnknownPropertyKeyWarning` without discarding later kind inference.
- Simplify the per-round retrieval contract again: the Query Rewriter now writes one human-style Nextcloud full-text `elastic_query` (for example `+examplehost +2025 +Rechnung`) plus one natural `semantic_query`; the middleware still compiles the former to Elasticsearch JSON and sends only the latter to Qdrant.
- Preserve `entities`, `concepts`, `constraints` and `verification_requirements` as analytical side-products of the same rewrite call. They feed Candidate Verifier, RetrievalRecord and Graph-Light provenance but no longer silently manufacture Elasticsearch MUST clauses.
- Supply compact Neo4j seed/alias context to the Query Rewriter before it writes the search expression. Reuse that same context in the API request so entity resolution is not repeated in the same retrieval round.
- Keep retrieval rounds as an optional outer controller. Later rounds may revise the same SearchSpec after seeing the bounded result picture; there is still no separate probe language in the normal provider path.
- Execute `elastic_query` with the proven Nextcloud QueryContent semantics (`+` required, `-` excluded, quoted expressions preserved; content OR title), while the natural-language user sentence is never injected as a broad Elasticsearch ranking clause.
- Add explicit `verification_requirements` to the verifier prompt. This allows the rewrite to retain intent such as “the document itself must be an invoice” or “the relevant invoice date is February 2021” without guessing a literal text encoding such as `02-2021`.
- Update the query-rewriter prompt with regression examples for `examplehost`/2025 and February 2021, including the rule not to invent concrete date spellings that are not implied by the user request or known seeds.
- Keep rc2 compatibility fields accepted by the API for stored/external SearchSpec callers, but the rc3 provider no longer emits them.
- Regression suite now contains 344 tests including the post-packaging hotfix regressions.

## 0.8.4-rc2 – 2026-09-15

- Replace the normal RC8 multi-probe planner path with one backend-neutral `SearchSpec` per retrieval round. The Query Rewriter emits lexical fields plus `semantic_query`; it no longer emits Elasticsearch/Qdrant control syntax.
- Use Neo4j CardDAV/curated seeds as entity/alias expansion for the SearchSpec. Neo4j is no longer an automatic document-retrieval arm in the normal path; explicit graph diagnostics remain available.
- Compile SearchSpec lexical fields deterministically to Elasticsearch and route only `semantic_query` to Qdrant when the vector arm is enabled. Super-Light therefore follows the same code path with Qdrant disabled rather than a separate planner strategy.
- Keep retrieval rounds as an optional outer controller. Round 1 always rewrites once; `retrieval_planner.enabled` (legacy config section name) now controls only additional rounds, and every later round reuses the same SearchSpec → ES/Qdrant → fusion pipeline.
- Fail closed when a files SearchSpec cannot be produced after one retry instead of sending the original natural-language sentence to Elasticsearch. Explicit years/dates/identifiers/filenames are deterministically retained as safe literal constraints.
- Log the effective SearchSpec, the actual Elasticsearch JSON query and compact ranked ES hit metadata for the normal path so administrators can trace a retrieval without enabling verbose third-party logging.
- Fix candidate-pool truncation when no reranker is configured: bounded Super-Light retrieval can now actually deliver its configured 30 authorized candidates to the verifier instead of being capped by `rerank_candidates=10`.
- Keep the document-type verifier rule from the rc1 planner hotfixes: a document that merely mentions an invoice is not itself an invoice.
- Retain legacy `/multi-search`/probe code only for compatibility and diagnostics; the normal provider path no longer calls it.
- Add SearchSpec/Neo4j-expansion/backend-compilation regression coverage; full suite now contains 336 tests before packaging validation.

## 0.8.4-rc1 planner hotfix 3 – 2026-09-15

- Separate planner intent from retrieval-backend syntax: the structured QueryFrame is now compiled deterministically for the files/Elasticsearch arm, while the original natural-language question is reserved for semantic/vector retrieval and graph resolution when those arms exist.
- In Super-Light/files-only mode a valid bounded QueryFrame such as `concept=Rechnung`, `entity=examplehost`, `year=2025` produces only the exact files probe `+Rechnung +examplehost +2025`; the natural-language sentence is no longer added as a competing Elasticsearch probe.
- Semantic probes can no longer silently fall through to Elasticsearch when the vector arm is unavailable. Model-generated lexical/strict probes are ignored when the deterministic QueryFrame files compiler succeeded; they remain only as a fail-open recovery path for an unusable frame.
- Tighten candidate verification for requested document types: a document must itself be of the requested type; a bank statement, booking, attachment or reference that merely mentions an invoice is not an invoice match.
- Add regression coverage for Super-Light arm separation, QueryFrame compilation and planner-failure fallback.

## 0.8.4-rc1 planner hotfix 2 – 2026-09-15

- Execute files-only `strict_lexical` probes through the Nextcloud-compatible exact Elasticsearch path instead of the broad RAG lexical planner. Valid multi-MUST Boolean probes are defensively recognized even if a provider/model labels them incorrectly.

## 0.8.4-rc1 planner hotfix 1 – 2026-09-15

- Harden retrieval-planner probe normalization: Boolean `+/-` control syntax is accepted only for `strict_lexical`; a mislabeled but valid Boolean probe is recovered as an Elasticsearch strict view when the files arm is available, while vector/semantic views receive plain text.
- Canonicalize simple model output such as `+(Rechnung)` to the supported `+Rechnung` syntax; malformed/weak Boolean output is downgraded instead of leaking control characters into semantic/lexical views.
- For concretely bounded document-set requests, instruct the planner to prefer a strict lexical view containing the normalized document type, distinguishing named anchors and explicit safe constraints (e.g. `+Rechnung +examplehost +2025`). The deterministic entity+constraint strict probe remains only as a fallback when the model does not produce a valid strict view.
- Add regression coverage for the observed Super-Light query `Suche Rechnungen von examplehost aus dem Jahr 2025`.

## 0.8.4-rc1 – 2026-09-15

- Promote the dockerized Super-Light stack to the 0.8.4 beta candidate while keeping functional profile (`standard`/`super-light`) and deployment mode (`native`/`dockerized`) as separate axes. Tested mappings remain `standard+native` and `super-light+dockerized`.
- Add per-Nextcloud-user CardDAV seed administration. RAG Admin → Users → Kontakt-DB stores enable/include/exclude settings and last sync status, reuses the existing Login-Flow credential, and treats missing credentials/empty sources as clean no-ops. New `rag.contacts` / `install/super-light/contacts.sh` CLI uses the human Nextcloud login; canonical UUIDs stay internal.
- Add the missing Neo4j `ContactRecord.addressbook_slug` index to avoid noisy unknown-property warnings.
- Move the Playwright renderer to the shared `install/components/` area. Default web snapshots use a 1440×900 desktop viewport and A4 landscape, retry bounded consent cleanup once before capture, and persist isolated browser storage state per requested host in a Docker volume. Login/paywall/CAPTCHA bypass remains out of scope.
- Record landscape/viewport and browser-state reuse/persistence in hidden per-source metadata alongside cleanup provenance.
- Raise the Super-Light normal verification window from 6 to 10 documents; the reranker remains disabled.
- Translate temporary Elasticsearch transport failures to HTTP 503 and a user-facing “Dokumentensuche derzeit nicht verfügbar” response instead of a generic API 500/provider 502.
- Tighten the natural-instruction compiler prompt/schema so singular ordinal references such as “das erste Dokument” compile to selected source `1`, not `all_previous`.
- Improve installer completion output: print admin credentials/provider API key location, identify LLM/Web secret files, and replace legacy CardDAV password guidance with per-user Kontakt-DB/CLI instructions.
- Bundle AKI Recherche 0.2.1 with correct `<navigations>` registration and a dedicated compact SVG navigation icon.
- Refresh installation, administration and technical documentation. The measured Leap 15.3 Super-Light acceptance VM used ~1.7 GiB / 44% of 3.9 GiB RAM at idle with ~99% CPU idle and no swap; 4 GiB is documented as a practical minimum, 4–8 GiB recommended.
- Add a concise Beta Operations runbook and Known Limitations document after clone acceptance; document successful Super-Light/Kontakt-DB acceptance, synchronous contact-sync UI progress, CA-path preflight limitation, reranker-independent deduplication and the post-0.8.4 architecture freeze.

## 0.8.3-rc11 web-renderer hotfix 1 – 2026-09-15

- Add bounded best-effort Playwright page cleanup before PDF archiving: accept common cookie-consent dialogs, dismiss harmless modal/overlay prompts, and keep DOM removal disabled by default.
- Record renderer cleanup provenance in each hidden per-source `.metadata.json` (`cookie_consent`, action counts, dismissed/removed overlays, `dom_modified`).
- Keep cleanup page-generic and bounded; no site-specific paywall/loginwall bypass logic is added. Each render still uses a fresh browser context, so accepted cookies are not persisted between research fetches.

## 0.8.3-rc11 – 2026-09-14

- Add a bounded `retrieval_policy` layer: internal arms are `required`, `optional` or `disabled`; planner failures use deterministic `optional_default`; Web policy is `disabled`, `explicit` or `planner`. Resource budgets remain administrator-controlled.
- Retrieval-planner structured output may select permitted optional arms and may emit conservative `strict_lexical` Elasticsearch recall probes. Obvious grammatical normalization is allowed for those probes; factual synonym invention is still prohibited.
- Add central `tls.x509_strict` compatibility control for Python 3.13. Setting it false preserves CA/chain/SAN/hostname/validity verification while removing only `VERIFY_X509_STRICT`, consistently across stdlib/httpx and requests/urllib3 paths.
- Dockerized super-light installer adds `--no-x509-strict` and retains repeatable `--ca-certificate`; fresh Leap 15.3 installation is the compatibility baseline.
- Expose profile and deployment as orthogonal installer concepts (`--profile`, `--deployment`) while supporting only regression-tested `standard+native` and `super-light+dockerized` combinations in RC11.
- Bundle AKI Recherche 0.2.0 for Nextcloud 23+: safe Markdown subset, links, failure retry, per-question **Erneut senden** and **Bearbeiten & erneut senden** branching.
- Clarify that CardDAV credentials are optional one-account graph-seed credentials, not normal AKI authentication or live-ACL credentials.

### rc10 install hotfix 5

- Super-light base Compose contains only core services; optional OpenWebUI/nginx are generated in `docker-compose.override.yml`, so a later plain `docker-compose up` cannot unexpectedly start OpenWebUI.
- Super-light web capability defaults to globally enabled; missing Brave/SearXNG configuration is reported as `unconfigured` and does not degrade internal retrieval.
- Web passage selection skips the reranker directly when `reranker.backend=none`, avoiding misleading warning logs in super-light mode.


## 0.8.3-rc10 install hotfix 4

- Super-light bundled nginx: make the bind-mounted htpasswd file readable by the unprivileged nginx worker. The file contains only the salted password hash; the previous 0600 root-only mode caused HTTP 500 after the Basic Auth prompt.

### RC10 install hotfix 3

- Add explicit `Jinja2` runtime dependency to standard and super-light requirements. The admin UI imports Starlette `Jinja2Templates`; without the optional Jinja2 package the API container exits at startup.

## RC10 install hotfix 2

- Super-light provider image no longer expects `provider.env.example` inside the installed build context.
- Suppress the expected pip-as-root warning inside the container image build; host Python remains unused.
- Super-light `--plan` reports an approximate disk-use range and makes clear that OpenWebUI is not pulled or started unless explicitly requested.


Entries below 0.8.5-rc3 document internal development candidates used during field testing. They were not published as public upstream releases; 0.8.5-rc3 is the first public release candidate.

## 0.8.3-rc10 installation hotfix 1 – 2026-09-14

- one public installer entry point: `install/install.sh --profile standard|super-light`;
- super-light no longer requires host Python and is reachable through the same installer;
- legacy Compose compatibility: super-light uses Compose file format 2.4 (tested structurally for the Leap 15.3 / docker-compose 1.25.x target);
- OpenWebUI and bundled nginx are opt-in in super-light instead of starting implicitly;
- super-light registers its generated provider key as `default-client` in the credential store;
- old `install/super-light/install-super-light.sh` remains as a forwarding compatibility shim.

## 0.8.3-rc10 – 2026-09-13

- Folded the super-light variant back into the common middleware codebase. Super-light is now an installation profile, not a fork: Elasticsearch-only retrieval, no Qdrant/embedding/reranker, Neo4j retained for seeds/aliases and lightweight research findings.
- Added the side-effect-free `check-config.sh` / `rag.config_check` validator. Impossible profile combinations are errors; technically valid but weaker combinations such as Elasticsearch + Qdrant without a reranker remain warnings because RRF can still fuse the arms.
- Added **AKI Recherche** research findings: the provider reuses the already-produced retrieval-planner `query_frame` and positive Candidate-Verifier `evidence_frame` and persists only `match` + `direct` document findings to Neo4j. No additional LLM or graph-extraction pass is started.
- Research findings are provenance-bearing observations, not global truth edges. Planner relations stay on the `ResearchFinding` node; existing graph entities are linked only on a unique exact query-side name/alias resolution. Rejected and uncertain document/query pairs are never stored.
- Findings coalesce by canonical query-frame hash + document ID, track first/last observation and count, and are batch-written to keep the super-light path inexpensive. Raw user-question text is not copied into research-finding nodes.

## 0.8.3-rc9 – 2026-09-12

- Removed runtime model-name sniffing from the embedding layer. `query_prefix` and `document_prefix` now define retrieval-role formatting explicitly and work with arbitrary embedding models.
- `embedding.profile` is now diagnostic metadata only. Neither `auto` nor legacy profile labels select prefixes or runtime behavior; only explicit `query_prefix` / `document_prefix` values do.
- Made the vector index signature depend on document-affecting inputs rather than the diagnostic profile label; changing only a query prefix does not require re-embedding the corpus.
- Kept the reference configuration on `qwen3-embedding:4b` / 1024 dimensions, but Qwen is now a replaceable default rather than a runtime special case.

## 0.8.3-rc8 – 2026-09-12

- Changed the reference local embedding model to `qwen3-embedding:4b` while keeping Qdrant vectors at 1024 dimensions through the Ollama `/api/embed` `dimensions` parameter.
- Added fail-closed embedding-dimension validation and included dimensions in the per-document vector index signature.
- `embedding.profile: auto` now selects a Qwen3 retrieval profile for `qwen3-embedding*`: queries receive the recommended query-only retrieval instruction while corpus documents remain uninstructed.
- Added optional basename-aware document embedding (`sync.embedding_include_basename`, default true): the basename is added only to model input; stored Qdrant evidence text remains unchanged.
- Added `--embedding-url` one-run overrides to `rag.sync` and `rag.qdrant_smoke`, allowing a GPU Ollama for the initial full sync while the persistent configuration continues to point at a CPU Ollama.
- Bundled the standalone `helpers/fts_reconcile` Nextcloud maintenance utility (0.2.0) for dry-run FTS/filecache reconciliation with reversible pre-index `--unreconcile`.
- Includes the rc7 Web Research archive additions: fetch log, per-source metadata and optional fail-open Playwright screen-PDF rendering.

## 0.8.3-rc7 – 2026-09-12

- Added provenance-complete Web Research archiving: `fetch-log.jsonl` records every attempted/fetched search result with requested/final URL, HTTP status, redirects, content hash, fetch outcome and relevance decision.
- Added per-selected-source `.metadata.json` files with retrieval, relevance and archive metadata.
- Added optional fail-open integration with the local `rag-playwright-renderer`: selected HTML sources can be archived as screen-CSS PDFs, while original PDFs remain unmodified.
- Render failures never invalidate text evidence or the Web Research answer; they are reported as archive-stage errors.
- Web source output now exposes archived PDF and metadata paths in addition to the text snapshot/original payload.

## 0.8.3-rc6 – 2026-09-12

- Fixed bounded document-set recall so hard literal filtering no longer happens only after broad top-K truncation.
- Added a deterministic ES-only strict recall probe for bounded searches when the planner identifies an explicit entity plus a safe literal constraint (for example `+examplehost +2025`).
- Strict bounded probes use conjunctive MUST semantics and participate alongside the existing broad lexical/vector/graph probes; they improve recall without claiming exhaustive completeness.
- Added regression coverage for bounded strict-probe generation and ES-only routing.

## 0.8.3-rc5 – 2026-09-12

- Added early safe-literal recall filtering for explicit years, dates and structured identifiers before probe RRF and Cross-Encoder reranking, preventing other-year documents from consuming the bounded candidate pool.
- Added a bounded document-set mode for queries such as `Rechnungen von examplehost aus dem Jahr 2025`: these use a larger configurable verifier window without claiming exhaustive completeness.
- Added `retrieval_planner.bounded_verification_candidate_limit` (default 30) and differentiated the candidate-limit notice for already bounded queries.
- Added regression coverage for year-constrained recall filtering and bounded document-set detection.

## 0.8.3-rc4 – 2026-09-12

- Fixed deterministic `/use:<filename>` resolution for Nextcloud FullTextSearch mappings where the searchable filename is present in `combined` but not queryable through `title`.
- `/use` now applies the current Nextcloud Live-ACL/existence check before deciding whether an exact filename or path is unique, so stale Elasticsearch rows for deleted files cannot create false ambiguity.
- Added regression coverage for stale-index and ACL-visible ambiguity cases.

## 0.8.3-rc3 – 2026-09-12

- Simplified the end-user help text; `/health` no longer exposes operational details in chat, while natural help aliases such as `Help`, `Hilfe`, `Aide`, `Ayuda`, `Aiuto` and `Pomoc` resolve to `/help`.
- Made exact `/use:<filename>` resolution tolerant of analyzed Elasticsearch `title` mappings while retaining strict basename/path selection semantics.
- Added a user-visible notice when normal candidate verification leaves additional ranked candidates unchecked because of the verification window.
- Added a cheap provider `/live` endpoint and switched `status.sh` to liveness so status checks no longer depend on remote LLM probes.
- Narrowed nginx `/auth/` routing to the Nextcloud auth namespace so OpenWebUI logout/auth routes remain with OpenWebUI.
- Added an optional CPU Ollama/TEI helper compose example for `/opt/rag-helper`.
- Documented the tested `overlay2` workaround for Docker/containerd image-store extraction failures on affected Leap 16 VM/Btrfs combinations.

## 0.8.3-rc2 – 2026-09-11

- Added role-based LLM backend routing for planner, verifier, evidence control and answer generation while retaining the rc1 default backend as a compatibility fallback.
- Added explicit remote-evidence budgets and surfaced role/backend trust-boundary information in provider health.
- Graph auto-processing is now independently switchable from graph capability; mail worker start is independently switchable from mail capability.
- Improved OpenWebUI first-start waiting, smoke-test progress feedback and TEI reranker installation behavior.
- Fixed Web Research admin UX, disabled-message wording, archive target default, error-page back navigation and archive TLS documentation; raw HTML archiving now defaults off.
- Added timing diagnostics for Web Research stages and clearer operational documentation for Docker named volumes and private Elasticsearch backend networks.

## 0.8.3-rc1 – 2026-09-11

Internal release candidate used during pre-public field testing (not publicly released).

Highlights:

- hybrid Elasticsearch/Qdrant retrieval with bounded multi-probe planner and candidate verification;
- live Nextcloud ACL authorization before evidence reaches the answer model;
- optional document-grounded Neo4j/GraphRAG signals and curator UI;
- OpenAI-compatible provider with configurable local or remote LLM backends;
- optional Brave/SearXNG Web Research with relevance gating and Nextcloud archiving;
- per-user IMAP ingestion with one Nextcloud directory per message and optional attachment storage;
- periodic Elasticsearch-to-Qdrant synchronization;
- canonical multi-user identity model and trusted frontend clients;
- AES-256-GCM encryption for reversible Nextcloud/IMAP credentials and Login Flow poll tokens;
- cleaned RAG Admin information architecture with separate Overview, Users, Graph and Security areas;
- fresh-install repository baseline and reproducible pytest configuration.

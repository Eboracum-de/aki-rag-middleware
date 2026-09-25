# Release notes – 0.8.6-rc1.1

**Status:** release candidate hardening update  
**Date:** 24 September 2026  
**Public predecessor:** `0.8.6-rc1`

0.8.6-rc1.1 is a focused hardening update following the full public release-diff
review of 0.8.6-rc1. It does not change the three shipped research-profile budgets
or the live-Nextcloud-ACL authorization model.

## Security and privacy hardening

- Role-specific LLM routing now reclassifies `local|remote` scope when a SunaQ
  profile changes the role endpoint unless that profile explicitly sets `scope`.
  This prevents a stale inherited `local` scope from bypassing remote evidence
  limits after routing a role to a remote backend.
- Normal INFO retrieval logging no longer records rewritten search terms, entities,
  concepts, constraints or model-provided rewrite reasons. It retains only bounded
  control/count metadata.
- SunaQ Recherche requires HTTPS for credential-bearing middleware requests by
  default. Plain HTTP is available only through an explicit administrator opt-in
  for controlled test/lab networks.
- Bundled nginx gives the externally reachable OpenAI-compatible `/v1/` surface
  its own per-source-IP request bucket (10 requests/s, burst 30) and a 16-connection
  concurrency limit, returning HTTP 429 when exceeded. Persistent account lockouts
  are intentionally avoided because they can themselves be abused for denial of
  service.

These proxy controls bound application pressure, not volumetric DDoS. The provider
should remain on loopback/private service networking; Internet-facing deployments
still need appropriate upstream firewall/load-balancer/provider protection.

## Minimal-by-default deployment boundary

Fresh installations start close to the **Secure RAG Core (SRC)** baseline:
ordinary Nextcloud documents → FullTextSearch/Elasticsearch → live Nextcloud ACL
→ LLM. Local model processing is preferred; bounded external model endpoints are
also possible where administrators explicitly accept and manage data egress.

The wider **Eboracum Research Gate (ERG)** capabilities remain inactive until an
administrator opts in:

- global Web Research is off and Web archive persistence is off;
- Playwright is not built or started by Super-Light unless
  `--with-playwright` is supplied;
- the mail worker is not started while mail/worker configuration is disabled;
- chat archives are not usable as RAG evidence until
  `chat_archive.enabled=true`;
- Research-Finding persistence defaults to off;
- the bundled SunaQ client starts with Documents only rather than Documents +
  Mail.

ERG is an opt-in capability set rather than a monolithic mode. Features such as
Web/Mail/Chat sources, semantic retrieval/reranking, Findings/Graph-Lite, full
graphization or additional retrieval rounds may add retained state, untrusted
input, egress, latency and lifecycle obligations. rc1.1 documents this structure;
explicit SRC/ERG installer/configuration support remains an rc1.2 target.

## Policy/inspection hook scaffold

- Add a shared `rag.policy_hooks` contract with `outbound_query`,
  `pre_fetch`, `post_fetch`, `pre_persist` and `pre_model_egress` stages
  plus `ALLOW | BLOCK | QUARANTINE | MODIFY` decisions.
- Wire the stages into Web search/fetch/Playwright, Web-archive persistence,
  IMAP message/attachment import, Mail-archive persistence and LLM/embedding
  backend calls.
- rc1.1 installs no policy evaluator, so all hooks are ALLOW-only and preserve
  current runtime behavior. Concrete scanner/DLP/URL-policy adapters and
  administrator configuration remain deferred.

This scaffold is not a malware/DLP/filtering guarantee; it creates stable
trust-boundary insertion points so later adapters do not require another
data-flow redesign.

## Runtime correctness

- Explicit specialist context budgets remain explicit even if they numerically
  equal a legacy provider default; omitted arguments are now represented by
  `None` rather than value-equality sentinels.
- Partial profile reranker settings are merged over global defaults.
- An effective reranker configuration identical to the warmed global configuration
  reuses that instance instead of loading a duplicate local model.
- Model aliases may no longer collide with model IDs regardless of profile
  directory/load order.
- `/help` now matches the client-neutral implicit source default: ordinary
  documents only; mail, Web and chat archives are opt-in.

## Chat archive administration

SunaQ Recherche 0.3.4 uses exactly one configured chat-archive path per canonical
user. The default is `SunaQ-Chats`. A per-user enable/disable switch is layered
below the global `chat_archive.enabled` gate; existing settings migrate enabled
to preserve prior behaviour.

This deliberately avoids permanent dual-root legacy logic. Operators with an older
RC archive may either configure that user to keep using `AKI-Chats` or move the
archive files once into the selected SunaQ path. Changing the setting does not move
files automatically. Legacy `.akirag.json` / HTML records remain readable when
present inside the selected archive.

The provider now exposes effective authenticated source capabilities through
`/v1/user-settings`. The bundled app renders optional source chips fail-closed:
they start hidden and are shown only after the authenticated capability response
confirms that they are globally enabled and enabled for the current user. The same capability policy
is enforced server-side, so explicit Slash-Directives cannot bypass an
administrator-disabled Mail/Web/Webarchive/Chat source. The app writes new archive files only while both the
global and per-user chat capability are enabled; a settings failure fails closed
for persistence. Rename operations use the same fail-closed capability check
before rewriting or registering archive content. Manual deletion of a managed Markdown chat removes
the matching hidden metadata sidecar
through a Nextcloud file-delete listener, with list/load orphan cleanup as a repair
fallback.

When Research Findings are enabled, explicit `/use` document selection now also
feeds Findings through a separate structured rewrite + Candidate-Verifier side
pipeline. This does not change the directly selected answer context; only positive
`match` + `direct` verifier observations are persisted. The optional Findings
pass is scheduled only after the user-facing answer has been generated, keeping
its planner/verifier work off the answer-generation critical path.

## Packaging and documentation

- Standard and Super-Light now agree on the pinned optional OpenWebUI
  `v0.11.4-slim` image; Arena models remain disabled.
- `versions.lock.yaml` is aligned with the rc1.1 baseline.
- Support, administration, beta-operations and technical-reference documentation
  are updated for the SunaQ naming, chat-archive policy and rc1 validation state.
- SRC (Secure RAG Core) and ERG (Eboracum Research Gate) are documented as a
  target architecture concept; supported presets/enforcement are deferred to
  rc1.2.
- Fresh Standard and Super-Light installs no longer require a generated Playwright
  seccomp file when the renderer is not selected. `--with-playwright` prepares
  and selects the verified profile before Compose is invoked.
- Restore executable Git modes on the Standard and Super-Light profile installers; the public installer wrapper executes these scripts directly.
- Historical 0.8.5 release notes remain unchanged as historical records.

## Validation

The rc1.1 branch adds targeted regression coverage for the findings above. Final
promotion remains conditional on the normal GitHub CI, repository hygiene and
post-change review checks.

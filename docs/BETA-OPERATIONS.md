# Beta operations runbook

**Reference:** `0.8.5-rc3`  
**Target:** controlled beta deployment behind an administrator-managed network boundary

This document is the short operational path for the current beta candidate. For
full configuration details see `TECHNICAL-REFERENCE.md`; for identity/credential
administration see `ADMINISTRATION.md`.

## 1. Supported deployment matrix

0.8.5 keeps functional profile and deployment mechanism separate, but only two
combinations are regression-tested and accepted for the beta:

| Functional profile | Deployment | Status |
| --- | --- | --- |
| `standard` | `native` | supported/tested |
| `super-light` | `dockerized` | supported/tested |
| `standard` | `dockerized` | not a 0.8.5 supported mapping |
| `super-light` | `native` | not a 0.8.5 supported mapping |

Super-Light is one configuration of the same middleware, not a fork. It expects
Nextcloud, its FullTextSearch Elasticsearch and the LLM endpoint to be external.
Locally it runs API, provider, Neo4j Graph-Lite and Playwright; bundled nginx is
optional. Qdrant and the local reranker are disabled.

## 2. Super-Light installation

Inspect the plan first:

```bash
sudo ./install/install.sh \
  --profile super-light \
  --deployment dockerized \
  --nextcloud-url https://cloud.example/nextcloud \
  --elasticsearch-url http://10.0.0.20:9200 \
  --elasticsearch-index my_index \
  --with-proxy \
  --plan
```

For an internal PKI, add one `--ca-certificate FILE` for each root/intermediate
PEM certificate. If the chain is trusted but Python 3.13 rejects an older
certificate only because strict RFC-5280 checks require an Authority Key
Identifier, additionally use `--no-x509-strict`:

```bash
sudo ./install/install.sh \
  --profile super-light \
  --deployment dockerized \
  --nextcloud-url https://cloud.example/nextcloud \
  --elasticsearch-url http://10.0.0.20:9200 \
  --elasticsearch-index my_index \
  --ca-certificate /secure/Company_Root_CA.crt \
  --no-x509-strict \
  --with-proxy \
  -y
```

`--no-x509-strict` does **not** disable normal CA-chain, hostname/SAN, signature
or validity checks. Do not replace it with `verify_tls:false` in normal operation.

Current small limitation: CA file validation is not the first global installer
preflight. A typo can therefore abort after some setup steps. Correct the path and
rerun; the installer is designed to be rerunnable.

## 3. First post-install configuration

The installer prints the RAG Admin credential and provider API key and records the
local runtime values in `/opt/nextcloud-rag/runtime.env`. Treat that file as a
secret. Configure the actual LLM and optional Web Search credentials before user
acceptance.

Useful Super-Light commands:

```bash
cd /opt/nextcloud-rag/install/super-light
./status-super-light.sh
docker-compose ps
docker-compose logs --tail=100 api provider
docker-compose restart api provider
docker-compose logs -f mail-worker
```

Do not edit credential rows in `runtime/users.sqlite` with ad-hoc SQL. Use the
Admin UI or supplied CLIs.

## 4. AKI Recherche 0.2.3

AKI is the preferred slim Nextcloud UI for this beta. It targets Nextcloud 23+.
Install the `akirag` app in Nextcloud, enable it, then configure **Middleware URL**
and **Provider API key** under **Settings → Administration → Additional settings**.

The app proxies server-side and sends the current Nextcloud UID; the provider key
never reaches browser JavaScript. Each user completes Nextcloud Login Flow once so
the middleware can perform live ACL checks with that user's current credential.

If the middleware URL is an RFC1918/private address, Nextcloud can reject the
server-side request with `Host violates local access rules`. For a deliberately
internal deployment set the global Nextcloud option `allow_local_remote_servers`
to true and make sure the Nextcloud host trusts the middleware TLS issuer.

## 5. Contact seeds / Graph-Lite

After a user has completed Login Flow, open:

```text
RAG Admin → Users → <Nextcloud login> → Kontakt-DB
```

Enable/configure the source and choose **Jetzt synchronisieren**. CardDAV uses the
already stored Nextcloud credential; no second CardDAV password is needed. The
operational identity is the human Nextcloud login; `canonical_user_id` remains an
internal join key.

CLI equivalent:

```bash
cd /opt/nextcloud-rag/install/super-light
./contacts.sh list
./contacts.sh status --user alice
./contacts.sh books --user alice
./contacts.sh sync --user alice
```

Use `--server URL` only when the same login exists on multiple Nextcloud servers.
Missing credential, disabled seed source and empty address book are clean no-ops.

The Admin UI starts the contact import as a background job and shows a progress bar with processed/total, written, repaired, removed and error counts. **Adressbücher ermitteln** lists the CardDAV display name and technical slug accepted by include/exclude filters. A full successful scan also removes ContactRecords whose CardDAV href disappeared; parse failures are still counted as seen and are not mistaken for deletions.

## 6. Retrieval behavior in Super-Light

Super-Light uses Elasticsearch as the required document arm and Neo4j for
entity/alias expansion and lightweight research findings. Qdrant and the local
reranker are disabled.

Every normal request first produces one small small SearchSpec. In
Super-Light its lexical fields are compiled to Elasticsearch; `semantic_query`
is retained for portability but is not executed because Qdrant is disabled.
Neo4j may add known seed/alias forms before the Elasticsearch request. The actual
Elasticsearch JSON query is logged at INFO for this path. Additional retrieval
rounds use the same SearchSpec pipeline and are disabled simply by setting
`max_retrieval_rounds: 1` (or by disabling additional rounds in the legacy-named
`retrieval_planner` section).

The absence of a reranker does **not** disable deduplication. Near-identical text
and common PDF/ODT/copy variants are collapsed before the final candidate path.
The normal verifier window is 10 authorized candidates in Super-Light (6 in the
standard reference profile); bounded/exhaustive requests use separate configured
limits.

Live Nextcloud ACL remains mandatory. Unauthorized results are removed and are not
backfilled with lower-ranked documents merely to fill the context.

If Elasticsearch is unavailable, the API returns service-unavailable semantics and
the UI should show `Dokumentensuche derzeit nicht verfügbar` rather than exposing a
generic 500/502 as the user-facing result.

## 7. Web Research and archive

The shared Playwright renderer uses a 1440×900 desktop viewport and A4 Landscape
PDF. In RC3 rendering is archival enrichment scheduled after the synchronous evidence/archive write, so slow Chromium rendering does not block the user answer. Cookie/harmless-overlay handling is bounded best effort; ordinary browser
storage can persist per requested host so a consent choice may survive future
captures. The archive deliberately does not bypass login walls, paywalls,
CAPTCHAs or access restrictions.

Per-source metadata JSON is stored as a hidden dotfile, for example:

```text
.01-source.metadata.json
```

The PDF is a readable research snapshot, not WARC/WACZ or a forensic browser
archive. Raw HTML, when enabled, is only the fetched main response and does not
bundle every subresource.

## 8. Acceptance checklist before opening the beta

Use at least one real account with ordinary documents and one second account with
different ACLs.

1. `status-super-light.sh` reports API/provider/Neo4j/Playwright ready.
2. AKI appears in Nextcloud navigation and opens without manual URL entry.
3. User 1 completes Login Flow and can query an authorized document.
4. User 2 cannot receive evidence for a document they cannot access.
5. Kontakt-DB sync succeeds for one user; Neo4j shows ContactRecords/provenance.
6. A normal document question works with the Super-Light 10-candidate verifier window.
7. A Web Research run archives a source as desktop/Landscape PDF plus hidden metadata.
8. Stop Elasticsearch temporarily and verify the friendly unavailable response.
9. Restore Elasticsearch and verify retrieval recovers without state repair.
10. Run `docker-compose down` / `docker-compose up -d` and repeat one document and one Web query.

The Leap 15.3 beta host exercised the underlying RC2 field paths carried into RC3 for document retrieval, CardDAV import/reconciliation, Web Research archive creation, IMAP→WebDAV mail import with attachments/OCR and the long-running Docker mail worker. RC3-specific Findings/Admin publication hardening is regression-tested; rerun this acceptance checklist before production rollout.

## 9. Resource reference

Observed on the Super-Light acceptance VM:

```text
assigned RAM:      ~3.9 GiB
idle RAM in use:   ~1.7 GiB / 44%
CPU idle:          ~99%
load average:      ~0.09 / 0.09 / 0.08
swap:              none
```

This is an observed test point, not a guaranteed ceiling. 4 GiB is a practical
minimum for the tested profile; 4–8 GiB is recommended when Chromium/Web Research
will be used. Nextcloud, Elasticsearch and the LLM are external in this figure.

## 10. Beta freeze

0.8.5-rc3 is the consolidated deployment/operations baseline for the next beta iteration.
Expected follow-up work is primarily query-rewrite/retrieval-round/retrieval quality
and small UI/operator improvements. A change that alters the trust model, live ACL
invariant, credential ownership, deployment axes or evidence pipeline should be
treated as an architectural change and not slipped into a retrieval-quality patch.


## Source-origin mirror and reconcile

Archive scopes (`/mailarchive`, `/webarchive`, `/chatarchive`) filter on mirrored `source_origin` values before the Elasticsearch/Qdrant candidate windows. The middleware registry keyed by Nextcloud `files:<id>` is the durable source of truth for special archive origins. Normal retrieval performs a lightweight id-based mirror repair whenever the registry changes; this avoids a full index scan in Super-Light.

A full Elasticsearch reset/reindex is explicit administrator work. Afterwards run:

```bash
cd /opt/nextcloud-rag/install/super-light
docker-compose exec api python -m rag.source_registry reconcile
```

For native/standard deployments run the equivalent module with the installed venv. Reconcile prefers `.mailmeta.json` membership data for mail recovery, then falls back to the normalized `CONTENT-KIND: EMAIL` marker and configured archive roots.

## TLS strict mode

Normal TLS verification is enabled by default. `tls.x509_strict` defaults to `false` for compatibility with older private PKIs; this only disables the additional Python/OpenSSL `VERIFY_X509_STRICT` flag. Use `--x509-strict` to opt into strict RFC-5280 checks. Do not use `verify_tls: false` as a substitute.

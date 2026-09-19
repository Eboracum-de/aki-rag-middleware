# Super-light installation profile (0.8.5-rc4)


0.8.5-rc4 uses X.509 strict mode **off by default** while normal TLS certificate/hostname verification remains enabled. Use `--x509-strict` only for PKIs that require and satisfy the additional strict checks.
The profile uses legacy Compose file format **2.4** so it also works with the `docker-compose 1.25.1` commonly found on Leap 15.3. OpenWebUI and the bundled nginx proxy are disabled by default; add `--with-openwebui` and/or `--with-proxy` explicitly.

This deployment is intended for small/older Linux hosts where the middleware
should reuse an existing Nextcloud FullTextSearch Elasticsearch index without
running an embedding model or a CrossEncoder reranker.

## Retrieval profile

- **Elasticsearch:** document retrieval arm.
- **Neo4j:** CardDAV/contact seeds, known entities and aliases only. Entity
  resolution contributes weighted Elasticsearch phrase expansions.
- **Graph document retrieval:** disabled.
- **Automatic graph extraction:** disabled.
- **AKI Recherche findings:** enabled; positive planner/verifier results are batch-written to Neo4j without another model call.
- **Qdrant / embeddings / sync worker:** disabled and not installed.
- **Reranker / TEI / transformers:** disabled and not installed.
- **Deduplication:** remains enabled independently of the reranker, so PDF/ODT/copy
  variants do not unnecessarily consume the normal 10-candidate verifier window.
- **Live Nextcloud ACL:** unchanged and remains the authorization boundary.
- **Verifier/answer LLM:** configurable as in the full stack. Only the bounded
  post-retrieval evidence is sent to a remote role; the corpus itself remains
  in Nextcloud/Elasticsearch.
- **Mail worker:** common `rag.mail_worker` scheduler in its own Compose service when mail is enabled.
- **Playwright:** local fail-open screen-PDF renderer for selected web sources; HTML→PDF work is queued after answer evidence/archive creation.

The normal verifier window in this profile is **10 authorized candidates** (standard remains 6).

The API and OpenAI-compatible provider run from the same Python 3.13 container
image. Neo4j and the Playwright renderer are containerized as well. The host
therefore does not need Python >=3.10; this is specifically useful for openSUSE
Leap 15.3. In packaging terms this is the `dockerized` deployment mode with a
`super-light` functional configuration, not a separate middleware fork.

## Memory target

The compose profile deliberately caps Neo4j at 512 MiB heap with a 256 MiB
page cache. A Leap 15.3 acceptance VM with 3.9 GiB assigned RAM used roughly
1.7 GiB / 44% at idle with about 99% CPU idle and no swap. This is an observed
test point, not a guaranteed ceiling. 4 GiB is therefore the practical minimum
for this profile; 4–8 GiB is recommended to leave headroom for transient Chromium rendering.

## Installation

From the unpacked release tree:

```bash
sudo ./install/install.sh --profile super-light --plan \
  --nextcloud-url https://cloud.example.org \
  --elasticsearch-url http://10.0.0.20:9200

sudo ./install/install.sh --profile super-light -y \
  --nextcloud-url https://cloud.example.org \
  --elasticsearch-url http://10.0.0.20:9200 \
  --elasticsearch-index my_index
```

The installer intentionally uses Docker for the middleware runtime. It installs
no middleware Python packages on the host. On hosts with Compose V2, `docker compose` may be used instead of the legacy `docker-compose` command.


### Private/internal CA certificates

If Nextcloud, Elasticsearch or another internal HTTPS endpoint uses a private
PKI, keep TLS verification enabled and supply the CA certificate to the
installer. One PEM X.509 certificate is accepted per option; repeat the option
for an intermediate CA if needed:

```bash
sudo ./install/install.sh --profile super-light -y \
  --nextcloud-url https://cloud.internal.example \
  --elasticsearch-url https://es.internal.example:9200 \
  --ca-certificate /secure/Company_Root_CA.crt
```

The installer preserves these trust anchors as local installation state and
bakes them into the API/provider image in addition to the normal public CA
bundle. `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` point to the resulting system
bundle inside the image. This lets `acl.verify_tls`, `auth.verify_tls`,
`carddav.verify_tls` and ordinary Python/httpx HTTPS clients remain enabled.

Changing the private CA requires rerunning the installer with the desired
`--ca-certificate` option(s), which rebuilds the API/provider image. The server
certificate/key used by the optional bundled nginx is separate: replace
`install/nginx/tls/server.crt` and `server.key` as before.

After installation, configure the external LLM/API key in:

```text
/opt/nextcloud-rag/runtime.env
/opt/nextcloud-rag/provider.env
```

Then recreate the API/provider containers so new environment values are loaded:

```bash
cd /opt/nextcloud-rag/install/super-light
docker-compose up -d --force-recreate api provider
```

Status:

```bash
/opt/nextcloud-rag/install/super-light/status-super-light.sh
```

## Contact seed graph

Contact seeds are attached operationally to the verified Nextcloud account, not
to an internal UUID. After the user has completed the normal Nextcloud Login
Flow, the stored credential can be reused for CardDAV. In RAG Admin open
**Users → <login> → Kontakt-DB** to configure and synchronize the seed source.
No extra password field is required. Missing credentials, a disabled source or
an empty address book are clean no-ops.

The equivalent CLI always accepts the human Nextcloud login:

```bash
cd /opt/nextcloud-rag/install/super-light
./contacts.sh list
./contacts.sh status --user alice
./contacts.sh books --user alice
./contacts.sh sync --user alice
```

If the same login exists on several Nextcloud servers, add `--server URL`.
`seed-carddav.sh --user alice` remains as a compatibility wrapper. The legacy
global `NEXTCLOUD_USERNAME` / `NEXTCLOUD_APP_PASSWORD` configuration is not
required for normal multi-user contact seeding. The Admin UI runs contact sync as a background job with a progress page and can discover available address-book names/slugs before synchronization. `docker-compose logs -f api` remains useful for diagnostics; full successful runs also reconcile contacts deleted at the CardDAV source.

No graph worker is started in Super-Light. The resulting persons, organisations
and aliases are reused during entity resolution and Elasticsearch query
expansion. Positive `AKI Recherche` findings are also persisted from the normal
planner/verifier path without another graph-extraction model call.

## Playwright

The renderer is a shared component under `install/components/` and binds to
`127.0.0.1:8090`. It accepts only public HTTP(S) targets on ports 80/443 and
blocks private/link-local/reserved destinations. HTML is rendered with a
1440×900 desktop viewport to A4 landscape PDF by default.

Super-Light enables bounded best-effort cookie acceptance and harmless prompt
dismissal. Browser storage state is kept in a Docker volume and isolated by
requested hostname, so ordinary consent choices can be reused on later renders.
This archive profile is for public sources: it does not automate logins and does
not remove login walls, paywalls, CAPTCHAs or other access restrictions. DOM
removal remains disabled by default. Rendering is fail-open; dynamic/video-heavy
content can still be incomplete.

Per-source metadata sidecars are written as hidden files, e.g.
`.01-source.metadata.json`, and record viewport/landscape, state reuse and cleanup
actions. The PDF is a readable research snapshot, not WARC/WACZ or a forensic archive.

## 0.8.4 clone acceptance

A fresh Leap 15.3 clone installation of 0.8.4-rc3 completed without manual runtime
repair. Kontakt-DB import through the Admin UI also completed successfully. On the
acceptance VM, 3.9 GiB assigned RAM showed roughly 1.7 GiB / 44% use at idle with
about 99% CPU idle and no swap. Treat this as an observed test point, not a hard
resource guarantee; Chromium/Web Research produces transient peaks.

## Privacy boundary

This profile removes the two local model/vector components, not the ACL model.
The normal path is:

```text
query -> planner -> Neo4j alias expansion -> Elasticsearch -> live Nextcloud ACL
      -> bounded verifier/evidence -> answer LLM
```

If planner/verifier/answer roles point at remote services, only their bounded
role inputs leave the host. Neo4j, Elasticsearch, Nextcloud credentials and the
full corpus remain local. Automatic document graph extraction is disabled. Positive
research findings reuse the planner/verifier structures already produced for the
answer and therefore require no additional remote model call.

## Static configuration check

Before starting or after editing `config.yaml`, run the side-effect-free static
checker from the release root:

```bash
./check-config.sh --config install/super-light/config.super-light.yaml
```

The checker exits non-zero for combinations that cannot work or contradict the
selected deployment profile. Technically valid but suboptimal combinations are
reported as warnings; for example Elasticsearch + Qdrant without a reranker is
supported through RRF and is therefore not rejected.

## TLS / private CA

For a private root/intermediate CA, pass each PEM certificate separately:

```bash
sudo ./install/install.sh --profile super-light --deployment dockerized \
  --ca-certificate /path/Company_Root_CA.crt ...
```

Python 3.13 strict X.509 checking remains enabled by default. Established
intranet PKIs that fail only the additional strict RFC-5280 checks can use
`--x509-strict` enables the additional strict RFC-5280 checks. Normal certificate, chain and hostname verification remains enabled even though strict mode is off by default.

## Retrieval policy

This profile ships with Elasticsearch as the required document arm and disables
vector/graph-document arms. Neo4j itself remains enabled for entity/alias query
expansion and AKI Recherche findings. Web fallback is planner-controlled when
the global Web backend, user permission and client capability are all available.

The profile is a `dockerized` deployment of the common middleware core, not a
fork. OpenWebUI remains opt-in and is not pulled or started unless requested.

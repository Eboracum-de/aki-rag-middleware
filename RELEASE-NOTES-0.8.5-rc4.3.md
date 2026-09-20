# AKI RAG Middleware 0.8.5-rc4.3

**Date:** 20 September 2026  
**Status:** release-candidate baseline; blank-VM acceptance completed

## Purpose

`0.8.5-rc4.3` hardens the internal service boundary discovered during post-rc4.2 review and incorporates installer/rerun defects found during a real rc9 → rc4.x upgrade rehearsal.

The release does not change the Nextcloud live-ACL model, Qdrant collection format, Mail sync cursor format or Graph-Lite data model. It changes **who may call the internal FastAPI middleware API**, introduces explicit route security zones, and tightens installer behavior around existing installations.

## Security boundary

Port `8765` is an internal service endpoint. RC4.3 adds two installer-managed machine credentials:

```text
RAG_INTERNAL_API_KEY
RAG_PROVIDER_INTERNAL_KEY
```

Protected middleware calls require:

```text
X-AKI-Internal-Key: <internal machine secret>
X-AKI-Provider-Key: <trusted-provider secret>
```

The provider supplies both credentials on its middleware calls. The bundled nginx proxy receives and injects only the internal credential on protected API/auth locations after its configured access/admin authentication layer; it never receives the trusted-provider secret. Client-supplied internal-key values are overwritten by nginx.

Routes are assigned centrally to `PUBLIC`, `TRUSTED_PROVIDER`, `INTERNAL`, `ADMIN` or `USER`. USER routes additionally require a usable scoped identity in multi-user modes before the existing Nextcloud live ACL authorizes document evidence.

This closes direct unauthenticated access to, among others:

- retrieval endpoints such as `/search`, `/multi-search`, `/elastic/search` and `/documents/resolve`;
- Graph diagnostics and mutation endpoints under `/graph/*`;
- `/query-context` and `/plan`;
- Web research/archive middleware endpoints;
- Nextcloud Login Flow middleware endpoints.

`/live` remains a cheap unauthenticated local liveness probe. `/rag-admin/*` and `/curation/*` retain their own existing authentication/session models.

The native start script also refuses a non-loopback `RAG_API_HOST` unless the administrator explicitly sets `RAG_ALLOW_REMOTE_INTERNAL_API=true`.

## Installer / rerun hardening

RC4.3 also includes:

- explicit Standard `--with-playwright` / `--no-playwright` switches; they update `archive.renderer.enabled`, while a rerun without either switch preserves the existing `web.yaml` renderer choice;
- reranking is now opt-in in the Standard reference configuration (`reranker.backend: none`); the installer skips Hugging Face reranker model download by default and exposes `--with-reranker-download` for deliberate local-reranker testing;
- common Standard/Super-Light names for Nextcloud/Elasticsearch connection settings and OpenWebUI/proxy enable/disable switches;
- explicit `--no-openwebui` and symmetric `--with-proxy` / `--no-proxy` behavior;
- retained optional component choices on rerun unless explicitly overridden;
- Standard preflight detection of existing AKI processes, systemd units and Compose services before modification;
- fail-closed abort when the existing running state cannot be verified;
- alternate proxy listen-port support in Standard;
- Standard Neo4j schema initialization executed from the application root so `python -m rag.graph` can import the installed package;
- visible progress while waiting for Neo4j/schema readiness;
- nginx health probing on the configured HTTPS port instead of hard-coded 443;
- canonical outbound Nextcloud TLS configuration via `nextcloud.verify_tls` and
  `nextcloud.ca_file` across Login Flow, live ACL, CardDAV, mail WebDAV and web
  archive;
- repeatable `--ca-certificate FILE` support in both Standard and Super-Light.
  Standard builds a Nextcloud-scoped CA bundle instead of setting global Python
  CA environment variables, so public OpenAI/Hugging Face trust is not replaced.
- Standard now declares the optional Playwright renderer in Compose and mirrors `web.yaml` automatically: `archive.renderer.enabled=true` builds/starts the renderer on `127.0.0.1:8090`; disabling it removes the local renderer container. This repairs upgrades where a preserved `web.yaml` kept rendered-PDF archiving enabled while Standard no longer managed the service.
- Super-Light includes the Playwright renderer as a normal profile component; no `--with-playwright` switch is required or accepted there. Standard keeps Playwright opt-in via `--with-playwright`.

## Upgrade behavior

Existing `runtime.env` is preserved. On first rc4.3 rerun, the installer adds `RAG_INTERNAL_API_KEY` and `RAG_PROVIDER_INTERNAL_KEY` if absent. Subsequent reruns retain both keys.

The internal key is not a replacement for:

- provider Bearer/client authentication;
- RAG Admin authentication;
- Nextcloud live document ACL;
- self-service Findings curation authentication.

If bundled nginx is disabled and another reverse proxy talks directly to port 8765, that proxy must provide equivalent client authentication and may inject only the general `X-AKI-Internal-Key` for INTERNAL/ADMIN access. The provider-role secret must remain confined to the trusted provider. Direct exposure of port 8765 is unsupported.

## State compatibility

RC4.3 does not intentionally invalidate:

- `runtime/users.sqlite`;
- `runtime/credential-master.key`;
- `mail_state.sqlite`;
- `state.sqlite`;
- existing Qdrant collections;
- existing Neo4j data volumes.

As with rc4.2, preserve `runtime/users.sqlite` and its matching credential master key as a pair.

## Validation

CI covers Python compilation, shipped shell syntax and the full regression suite.

Blank-VM acceptance was completed on 20 September 2026 for both supported deployment mappings:

- **Super-Light / dockerized:** fresh installation completed successfully; document search and RAG Admin were verified; Playwright started as part of the normal stack without an additional installer switch.
- **Standard / native:** fresh installation completed with local Qdrant and Neo4j; document search and RAG Admin were verified; `--with-playwright` built and started the optional renderer automatically.

A Standard-host Playwright base-image extraction initially failed with Docker/BuildKit `archive/tar: invalid tar header`. A direct pull of the same `v1.62.0-noble` base-image tag followed by installer restart succeeded without middleware changes. This is treated as a local Docker/storage-layer incident rather than an rc4.3 application defect.

RC4.3 is therefore the accepted release-candidate baseline. The remaining Playwright digest pin, Neo4j wait-output polish and WebDAV archive-latency work are documented follow-ups rather than release blockers.

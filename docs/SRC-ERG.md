# SRC and ERG target architecture

**Status:** architecture concept in `0.8.6-rc1.1`; explicit installer and
configuration support planned for `0.8.6-rc1.2`.

SunaQ is the product. **Secure RAG Core (SRC)** and **Eboracum Research Gate
(ERG)** describe trust/capability envelopes, not separate products.

SRC is the conservative Elasticsearch-centric target: ordinary Nextcloud
documents, FullTextSearch/Elasticsearch, live Nextcloud ACL and optional
administrator-owned seed/alias context. Local/private model processing is
preferred, but SRC does not require zero egress: bounded external model
processing is acceptable where the administrator explicitly accepts and manages
the disclosure.

ERG is the opt-in extension space for additional sources, derived state and more
complex retrieval or graph functions. Examples include Mail, live Web research
and Web archiving, Chat archive, semantic retrieval/reranking,
Research Findings/Graph-Lite, full document graphization and additional
retrieval rounds. ERG is a menu, not a requirement to enable all of these.

The expected everyday **workgroup** preset is therefore Elasticsearch-centric:
Documents + Mail + Web/Web archive + Playwright + Chat archive +
Findings/Graph-Lite, with Qdrant and full graph off unless needed.

## rc1.1 status

There is no supported `architecture.tier` switch in rc1.1. Existing component
gates can be combined manually into SRC-like or ERG-like operation, but that is
an administrator-managed override rather than a named, validated profile.

Deployment profile (Standard/Super-Light) and research model
(Schnell/Gründlich/Tief) remain independent of this architecture concept.

## rc1.2 target

The first supported implementation should stay small: individual
`--x-enabled` / `--x-disabled` switches, a safe plain-text
`--preset-file`, and shipped **core** / **workgroup** preset files. Explicit
CLI overrides win over preset values. Contradictory combinations should be
validated where security depends on them.

Conversation provenance is part of the same rc1.2 hardening step: replayed
client history is not authoritative. SunaQ should maintain its own conversation
store, derive bounded follow-up context from it, resolve prior-source references
from it, and generate Chat archives from it. Client-side Knowledge/RAG context
should not become a second evidence layer in front of SunaQ.

rc1.1 already defines and wires ALLOW-only modular policy/inspection hooks at
outbound-search, URL-fetch, received-content, Nextcloud-persistence and
model/embedding-egress boundaries. rc1.2 should add administrator configuration
and concrete adapters. This is particularly useful for ERG sources such as Mail/Web, but
`pre_model_egress` also applies to an SRC deployment that deliberately uses a
remote model. The architecture should permit adapters such as malware scanning,
URL policy or DLP without requiring one specific product.

See [Roadmap](ROADMAP.md).

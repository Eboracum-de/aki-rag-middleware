# Privacy architecture and trust boundary

**Reference:** 0.8.5-rc4.2

The middleware deliberately separates access to the complete private corpus from
processing of already selected evidence. Privacy is therefore not defined as
"every model must run locally". The primary invariant is that the complete
Nextcloud/Elasticsearch corpus, vector index and ACL state remain inside the
operator-controlled retrieval plane.

## Private retrieval plane

The following operations are intended to remain local/private:

1. Nextcloud FullTextSearch / Elasticsearch access;
2. document chunking and embedding;
3. Qdrant vector storage and search;
4. optional Neo4j retrieval over an existing graph;
5. Cross-Encoder/TEI reranking when a local reranker is configured;
6. live Nextcloud ACL authorization.

Only document content that survived the configured local retrieval and live
authorization pipeline is eligible for transmission to a remote verifier/answer
role. Query-rewrite roles may also receive the user query and bounded shared
identity/alias context according to configuration; that context is retrieval
knowledge, not document evidence.

```text
Nextcloud / Elasticsearch
          |
          v
 local embedding -> Qdrant
          |
          v
 hybrid / graph retrieval
          |
          v
    local reranker
          |
          v
 Nextcloud Live ACL
          |
---------- trust boundary ----------
          |
          v
 candidate verifier / evidence control / answer LLM
```

## Role-specific LLM routing

The current 0.8.5 reference can route four LLM roles independently:

- `planner`: Query Rewrite/SearchSpec generation and optional bounded round control;
- `verifier`: semantic verification of ACL-authorized document candidates;
- `evidence`: evidence decisions and citation-integrity control;
- `answer`: final answer generation and streaming.

Unset role settings inherit the canonical `LLM_*` backend for compatibility. Each role can override backend, URL, model, API key, TLS verification
and trust scope through `<ROLE>_LLM_*` variables.

A practical `private-retrieval` deployment keeps embedding, Qdrant, reranking
and ACL local while using a capable remote model for verifier/evidence/answer.
A `strict-local` deployment points all roles at a local provider instead.

## Remote evidence budgets

When a role endpoint is classified as remote, the provider applies hard evidence caps in
addition to the feature-specific limits:

- maximum characters per answer document: `REMOTE_LLM_MAX_CHARS_PER_DOCUMENT`;
- maximum total answer/evidence characters per call: `REMOTE_LLM_MAX_TOTAL_CHARS`;
- maximum verifier candidates: `REMOTE_VERIFIER_MAX_CANDIDATES`;
- maximum verifier characters per candidate: `REMOTE_VERIFIER_MAX_CHARS_PER_DOCUMENT`;
- maximum answer documents: `REMOTE_ANSWER_MAX_DOCUMENTS`.

Loopback and private/link-local IP endpoints are classified as local by default;
public IPs and ordinary public DNS names are remote. `*_LLM_SCOPE=local|remote`
can override this classification when the administrator knows the actual trust
boundary.

These limits constrain transmitted evidence, not the user question itself. A
remote planner may receive the user's query and bounded conversation context.

## Graph extraction is different

Graph extraction can inspect much larger portions of a document than normal
answer evidence. The graph entity/relation extractors therefore remain a
separate administrative trust decision. Their backend is configured under
`graph_entity_discovery` / `graph_relation_discovery` (or the corresponding
`GRAPH_*` environment variables).

Automatic graph processing is **off by default** in the current reference configuration even when Neo4j and the
Graph Queue are available:

```yaml
graph_queue:
  enabled: true
  auto_enqueue_cited_documents: false
  worker:
    enabled: false
```

This prevents answer-cited documents from being silently sent to a remote graph
extractor. Administrators may still enqueue/process graph jobs deliberately.

## Public Web Research

Public Web Research is separate from the private corpus. Search results are
fetched first; only actually fetched content can become evidence. Selected
sources can be archived to the current user's Nextcloud via WebDAV. Archive TLS
verification has its own `web.yaml: archive.verify_tls` setting because the
archive write is a separate HTTP client path.

## Shared retrieval knowledge versus protected evidence

AKI intentionally permits organization-wide reuse of curated identity and alias
knowledge. If one user's work establishes a useful name form, another user's
query may benefit from that expansion. This does not transfer the source
document's read permission: any concrete document content still has to pass the
current user's live Nextcloud ACL before it is used as answer evidence.

The distinction is important for Graph-Lite: identity vocabulary and curation
state can be collaborative, while source passages, EvidenceFrames and supporting
documents remain provenance-bearing and authorization-sensitive.

## Untrusted content

Mail, web pages, archived web content and saved chats can be authored or influenced
by third parties. Their text is data, not an instruction channel to the model.
Structured verifier/Graph schemas, bounded context and provenance-specific prompts
reduce the impact of adversarial text, but 0.8.5 does not claim a complete prompt-
injection defense. Operators should treat automatic extraction from hostile inbound
content as lower-trust until reviewed.

## Operational principle

A deployment should make the trust decision explicit rather than infer it from
where a model happens to run. Provider health reports the effective backend,
model and local/remote scope for Query-Rewriter (`planner`), verifier, evidence and answer roles.

## Research-Finding provenance

`research_findings` persists only positive, verifier-supported document matches; rejected or uncertain document/query pairs are not stored as Findings. Shared `ResearchFinding` nodes deliberately coalesce equivalent curation work, while per-user provenance is represented by the concrete request path:

```text
CanonicalUser -> ResearchRun -> ResearchFinding -> Document
```

The ResearchRun retains the user/query/runtime provenance. Before Findings evidence is shown in RAG Admin or self-service curation, the supporting Document is re-authorized through the selected/current user's live Nextcloud credential. RAG Admin is a trusted operator surface: its administrator can choose another configured canonical-user context and is therefore not isolated by the administrator's own Nextcloud ACL. Self-service curation is separately gated and currently exposes only the authenticated user's own ResearchRuns.

Shared curation remains intentional organization-level retrieval knowledge. A decision made by one authorized curator can be reused when another authorized user later reaches the same Finding, but it never grants access to the supporting document.

## Data protection and lifecycle

Technical data minimization does not by itself define legal roles or retention duties.
For deployments using remote LLM/search/hosting providers, the operator must assess the
required contractual/organizational controls for the actual data and jurisdiction.
AKI's role routing and evidence caps can support such a policy but do not replace it.

Deletion, archive-retention, backup/restore and key-rotation limits are documented in
`DATA-LIFECYCLE.md`; the adversary/boundary model is in `THREAT-MODEL.md`.

# AKI RAG Middleware
## Architecture and design baseline 0.8.5-rc4.3

**Updated:** 20 September 2026  
**Status:** Release Candidate  
**Reference version:** `0.8.5-rc4.3`

---

## 1. Overview

AKI RAG Middleware connects an existing Nextcloud document estate to several retrieval paths and an LLM answer layer. It is not a document store and does not maintain an independent authorization database.

The core authorization rule is:

> **Retrieval systems propose candidates. Nextcloud remains the final authorization authority for private document evidence.**

Elasticsearch, Qdrant and Neo4j may contribute retrieval signals or candidate documents. Before private document content becomes verifier or answer evidence, the concrete file candidate is checked live through Nextcloud for the current user.

If live authorization removes a candidate, the normal path does not adaptively fetch lower-ranked documents merely to fill the context window.

The reference architecture can combine:

- Nextcloud FullTextSearch / Elasticsearch for lexical retrieval;
- optional Qdrant for semantic retrieval;
- Neo4j for seed/alias/entity context and optional Graph-Lite functions;
- result fusion and deduplication;
- an optional local or external reranker;
- live Nextcloud WebDAV authorization;
- a compact document-grounded Candidate Verifier;
- one or more configurable LLM roles;
- optional public-Web research through Brave Search or SearXNG;
- optional Nextcloud-backed Web, Mail and Chat archives.

The model layers are independently configurable. Embedding models, rerankers, planner/verifier roles and answer models can be local or external according to administrator policy.

---

## 2. Scope and operating assumptions

The architecture is designed for installations that already have a useful Nextcloud document corpus and, in many cases, an existing FullTextSearch/Elasticsearch deployment.

Typical retrieval challenges include:

- alternate spellings and abbreviations;
- OCR errors;
- incomplete or colloquial user questions;
- relationships that cannot be expressed by one keyword;
- semantically similar but factually irrelevant documents;
- multiple versions or contradictory document states;
- changing Nextcloud permissions.

The middleware translates the user request into a constrained `SearchSpec`. The model may produce a human-style Nextcloud full-text expression and a semantic query, while the middleware itself constructs backend requests.

The model does not emit raw Elasticsearch JSON DSL for execution.

---

## 3. Design principles

### 3.1 Retrieval and authorization are separate concerns

Search/index systems may have stale, broader or differently synchronized knowledge than the current Nextcloud file tree. They are therefore candidate sources, not permission authorities.

### 3.2 Document evidence remains document-grounded

A semantic match or graph relation signal is not sufficient evidence by itself. Where enabled, the Candidate Verifier checks whether the candidate document directly supports the information need.

### 3.3 Missing evidence is represented explicitly

When authorized, relevant evidence is not available, the system may return fewer results or an insufficient-evidence response. It does not intentionally replace missing evidence with weaker documents simply to maintain a result count.

### 3.4 Models and providers are replaceable components

Answer LLM, planner/verifier roles, embedding backend, reranker and Web search provider are independently configurable.

Changing an answer model does not require re-indexing the vector corpus. Changing the embedding model normally does, because vector spaces from different embedding models must not be mixed.

### 3.5 Public Web research is a separate evidence path

Public Web discovery, fetch, passage selection, relevance review and archiving are handled separately from private document retrieval.

### 3.6 Graph-Lite is optional enrichment

Graph-Lite and Research Findings are not prerequisites for normal document search.

Ordinary Elasticsearch/Qdrant retrieval, live ACL, verifier and answer generation continue to operate when Findings are disabled or left uncurated.

Curated identity and relation knowledge can improve query expansion, entity resolution and later graph-assisted searches, but this is an optional learning/curation loop rather than a mandatory runtime dependency.

---

## 4. High-level architecture

```text
                  AKI Recherche / OpenWebUI / trusted API client
                                   |
                         OpenAI-compatible provider
                                   |
                         Query rewrite / SearchSpec
                                   |
                 +-----------------+-----------------+
                 |                                   |
         private/internal path                  public Web path
                 |                                   |
        Neo4j seed/alias context               Brave / SearXNG
                 |                                   |
        +--------+---------+                    URL discovery
        |                  |                         |
 Elasticsearch         Qdrant                   HTTP fetch
  required arm         optional                     |
        |                  |                  passage selection
        +--------+---------+                         |
                 |                             relevance gate
          fusion / dedup                           |
                 |                           Web evidence W1..Wn
        optional reranker                           |
                 |                                  |
        LIVE NEXTCLOUD ACL                          |
                 |                                  |
       optional Candidate Verifier                  |
                 +-----------------+----------------+
                                   |
                             answer model
                                   |
                    sources + optional archives
```

---

## 5. Component responsibilities

| Component | Responsibility | Authorizes private document access? |
|---|---|---:|
| Query Rewriter | creates SearchSpec and lightweight analysis fields | No |
| Neo4j | seed/alias/entity context; optional graph retrieval and curation | No |
| Elasticsearch | lexical candidate discovery | No |
| Qdrant | semantic candidate discovery | No |
| Dedup/RRF/Reranker | candidate combination and ordering | No |
| Nextcloud WebDAV ACL | current-user visibility of concrete files | **Yes** |
| Candidate Verifier | document-level relevance and relation binding | No |
| Answer model | answer generation from authorized evidence | No |
| Brave/SearXNG | public URL discovery | N/A |
| Web relevance gate | source relevance after actual fetch | N/A |

---

## 6. Internal retrieval path

### 6.1 Normal path

Each retrieval round uses the same interface:

1. A compact Neo4j seed/alias context may be loaded before rewrite.
2. The user question is rewritten into one `SearchSpec`.
3. `elastic_query` is parsed and compiled deterministically into Elasticsearch JSON.
4. `semantic_query` is sent to Qdrant when enabled.
5. Candidate lists are fused and deduplicated.
6. An optional reranker may reorder the bounded candidate set.
7. Live Nextcloud ACL removes unauthorized files.
8. The Candidate Verifier may check direct document support.
9. The answer model receives only selected evidence.

Example:

```text
User:
Find invoices from Example Ltd. from 2025

SearchSpec:
  elastic_query:  +Example +2025 +invoice
  semantic_query: invoices from Example Ltd. from 2025
  entities:       Example Ltd.
  concepts:       invoice
  constraints:    year=2025
```

Reference configuration:

```yaml
search:
  es_limit: 50
  vector_limit: 80
  vector_threshold: 0.55
  rrf_k: 60
  rerank_candidates: 10
  final_limit: 15

retrieval_planner:
  enabled: true
  max_retrieval_rounds: 1
  model: ""
  max_tokens: 700
  context_max_chars: 12000
  verification_candidate_limit: 6
  bounded_verification_candidate_limit: 30
  exhaustive_verification_candidate_limit: 30
```

`max_retrieval_rounds: 1` means one rewrite followed by one retrieval run.

If more rounds are configured, a later round may produce a revised SearchSpec from the bounded visible result picture. It still uses the same retrieval pipeline and configured backend policy.

### 6.2 Explicit retrieval directives

Supported specialist/diagnostic directives can override the normal arm selection:

- `/files` — Elasticsearch only, still using structured rewrite;
- `/vector` — Qdrant only;
- `/graph` — explicit graph document-retrieval path where enabled;
- combinations such as `/files /vector`;
- `/elastic` — direct Nextcloud/Elasticsearch full-text mode without rewrite/vector/fusion/reranker.

Neo4j seed/alias expansion is independent from the optional graph document-retrieval arm.

---

## 7. SearchSpec, QueryFrame, EvidenceFrame and RetrievalRecord

### 7.1 SearchSpec

The SearchSpec is the executable retrieval description.

Typical fields include:

```json
{
  "elastic_query": "+Example +2025 +invoice",
  "semantic_query": "invoices from Example Ltd. in 2025",
  "entities": ["Example Ltd."],
  "concepts": ["invoice"],
  "constraints": [{"kind": "year", "value": "2025"}],
  "verification_requirements": [
    "The document itself is an invoice from Example Ltd."
  ]
}
```

### 7.2 QueryFrame

For verifier/provenance/Findings compatibility, analysis fields can be represented as a QueryFrame.

A QueryFrame is a **search hypothesis**, not evidence and not a fact.

### 7.3 EvidenceFrame

The Candidate Verifier derives an EvidenceFrame only from the candidate document.

Important relation bindings include:

- `direct` — the document itself supports the requested relationship/object;
- `reference_only` — the requested subject is only mentioned or referenced;
- `contradicted` — the document supports a materially different relationship;
- `unclear` — the document does not allow a reliable decision.

### 7.4 RetrievalRecord

Optional retrieval/evidence audit records:

```yaml
retrieval_record:
  enabled: true
  directory: "runtime/retrieval-records"
```

They store structured query, SearchSpec/QueryFrame, document references, verifier metadata and EvidenceFrames, but not complete document bodies.

A QueryFrame must not be imported automatically as a graph fact.

---

## 8. Reranking and deduplication

Supported reranker modes include a local cross-encoder and an external TEI endpoint.

Local example:

```yaml
reranker:
  backend: local
  model: BAAI/bge-reranker-v2-m3
  device: cpu
```

External TEI example:

```yaml
reranker:
  backend: tei
  tei_url: "http://127.0.0.1:8081"
  fallback_backend: none
```

Super-Light can operate without a reranker. Deduplication remains a separate preprocessing step.

---

## 9. Live ACL and bounded post-filtering

The current normal order is:

```text
retrieve -> fuse/deduplicate -> optional rerank -> bounded candidates
        -> live Nextcloud ACL -> verifier/answer
```

Example:

```text
Candidates:      [A, B, C, D, E]
Ranking:         [C, A, E, B, D]
ACL authorized:  [C, E]
Answer evidence: [C, E]
```

The middleware does not then fetch F, G or H merely to restore the original count.

This has two operational consequences:

- no replicated ACL shadow is required in Elasticsearch/Qdrant/Neo4j;
- users with narrow permissions may receive fewer results than a user with broader rights.

A possible future optimization is a fixed-size ACL candidate pool before an expensive reranker. Such a pool would remain bounded and non-adaptive.

### 9.1 WebDAV request cost

Live ACL checks are batched. With the default:

```yaml
acl:
  batch_size: 100
```

up to 100 unique file IDs are checked in one authenticated WebDAV `SEARCH` request.

The practical cost should be measured on the actual Nextcloud deployment. It is not a per-document HTTP request loop.

---

## 10. Graph and Graph-Lite

Neo4j is used for identity/alias context, provenance and optional graph-assisted retrieval and curation.

It is not an authorization store and is not treated as a universal fact database.

### 10.1 CardDAV seeds and provenance

CardDAV contacts can seed known Persons/Organizations. Document processing can add observations and relation evidence while retaining provenance.

### 10.2 Name and alias policies

Entity forms can carry a `resolution_policy`:

- `exclusive` — query use plus hard ingestion identity resolution;
- `contextual` — query/candidate use but no hard ingestion resolution;
- `search_only` — query expansion only;
- `document_only` — not exposed as a global resolver/search form.

This allows uncertain OCR/name variants to be useful without automatically treating them as canonical identity.

### 10.3 Shared retrieval knowledge

Curated names and aliases can be reused across users.

This reuse is retrieval knowledge, not access to the source document that originally motivated the alias. Document evidence still requires current-user live ACL.

### 10.4 Graph curation operations

Administrative tooling supports, among other operations:

- merge proposals;
- manual merge with preview;
- persistent `NOT_SAME_AS`;
- alias and policy maintenance;
- name correction;
- reassignment of observations or CardDAV records;
- provenance and import-run inspection.

### 10.5 Indirect relations

A document-grounded chain:

```text
A -> C -> B
```

may be represented as an indirect connection only when both hops have supporting provenance.

It must not be transformed into a direct `A <-> B` relation.

### 10.6 Research Findings

Research Findings are positive, document-bound verifier observations.

A deterministic `finding_id` combines provenance, supporting document and canonical QueryFrame so repeated equivalent research can coalesce.

Findings are an **optional learning layer**. The normal RAG pipeline does not depend on their curation.

A typical enrichment loop is:

```text
query
 -> SearchSpec
 -> retrieval
 -> live ACL
 -> verifier
 -> answer
 -> optional ResearchFinding
 -> optional curator decisions
 -> improved shared graph knowledge
```

A well-curated graph can improve entity resolution and may support searches across recognized relationships. Leaving Findings uncurated or disabling `research_findings.enabled` does not disable normal retrieval or answering.

Curated claims remain document-grounded `RelationObservation` records. The current release does not automatically promote them into global fact edges or query-expansion relations.

User/query provenance is represented through a per-request `ResearchRun` while the Finding remains shared:

```text
CanonicalUser --PERFORMED--> ResearchRun --PRODUCED--> ResearchFinding
                                                        |
                                                  SUPPORTED_BY
                                                        |
                                                     Document
```

The ResearchRun stores the original user query and retrieval/runtime provenance. Equivalent runs may therefore converge on the same globally curated Finding. Run-level dismissal controls the work queue only; it does not alter the shared Finding.

Both the administrator user-context view and optional end-user self-service re-check the supporting document through live Nextcloud ACL before exposing Finding evidence. End-user curation uses a separate, short-lived Nextcloud Login Flow session rather than a persistent RAG password or the ordinary provider credential. Self-service is disabled by default and can be gated per canonical user.

---

## 11. Public Web research

### 11.1 Discovery

Supported discovery backends include:

- Brave Search API;
- externally operated SearXNG.

Search snippets are discovery metadata and are not answer evidence.

### 11.2 Evidence pipeline

```text
Search provider
   -> URL list
   -> HTTP fetch
   -> text/PDF extraction
   -> passage selection
   -> relevance review
   -> bounded Web evidence
   -> answer citations [W1], [W2], ...
```

### 11.3 Explicit, mixed and fallback use

Web research can be:

- explicit Web-only: `/web ...`;
- part of a mixed workflow;
- used after selected internal evidence;
- allowed as a controlled fallback when the trusted client sets `X-RAG-Web-Allowed: true` and per-user Web research is enabled.

A conservative Web gate decides whether automatic Web use is appropriate.

### 11.4 Web-after egress boundary

When Web queries are derived from private internal evidence, the query itself becomes data sent to an external search provider.

The Web-after prompt therefore treats internal evidence as untrusted input and avoids transferring secret-like strings, e-mail addresses, API keys, tokens, internal identifiers or unusual verbatim text unless the user explicitly asks to search for that exact value.

### 11.5 Web archive

Selected Web research can be archived through the user's Nextcloud WebDAV credential:

```text
<archive-root>/YYYY-MM/DD-HHMMSS-xxxx/
    recherche.md
    fetch-log.jsonl
    01-source.txt
    .01-source.metadata.json
    01-source.pdf
    01-source.html       # optional
    ...
```

Archive roots are excluded from ordinary internal retrieval so archived public material does not later appear as an independent private source.

Playwright rendering is optional and produces a readable research snapshot, not a complete WARC/WACZ forensic capture.

---

## 12. Privacy and processing boundaries

### 12.1 Local embeddings

With local embedding infrastructure:

- document text can remain inside the administrator-controlled environment;
- Qdrant can remain local;
- only selected authorized evidence needs to be transmitted to a remote answer/verifier model when remote roles are configured.

### 12.2 External embeddings

Using an external embedding provider transmits every indexed text chunk to that provider.

For a full index this can approach disclosure of the complete indexable corpus and should be treated as a different trust boundary from selective answer generation.

### 12.3 Role-specific LLM routing

Planner, verifier, evidence-control and answer roles can inherit one default model/backend or use separate model configurations.

Remote roles have explicit document/count/character budgets.

### 12.4 Credential storage

User-bound reversible Nextcloud and IMAP credentials, and Login Flow poll tokens, are encrypted with AES-256-GCM in the credential store.

The master key remains outside SQLite.

This protects stored database material from casual/plaintext disclosure but is not intended to protect secrets from `root` or a fully compromised middleware process.

### 12.5 Untrusted content

Documents, mail, Web pages and saved chats may contain text phrased as model instructions.

Such text is treated as evidence content, not as middleware control input.

The main residual risks are evidence integrity, persistent graph/finding pollution and Web-query egress, rather than arbitrary backend-command execution.

See `THREAT-MODEL.md` for the security analysis.

---

## 13. Mail integration

Mail synchronization is configured per canonical Nextcloud user.

Configured IMAP mailbox names are recursive roots. Selectable descendants are discovered through IMAP `LIST`, and the hierarchy is mirrored into Nextcloud.

New messages use a directory-per-message layout:

```text
<target>/<account>/<mailbox-hierarchy>/<YYYY>/<MM>/
  <timestamp>_<uid>_<subject>/
    mail.txt
    .mailmeta.json
    a01_<attachment>
    ...
    message.eml          # optional
```

`mail.txt` is the indexable normalized representation. `.mailmeta.json` carries deterministic metadata for mail/thread processing.

Legacy flat archives remain readable and are not moved automatically.

---

## 14. Frontends and provider boundary

AKI Recherche is the bundled Nextcloud-native frontend.

OpenWebUI or another OpenAI-compatible integration can use the same provider when registered as a Trusted Client.

The frontend boundary is intentionally independent from retrieval implementation:

```text
frontend/integration
      |
trusted client key
      |
OpenAI-compatible provider
      |
retrieval/orchestration
```

A Trusted Client key authenticates the integration server, not the human user. The external user identifier supplied by that integration is scoped as:

```text
client_id::external_user_id
```

and selects the corresponding server-side Nextcloud credential binding.

Provider keys therefore belong only on trusted integration servers. Externally reachable provider endpoints should be restricted with network policy, reverse-proxy allowlists, mTLS or equivalent controls where appropriate.

This boundary also allows AKI to be composed with other local RAG systems, agents or research tools when the administrator explicitly permits it.

---

## 15. Process model and latency

The normal AKI request path is served by long-running API/provider processes and is independent from Nextcloud's background-job scheduler.

Total latency depends on:

- query rewrite;
- Elasticsearch/Qdrant response time;
- hydration/fusion/dedup/reranking;
- live WebDAV ACL;
- verifier;
- answer model;
- public Web fetch/relevance stages when enabled.

One observed development run with GPT-5.6 Luna was approximately:

```text
Query Rewrite            ~4 s
Retrieval/Rerank/ACL     ~9-10 s
Verifier                 ~5 s
Answer                   ~3 s
Total                    ~24 s
```

This is an observation from one environment, not a performance guarantee.

Latency measurements should separate live ACL time from the rest of retrieval. Because ACL uses batched WebDAV SEARCH, benchmarking 10/50/100 candidates on the target Nextcloud instance is more useful than assuming linear per-document cost.

---

## 16. Background workers and deployment profiles

Capabilities and workers are configured separately.

Example:

```yaml
qdrant:
  enabled: true
sync_worker:
  enabled: false

mail:
  enabled: true
  worker:
    enabled: false

graph_queue:
  enabled: true
  auto_enqueue_cited_documents: false
  worker:
    enabled: false
```

This permits a component to be configured without automatically starting periodic CPU-intensive or privacy-sensitive processing.

The current release line tests:

- `standard + native`;
- `super-light + dockerized`.

These are combinations of two independent axes:

- **functional profile** — enabled retrieval/graph/UI capabilities;
- **deployment mode** — native or containerized service operation.

Super-Light uses the same middleware core and can remain Elasticsearch-centric without Qdrant or a local reranker.

---

## 17. Error and uncertainty handling

The middleware uses explicit states for incomplete or uncertain processing:

- invalid/incomplete structured model output is retried or reported as failure;
- ACL denial removes evidence and does not trigger adaptive refill;
- indirect graph chains remain labeled indirect;
- search-engine snippets are not evidence;
- unfetchable Web pages are not evidence;
- mere mention can be classified `reference_only`;
- missing evidence is phrased as absence from the retrieved/available sources rather than global nonexistence.

---

## 18. Current release-candidate boundaries

`0.8.5-rc4.3` is the current release-candidate baseline.

Known limits include:

- only `standard+native` and `super-light+dockerized` are released/tested deployment combinations;
- no unified cross-store purge/restore workflow;
- no complete prompt-injection defense;
- Web snapshots are research artifacts, not full WARC/WACZ captures;
- ResearchRun provenance and user-scoped live-ACL curation are implemented, but curation still writes shared Graph-Lite knowledge and should therefore be granted deliberately;
- no automatic conversion of QueryFrames or Finding claims into global facts.

See `KNOWN-LIMITATIONS.md`, `THREAT-MODEL.md`, `DATA-LIFECYCLE.md` and `GRAPHLIGHT-FINDINGS.md` for details.

---

## 19. Responsibility separation

The current middleware separates four responsibilities:

1. **candidate retrieval** — Elasticsearch, optional Qdrant, optional Graph/Web paths;
2. **private-document authorization** — Nextcloud live ACL;
3. **evidence review** — Candidate Verifier and Web relevance checks;
4. **answer generation** — the configured answer model.

This separation defines component boundaries and failure handling. It also permits individual retrieval/model components to be replaced without changing the live authorization rule.

It is an architectural choice with explicit trade-offs rather than a claim that the same decomposition is required for every RAG deployment.

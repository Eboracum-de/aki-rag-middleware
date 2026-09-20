# Roadmap

This file records follow-up work that is intentionally **not** part of the `0.8.5-rc4.1` contract.

## 0.8.5-rc5 candidates

### Optional ACL-aware retrieval prefilter

Keep the existing live Nextcloud WebDAV ACL as the mandatory final authorization boundary, but evaluate an administrator-configurable retrieval prefilter.

Nextcloud FullTextSearch already materializes effective document ACL metadata in Elasticsearch, including `owner`, `users`, `groups` and `circles`; the ES→Qdrant synchronization also preserves those fields in vector payloads. A future prefilter can therefore reduce the candidate space before reranking while the live ACL still decides whether a concrete file may become evidence.

Design constraints:

- off/on must be administrator-configurable; the initial default should remain conservative;
- include Circle access, not only direct users/groups;
- stale index ACL may improve or reduce recall but must never become the security boundary;
- if the current user's group/Circle context cannot be obtained completely and reliably, fail open to the existing unfiltered retrieval path;
- keep work bounded; do not repeatedly fetch until an arbitrary authorized result count is reached;
- continue a final live WebDAV authorization before verifier/answer use.

### Exact extracted-content duplicate detection

Use Nextcloud FullTextSearch's document `hash` as the primary exact duplicate signal where available. In the current Nextcloud FullTextSearch implementation this is an MD5 of the **extracted indexed content**, not a raw-file byte hash, so the correct term is *exact extracted-content duplicate*.

The duplicate group must retain all distinct Nextcloud file IDs. Authorization is evaluated per visible copy so a denied representative can never hide an otherwise accessible duplicate. Near-text/OCR and same-stem format-variant detection remain separate secondary signals.

For graph/research statistics, independent-source counts should ultimately use distinct extracted-content hashes rather than distinct file IDs when the hashes are available.

### Dependency hardening and Transformers 5 evaluation

Keep `transformers==4.57.6` as the RC4 baseline for now. Dependabot's direct 5.10.1 bump is not mergeable as-is because Transformers 5.10.1 requires `huggingface-hub>=1.5,<2`, while the current baseline intentionally pins `huggingface-hub>=0.24,<1`.

For RC5:

- test a coordinated Transformers 5.x + Hugging Face Hub 1.x upgrade on a dedicated branch rather than accepting an isolated major bump;
- run the full regression suite plus a real local reranker smoke test with the configured cross-encoder model before changing the baseline;
- document/automate reachability triage for dependency advisories: distinguish vulnerable APIs from actually exercised AKI paths, especially where the local reranker only imports `AutoTokenizer` and `AutoModelForSequenceClassification` with `local_files_only=True`;
- split optional heavyweight ML dependencies from the core/server dependency set where practical (for example core vs. local-reranker requirements), so TEI/Super-Light deployments do not install Transformers merely because another profile can use it;
- keep Dependabot major-version updates non-automatic; security updates within the supported major line should still be reviewed promptly.

### Smaller RC5 follow-ups

- Reduce presentation drift between RAG-Admin Finding curation and `/curation/` by sharing more of the Finding view/presentation logic while keeping their authorization/session boundaries separate.
- Make the global self-service gate and Login-Flow identity behavior more explicit in the UI.
- Consider controlled expansion of self-service beyond a user's own ResearchRuns only after the ACL/provenance semantics are specified and tested.

## 0.8.6 direction

The next minor line may expose richer **multi-model/model-profile selection** rather than adding it late to the 0.8.5 RC series. The current role-specific backend configuration remains the 0.8.5 contract; model-profile UX, selection policy and compatibility rules should be designed and tested as an explicit 0.8.6 feature.

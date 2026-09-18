# Graph-Lite Findings curation

**Reference:** `0.8.5-rc3`

Graph-Lite turns selected, verified research findings into **curated, document-grounded graph observations**. It is deliberately conservative: a ResearchFinding is provenance-bearing evidence that a query frame matched a document; it is not automatically a global fact.

## Curation model

The manual workflow is:

1. **Entity resolution** — map each finding entity text to an existing Entity, create a corrected Person/Organization, or mark it as not-an-entity.
2. **Document-grounded mention** — a confirmed mapping creates/updates an `EntityObservation`, `RESOLVED_TO` and `Document-[:MENTIONS]->Entity` provenance.
3. **Optional claim** — with at least two curated Entities, an administrator may create a language-neutral predicate ID plus a human-readable label/claim text.
4. **RelationObservation** — the claim stays bound to its source Document and carries `DERIVED_FROM_FINDING` provenance.
5. **No automatic canonical fact edge** — RC3 does not silently convert the claim into a global `Entity -> Entity` truth or query-expansion edge.

## Findings states

- `open` — at least one entity text still needs a decision.
- `entities_resolved` — every entity text was curated or explicitly marked not-an-entity.
- `claimed` — at least one manual document-grounded claim exists.
- `no_entity` — the finding contains no entity text.
- `suppressed` — the finding was manually removed from the working queue while provenance remains stored.

The default Admin view is **open findings**.

## Entity-grouped bulk workflow

Open findings are grouped by unresolved entity text. One finding can therefore appear in more than one group when several entity decisions remain.

For each group an administrator can:

- select individual findings;
- select all currently visible findings in that group;
- assign the selected rows to one suggested/existing Entity; or
- mark that entity text as not-an-entity for the selected rows.

Findings with no entity text have a separate one-action suppression control. Suppression changes curator state only; it does not delete the ResearchFinding or its provenance.

Bulk operations report partial or complete failures. Rows that could not be updated remain open.

## Durable manual state

Manual Graph-Lite decisions must survive later machine re-indexing:

- finding-derived curated `MENTIONS` are restored after document relinking;
- manual finding claims are excluded from replacement of machine-derived relation observations;
- reassigning or suppressing a curated entity marks dependent manual claims `review_required` rather than leaving stale endpoints active.

## Evidence rule

A manual claim should use persisted evidence from the finding/EvidenceFrame when available. The user's search/query intent is not treated as document evidence merely because it led to the finding.

## Predicate IDs

Predicate IDs are stable, language-neutral identifiers such as:

- `shareholder_of`
- `invoiced`
- `works_for`
- `contract_with`

Display labels may be localized. RC3 intentionally does not ship a closed relation ontology.

## ACL boundary

Curated Graph-Lite claims are not automatically used for query expansion in RC3. Before a future release uses them as retrieval signals, that path must preserve evidence ACL semantics or perform a live authorization check against the supporting document.

## Deliberate non-goals in RC3

- automatic promotion of ResearchFindings to global facts;
- automatic use of curated claims for query expansion;
- LLM claim distillation into canonical relations without curator review;
- a mandatory global predicate ontology;
- treating mere co-occurrence as a semantic relation.

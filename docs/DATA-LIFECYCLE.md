# Data lifecycle, deletion, backup and restore

**Reference:** `0.8.5-rc4.1`

AKI deliberately reuses Nextcloud and its FullTextSearch infrastructure, but it also creates derived state. Operators therefore need to distinguish **authoritative source data**, **rebuildable indexes** and **state that contains manual work or credentials**.

This document describes the current technical lifecycle. It is not legal advice and does not claim automatic compliance with any particular retention or data-protection regime.

## 1. Data classes

| Data class | Typical location | Authority / recoverability |
|---|---|---|
| Original documents and archive files | Nextcloud | authoritative source content |
| FullTextSearch index | Elasticsearch | derived from Nextcloud / provider indexing |
| Vector chunks | Qdrant | derived; normally rebuildable from indexed source content |
| Machine-derived graph observations | Neo4j | largely rebuildable, but may be expensive |
| Manual Graph/Findings curation | Neo4j | **not safely reconstructible** from source documents alone |
| User bindings/service credentials | `runtime/users.sqlite` | operationally authoritative for AKI |
| Credential master key | separate key file | required to decrypt encrypted credentials |
| Configuration and runtime secrets | config/runtime environment | deployment-specific operational state |
| Retrieval records | optional runtime files | audit/debug data; not source-of-truth document content |

## 2. Document deletion today

Live ACL and deletion are different problems.

If a source file disappears or a user loses access, live ACL prevents that file from becoming current answer evidence for that user. It does **not** by itself guarantee immediate physical deletion from every derived store.

Current mechanisms include:

- Nextcloud/FullTextSearch lifecycle for the Elasticsearch source index;
- deterministic Qdrant point IDs and sync state so stale/shrunk documents can be removed during synchronization;
- graph rebuild/relink and explicit graph administration for document-derived observations;
- normal Nextcloud deletion/retention for Mail/Web/Chat archive files.

There is currently **no single cross-store command** equivalent to:

```text
aki purge-document files:12345 --plan
aki purge-document files:12345 --execute
```

that proves removal from Elasticsearch/Qdrant/Neo4j/retrieval records/archive derivatives in one transaction. This is a known operational gap.

## 3. Person-related deletion

A command such as "delete everything containing Person X" cannot safely be implemented as a simple text match:

- names are not globally unique;
- OCR errors and aliases exist;
- a document can mention a person without being "their" record;
- legal/retention obligations may differ by document.

A future person/entity purge workflow should therefore be **plan-first and curated**: resolve the intended entity, enumerate provenance/document links, show affected stores, and require explicit confirmation. It should not silently delete by string similarity.

## 4. Archive copies and revocation

An archive item is a new stored object.

For example, a saved chat may contain a summary or quotation from Document X. If that chat is stored as `AKI-Chats/...md`, the archive file has its own Nextcloud file ID and its own ACL. Removing access to Document X does not retroactively rewrite or delete the chat copy.

For this reason:

- `/chatarchive` is optional;
- deployments that value reusable organizational memory may enable it intentionally;
- deployments requiring strict source-revocation propagation should leave it disabled or define an additional retention/purge process.

The same lifecycle distinction applies to deliberately archived public web material.

## 5. Backup priorities

### Must be backed up together for credential recovery

At minimum:

- `runtime/users.sqlite`;
- the credential master key referenced by `RAG_CREDENTIAL_MASTER_KEY_FILE`;
- the relevant configuration/runtime environment needed to locate and interpret the store.

A backup of encrypted credentials without the matching master key is not usable for credential recovery.

### Must be backed up if manual curation matters

Neo4j contains manual identity corrections, merges, Finding entity decisions and manual document-grounded claims. Once such curation exists, treating Neo4j as entirely disposable would lose human work even if machine-derived portions can be regenerated.

### Usually rebuildable, subject to cost

Qdrant is normally rebuildable from the indexed corpus and embedding configuration. Machine-derived graph observations can also be regenerated, but rebuilds may be computationally expensive and can change if extractors/models/configuration have changed.

Elasticsearch recovery is primarily a Nextcloud/FullTextSearch operational concern; AKI does not replace the source platform's own backup strategy.

## 6. Restore order

There is no automated cross-service consistent-restore command in 0.8.5-rc4.1. A conservative manual order is:

1. restore Nextcloud and its authoritative files/shares;
2. restore AKI configuration, `runtime/users.sqlite` and the matching credential master key;
3. restore or rebuild Elasticsearch/FullTextSearch and verify file IDs/paths;
4. restore Neo4j if manual curation must be preserved;
5. restore Qdrant only if its embedding model/configuration still matches; otherwise rebuild it;
6. start AKI and run health/ACL smoke tests with at least two users;
7. reconcile/sync derived stores before reopening the service broadly.

A snapshot that mixes an old `users.sqlite` with a newer master key, or vice versa, can make credentials undecryptable. Treat those as one recovery set.

## 7. Key rotation

The current credential format is versioned and authenticated, but 0.8.5-rc4.1 does not provide a documented zero-downtime master-key rotation workflow for all encrypted rows.

Until a dedicated rotation command exists, operators should not replace the master key independently of the encrypted store. Back up the existing key and database before any credential migration.

## 8. Data-protection roles and remote providers

The software cannot decide the legal role of an organization or provider. Depending on deployment, the operator may be a controller/responsible body and external model/search/hosting providers may require contractual and organizational assessment.

Before routing private evidence to a remote provider, the operator should establish the required contractual basis, retention policy, technical/organizational measures and geographic/organizational restrictions for that provider. AKI's role-specific routing and evidence budgets are technical controls that can support such a policy; they do not replace it.

For German/EU deployments, questions such as AVV/DPA terms, data-subject rights, retention and deletion obligations must be assessed for the actual organization and data set. The current release does not claim an automated Art. 15/17 workflow.

## 9. Planned lifecycle hardening

Useful future additions are:

- plan/execute document purge with per-store results;
- provenance-aware entity/person review for deletion requests;
- explicit archive retention policies;
- backup/restore verification command;
- master-key rotation/migration command;
- admin report showing which derived stores contain state for one document ID.

Until those exist, deletion and restore remain operator-run procedures that should be tested on the deployment's actual profile.

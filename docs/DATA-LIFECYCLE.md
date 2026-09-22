# Data lifecycle, deletion, backup and restore

**Reference:** `0.8.5-rc5`

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

### RC5 lazy Finding cleanup on ACL denial

RC5 starts the purge work conservatively at the Neo4j user-provenance boundary.
When a Finding is checked through the current Nextcloud live ACL and a successful
ACL request definitively does not return its numeric `files:<id>`, AKI removes
that user's `ResearchRun -[:PRODUCED]-> ResearchFinding` provenance only if the
Finding is still uncurated. If no ResearchRun for any user references that
uncurated Finding afterwards, the Finding node is garbage-collected.

A Finding is treated as curated/preserved when it has a Finding curator status,
per-Finding suppressed entity text, a `CURATED_ENTITY` relationship or any
`RelationObservation -[:DERIVED_FROM_FINDING]-> ResearchFinding` provenance.
Those objects remain stored and continue to be hidden from users who no longer
pass the live ACL.

This cleanup is deliberately **not** triggered by timeout, TLS/network failure,
Nextcloud 5xx, rejected/invalid credentials, disabled ACL, or a document
identifier that cannot be tied to a numeric Nextcloud file ID. These cases remain
fail-closed for visibility but non-destructive for stored graph state.

This is not yet a global document deletion workflow and is intentionally not
coupled to Qdrant synchronization. A later central `purge-document` operation
can coordinate Qdrant, Neo4j and other AKI-owned derived stores from an explicit
document-lifecycle event.

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

### RC5 console recovery set

RC5 provides a console-first recovery workflow for AKI-owned state:

```bash
sudo /opt/nextcloud-rag/install/maintenance-mode.sh on
sudo /opt/nextcloud-rag/install/backup-restore.sh create /srv/aki-backups
sudo /opt/nextcloud-rag/install/backup-restore.sh verify /srv/aki-backups/aki-rag-backup-...
```

`create` requires maintenance mode and creates a timestamped recovery set with
SHA-256 checksums. The set contains AKI configuration/runtime/provider state,
`runtime/users.sqlite` with its matching credential master key, discovered AKI
SQLite state, private CA/TLS/operator state below the installation prefix and the
bundled Neo4j data volume when that component belongs to the selected deployment.

Configured CA or other referenced paths outside the AKI installation prefix are
reported as external operator dependencies rather than silently copied. A
credential store or credential master key outside the installation prefix is a
blocking condition for the automatic recovery set because the pair must remain
recoverable together.

The first RC5 recovery format deliberately excludes Nextcloud, Elasticsearch,
Qdrant, external Neo4j, OpenWebUI/Playwright state and model caches. Nextcloud
and Elasticsearch remain source-platform responsibilities; Qdrant is treated as
rebuildable derived state in this version. External Neo4j must have its own
operator-managed backup.

The recovery set contains secrets and the credential master key. Store it with
access controls appropriate for production credentials and, where required by
the deployment policy, on encrypted/off-host backup storage. A bundled Neo4j
container is stopped briefly while its data volume is snapshotted and is returned
to its previous running state afterwards.

## 6. Restore order

For AKI-owned state, verify the selected recovery set before allowing any
destructive restore:

```bash
sudo /opt/nextcloud-rag/install/maintenance-mode.sh on
sudo /opt/nextcloud-rag/install/backup-restore.sh verify /srv/aki-backups/aki-rag-backup-...
sudo /opt/nextcloud-rag/install/backup-restore.sh restore /srv/aki-backups/aki-rag-backup-... --yes
```

The RC5 restore command requires the same supported deployment profile/mode and
installation prefix. Before replacing local state it verifies the recovery-set
checksums, SQLite integrity and that reversible credentials can be decrypted with
the included master key. If bundled Neo4j is part of the set, its local data volume
is restored as part of the operation. Restore deliberately leaves AKI in
maintenance mode.

For a full deployment recovery, the conservative order remains:

1. restore Nextcloud and its authoritative files/shares;
2. prepare the same AKI profile/mode at the same installation prefix and enable maintenance mode;
3. verify and restore the AKI recovery set;
4. restore or rebuild Elasticsearch/FullTextSearch and verify file IDs/paths;
5. restore external Neo4j separately if used; bundled Neo4j is covered by the AKI set;
6. reconcile/rebuild Qdrant and other derived stores as required;
7. run health/smoke/live-ACL checks with at least two users;
8. disable AKI maintenance mode only after those checks pass.

A snapshot that mixes an old `users.sqlite` with a newer master key, or vice
versa, can make credentials undecryptable. The recovery workflow therefore treats
those files as one set and verifies decryption before restore.

## 7. Key rotation

The current credential format is versioned and authenticated, but 0.8.5-rc5 does not provide a documented zero-downtime master-key rotation workflow for all encrypted rows.

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
- master-key rotation/migration command;
- admin report showing which derived stores contain state for one document ID.

These lifecycle workflows should still be tested on the deployment's actual profile; master-key rotation and cross-store purge remain operator-run gaps.

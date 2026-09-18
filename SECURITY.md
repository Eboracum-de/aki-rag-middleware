# Security

## Security model

AKI RAG Middleware treats Elasticsearch, Qdrant and Neo4j as candidate-retrieval systems. They are not authorization authorities. Before document evidence is exposed to a verifier or answer model, access is checked live against Nextcloud for the authenticated user.

Reversible per-user Nextcloud and IMAP credentials, together with pending Nextcloud Login Flow poll tokens, are encrypted at rest in `runtime/users.sqlite` using AES-256-GCM. The credential master key is stored separately and production mode is fail-closed when required encryption cannot be satisfied.

Global service secrets such as API keys and backend passwords remain environment-file configuration in the current release-candidate line. Keep `runtime.env`, live `provider.env`, `runtime/`, TLS private keys and backups out of source control.

## Deployment expectations

- Use HTTPS for Nextcloud and verify TLS certificates.
- Keep RAG Admin behind authentication and an administrator-controlled reverse proxy/network boundary.
- Protect `runtime.env`, `runtime/users.sqlite` and the credential master key with restrictive ownership and permissions.
- Back up the credential master key separately from, but together with, the encrypted credential database.
- Do not manipulate credential rows directly with ad-hoc SQL. Use the Admin UI or supplied CLI commands.
- Treat Elasticsearch/Qdrant/Neo4j as sensitive infrastructure even though they do not authorize access.

## Reporting a vulnerability

Do **not** publish credentials, private document contents, exploit details or sensitive deployment information in a public issue.

Use GitHub private vulnerability reporting once it is enabled for the repository. Until a private reporting route is configured, open a minimal public issue asking the maintainer for a private contact channel without disclosing the vulnerability details.

## LLM trust boundary

The complete private corpus is expected to remain in the local/private retrieval plane. Elasticsearch/Nextcloud access, embeddings, Qdrant and live ACL checks do not need to be exposed to an external LLM provider.

Planner, verifier, evidence-control and answer roles can be configured independently. Remote roles are subject to explicit document/count/character budgets. Those limits reduce exposure but do not make transmitted evidence non-sensitive.

Graph entity/relation extraction is a separate trust decision because it may process larger document portions. Automatic graph-worker startup and automatic enqueue of cited documents are disabled by default in the reference configuration.

Web archive writes have independent TLS verification settings. Disabling TLS verification is a diagnostic exception and should not be a production default.

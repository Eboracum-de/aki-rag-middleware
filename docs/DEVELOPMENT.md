# Development

## Baseline

`0.8.5-rc3` is the first public release candidate. Earlier RC and draft identifiers were internal development snapshots and are not maintained as public upgrade targets. `0.8.5-rc3` and keeps one codebase with two explicit axes: functional profile and deployment mode. Regression-tested mappings are `standard+native` and `super-light+dockerized`.

## Repository layout

```text
rag/                 Python middleware, provider, workers and Admin UI
prompts/             LLM prompt templates
ontology/            graph relation ontology
install/             installer, Docker Compose, nginx and systemd templates
tests/               regression tests
tools/               development/diagnostic tools
docs/                current architecture and administration documentation
config.yaml           middleware reference configuration
web.yaml              Web Research reference configuration
provider.env.example  provider/reference environment without secrets
versions.lock.yaml    immutable container/model compatibility pins
```

Runtime-local files are deliberately not tracked. A fresh installer creates or preserves the local `provider.env`, `runtime.env`, `runtime/` database/key material and TLS state.


## Retrieval contract

The normal provider path uses one small `SearchSpec` per retrieval round. The
Query Rewriter may write a human-style Nextcloud full-text expression in
`elastic_query`; it must never emit raw Elasticsearch JSON DSL. `semantic_query`
is reserved for the vector arm. Neo4j seed/alias context is supplied before the
rewrite, while `entities`, `concepts`, `constraints` and
`verification_requirements` remain analytical side-products. Additional
retrieval rounds may revise the SearchSpec but must re-use the same pipeline.

## Tests

Create a virtual environment and install the runtime requirements, then run:

```bash
python -m pytest
```

Some graph/vector tests require the optional runtime client libraries listed in `requirements.txt`. The deployment regression tests also inspect Docker/installer/config files directly and therefore catch accidental changes to the supported topology.

## Release rule

Keep functional changes separate from repository/documentation cleanup where practical. Before a release candidate is tagged:

1. run the full pytest suite in a clean environment;
2. run the installer on a blank VM using the intended component flags;
3. execute the acceptance matrix for the profile being released (for Super-Light: API/provider, AKI/Login Flow, live ACL, Kontakt-DB, Web archive, Elasticsearch degradation and container restart);
4. regenerate `MANIFEST.sha256` for distributable tarballs;
5. scan the final tree for runtime databases, API keys, passwords, private keys and local environment files.

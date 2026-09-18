# Changelog

## 0.2.0

- Add `--unreconcile` to cancel pending `INDEX_REMOVE` marks before Full Text Search processes them.
- Preserve existing index status bits when applying `--reconcile`.
- Legacy v0.1.0 `INDEX_REMOVE`-only entries are reset to `INDEX_FULL` when unreconciled.
- Declare compatibility with Nextcloud 23 through 35.
- Add Eboracum/OpenAI copyright notice to `appinfo/info.xml`.

## 0.1.0

- Initial dry-run-first FTS/filecache reconciliation command.

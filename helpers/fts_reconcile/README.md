# Full Text Search Reconcile

Small maintenance-only Nextcloud app for reconciling stale `files` provider entries in Full Text Search against Nextcloud's current `filecache`.

## Safety model

- Dry-run is the default.
- Only the Full Text Search provider `files` is inspected.
- Only document IDs that can safely be mapped to a numeric Nextcloud `fileid` are considered.
- A document is considered stale only when its file ID no longer exists in `filecache`.
- `--reconcile` does **not** delete rows directly from Elasticsearch. It uses Nextcloud's public Full Text Search API to add `INDEX_REMOVE`; existing status bits are preserved so the pending mark can be cancelled.
- `--unreconcile` cancels pending `INDEX_REMOVE` marks on stale entries **before** the normal Full Text Search indexing process has processed them. It cannot recover an entry that Full Text Search has already deleted. Legacy marks made by v0.1.0 that contain only `INDEX_REMOVE` are reset to `INDEX_FULL` so Nextcloud can re-evaluate them.
- The configured Full Text Search indexing process then performs the platform deletion and removes the FTS bookkeeping entry.

This is deliberately conservative: it can miss some stale entries if `filecache` itself is stale, but it should not remove an entry merely because a path changed or a user no longer sees the file.

## Compatibility

The package declares Nextcloud 23 through 35. The implementation intentionally uses public OCP APIs present in NC23 and still present in current Nextcloud versions. It is written without PHP language features newer than PHP 7.3.

Test target for the first run:

- Nextcloud 23.0.1
- fulltextsearch 23.0.0
- files_fulltextsearch 23.0.2
- fulltextsearch_elasticsearch 23.0.1

## Install on the test clone

From the Nextcloud server:

```bash
cd /srv/www/htdocs/nextcloud
sudo tar xzf /path/to/fts_reconcile-0.2.0.tar.gz -C apps/
sudo chown -R wwwrun:www apps/fts_reconcile
sudo -u wwwrun php occ app:enable fts_reconcile
```

Check the command:

```bash
sudo -u wwwrun php occ help fts_reconcile:files
```

## Dry-run

```bash
cd /srv/www/htdocs/nextcloud
sudo -u wwwrun php occ fts_reconcile:files
```

Optional:

```bash
sudo -u wwwrun php occ fts_reconcile:files --show=50 --batch-size=1000
```

No data is changed without `--reconcile`.

## Reconcile

Only after reviewing the dry-run:

```bash
sudo -u wwwrun php occ fts_reconcile:files --reconcile
```

This marks stale entries `INDEX_REMOVE`. Then run the normal Full Text Search indexing process so the search platform processes those removals:

```bash
sudo -u wwwrun php occ fulltextsearch:index
```

Run the reconciler once more afterwards; stale entries should then be gone (or at least the `Already INDEX_REMOVE` count should shrink as the indexing process processes them).


## Unreconcile (emergency undo)

If an administrator notices immediately after `--reconcile` that the wrong storage/cache state was used, cancel pending removal marks **before running `fulltextsearch:index`**:

```bash
sudo -u wwwrun php occ fts_reconcile:files --unreconcile
```

`--reconcile` and `--unreconcile` are mutually exclusive. `--unreconcile` only acts on stale `files` entries that are currently marked `INDEX_REMOVE`. It does not recreate rows that the normal Full Text Search indexing process has already deleted. Restore the underlying storage/filecache state before re-indexing.

## Recommended first test

On the clone, start with the plain dry-run and share only the summary counts plus a few stale IDs. Do not use `--reconcile` until those numbers look plausible.

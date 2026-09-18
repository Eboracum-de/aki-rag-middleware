<?php

declare(strict_types=1);

namespace OCA\FtsReconcile\Command;

use OCP\DB\QueryBuilder\IQueryBuilder;
use OCP\FullTextSearch\IFullTextSearchManager;
use OCP\FullTextSearch\Model\IIndex;
use OCP\IDBConnection;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

class ReconcileFiles extends Command {
    /** @var IDBConnection */
    private $db;

    /** @var IFullTextSearchManager */
    private $ftsManager;

    public function __construct(IDBConnection $db, IFullTextSearchManager $ftsManager) {
        parent::__construct();
        $this->db = $db;
        $this->ftsManager = $ftsManager;
    }

    protected function configure(): void {
        $this
            ->setName('fts_reconcile:files')
            ->setDescription('Find stale files-provider FTS entries; dry-run unless --reconcile or --unreconcile is supplied')
            ->addOption(
                'reconcile',
                null,
                InputOption::VALUE_NONE,
                'Mark stale FTS entries INDEX_REMOVE using the public Full Text Search API'
            )
            ->addOption(
                'unreconcile',
                null,
                InputOption::VALUE_NONE,
                'Cancel pending INDEX_REMOVE marks for stale FTS entries before Full Text Search has processed them'
            )
            ->addOption(
                'batch-size',
                null,
                InputOption::VALUE_REQUIRED,
                'Number of FTS rows checked per batch (100-5000)',
                '1000'
            )
            ->addOption(
                'show',
                null,
                InputOption::VALUE_REQUIRED,
                'Maximum number of stale document IDs to print as examples',
                '20'
            );
    }

    protected function execute(InputInterface $input, OutputInterface $output): int {
        $apply = (bool)$input->getOption('reconcile');
        $undo = (bool)$input->getOption('unreconcile');

        if ($apply && $undo) {
            $output->writeln('<error>--reconcile and --unreconcile are mutually exclusive.</error>');
            return 2;
        }
        $batchSize = (int)$input->getOption('batch-size');
        $show = (int)$input->getOption('show');

        if ($batchSize < 100 || $batchSize > 5000) {
            $output->writeln('<error>--batch-size must be between 100 and 5000.</error>');
            return 2;
        }
        if ($show < 0 || $show > 1000) {
            $output->writeln('<error>--show must be between 0 and 1000.</error>');
            return 2;
        }

        $stats = [
            'fts_files_entries' => 0,
            'recognised_document_ids' => 0,
            'live_filecache_entries' => 0,
            'stale_entries' => 0,
            'already_marked_remove' => 0,
            'to_mark_remove' => 0,
            'unrecognised_document_ids' => 0,
            'marked_remove' => 0,
            'unreconcile_candidates' => 0,
            'unreconciled' => 0,
            'unreconcile_forced_full' => 0,
        ];
        $examples = [];
        $offset = 0;

        $output->writeln('Full Text Search file reconciliation');
        if ($apply) {
            $output->writeln('<comment>Mode: RECONCILE (stale entries will be marked INDEX_REMOVE)</comment>');
        } elseif ($undo) {
            $output->writeln('<comment>Mode: UNRECONCILE (pending INDEX_REMOVE marks on stale entries will be cancelled)</comment>');
        } else {
            $output->writeln('<info>Mode: DRY-RUN (no changes will be made)</info>');
        }
        $output->writeln('');

        try {
            while (true) {
                $rows = $this->loadFtsBatch($offset, $batchSize);
                if (empty($rows)) {
                    break;
                }

                $stats['fts_files_entries'] += count($rows);
                $fileIds = [];
                $rowMap = [];

                foreach ($rows as $row) {
                    $documentId = (string)$row['document_id'];
                    $fileId = $this->extractFileId($documentId);
                    if ($fileId === null) {
                        $stats['unrecognised_document_ids']++;
                        continue;
                    }

                    $stats['recognised_document_ids']++;
                    $fileIds[] = $fileId;
                    $rowMap[$documentId] = [
                        'fileid' => $fileId,
                        'status' => (int)$row['status'],
                    ];
                }

                $existing = $this->loadExistingFileIds($fileIds);
                $toMark = [];

                foreach ($rowMap as $documentId => $meta) {
                    $key = (string)$meta['fileid'];
                    if (isset($existing[$key])) {
                        $stats['live_filecache_entries']++;
                        continue;
                    }

                    $stats['stale_entries']++;
                    if (count($examples) < $show) {
                        $examples[] = $documentId;
                    }

                    if (($meta['status'] & IIndex::INDEX_REMOVE) === IIndex::INDEX_REMOVE) {
                        $stats['already_marked_remove']++;
                        if ($undo) {
                            $stats['unreconcile_candidates']++;
                            $toMark[] = $documentId;
                        }
                        continue;
                    }

                    $stats['to_mark_remove']++;
                    if ($apply) {
                        $toMark[] = $documentId;
                    }
                }

                if ($apply && !empty($toMark)) {
                    foreach (array_chunk($toMark, 500) as $chunk) {
                        // Preserve existing status bits so --unreconcile can remove only INDEX_REMOVE.
                        $this->ftsManager->updateIndexesStatus(
                            'files',
                            $chunk,
                            IIndex::INDEX_REMOVE,
                            false
                        );
                        $stats['marked_remove'] += count($chunk);
                    }
                } elseif ($undo && !empty($toMark)) {
                    foreach (array_chunk($toMark, 200) as $chunk) {
                        foreach ($chunk as $documentId) {
                            $index = $this->ftsManager->getIndex('files', $documentId);
                            $before = $index->getStatus();
                            $index->unsetStatus(IIndex::INDEX_REMOVE);

                            // v0.1.0 used reset=true and could leave status exactly INDEX_REMOVE.
                            // In that legacy case, request a full re-index rather than persisting status 0.
                            if ($index->getStatus() === 0) {
                                $index->setStatus(IIndex::INDEX_FULL, true);
                                $stats['unreconcile_forced_full']++;
                            }

                            if ($before !== $index->getStatus()) {
                                $this->ftsManager->updateIndexes([$index]);
                                $stats['unreconciled']++;
                            }
                        }
                    }
                }

                $offset += count($rows);
                if (count($rows) < $batchSize) {
                    break;
                }
            }
        } catch (\Throwable $e) {
            $output->writeln('<error>Reconciliation aborted: ' . $e->getMessage() . '</error>');
            return 1;
        }

        $output->writeln('FTS files entries checked:       ' . $stats['fts_files_entries']);
        $output->writeln('Recognised file document IDs:   ' . $stats['recognised_document_ids']);
        $output->writeln('Still present in filecache:     ' . $stats['live_filecache_entries']);
        $output->writeln('Stale FTS entries:              ' . $stats['stale_entries']);
        $output->writeln('Already INDEX_REMOVE:           ' . $stats['already_marked_remove']);
        $output->writeln('Need INDEX_REMOVE:              ' . $stats['to_mark_remove']);
        $output->writeln('Unrecognised document IDs:      ' . $stats['unrecognised_document_ids']);
        if ($apply) {
            $output->writeln('Marked INDEX_REMOVE this run:   ' . $stats['marked_remove']);
        } elseif ($undo) {
            $output->writeln('Pending marks to cancel:        ' . $stats['unreconcile_candidates']);
            $output->writeln('Unreconciled this run:          ' . $stats['unreconciled']);
            $output->writeln('Legacy marks reset INDEX_FULL:  ' . $stats['unreconcile_forced_full']);
        }

        if (!empty($examples)) {
            $output->writeln('');
            $output->writeln('Stale document ID examples:');
            foreach ($examples as $documentId) {
                $output->writeln('  ' . $documentId);
            }
        }

        $output->writeln('');
        if ($apply) {
            if ($stats['marked_remove'] > 0 || $stats['already_marked_remove'] > 0) {
                $output->writeln('<comment>FTS entries are now queued for removal.</comment>');
                $output->writeln('Run the normal Full Text Search indexing process to let the configured platform remove them, e.g.:');
                $output->writeln('  php occ fulltextsearch:index');
            } else {
                $output->writeln('<info>No stale entries needed reconciliation.</info>');
            }
        } elseif ($undo) {
            if ($stats['unreconciled'] > 0) {
                $output->writeln('<comment>Pending INDEX_REMOVE marks were cancelled.</comment>');
                if ($stats['unreconcile_forced_full'] > 0) {
                    $output->writeln('Legacy v0.1.0 marks with no remaining status bits were reset to INDEX_FULL.');
                }
                $output->writeln('Important: this is only an undo of the pending FTS status. If the source file is still absent, restore the storage/filecache state before running fulltextsearch:index.');
            } else {
                $output->writeln('<info>No pending INDEX_REMOVE marks on stale entries needed unreconciliation.</info>');
            }
        } else {
            $output->writeln('<info>No changes made.</info>');
            if ($stats['to_mark_remove'] > 0) {
                $output->writeln('Run again with --reconcile to mark these entries INDEX_REMOVE.');
            }
        }

        if ($stats['unrecognised_document_ids'] > 0) {
            $output->writeln('<comment>Safety note: unrecognised document IDs were not modified.</comment>');
        }

        return 0;
    }

    /**
     * @return array<int,array{document_id:mixed,status:mixed}>
     */
    private function loadFtsBatch(int $offset, int $limit): array {
        $qb = $this->db->getQueryBuilder();
        $qb->select('document_id', 'status')
            ->from('fulltextsearch_indexes')
            ->where(
                $qb->expr()->eq(
                    'provider_id',
                    $qb->createNamedParameter('files', IQueryBuilder::PARAM_STR)
                )
            )
            ->orderBy('document_id', 'ASC')
            ->setFirstResult($offset)
            ->setMaxResults($limit);

        $result = $qb->executeQuery();
        $rows = [];
        while (($row = $result->fetch()) !== false) {
            $rows[] = $row;
        }
        $result->closeCursor();

        return $rows;
    }

    /**
     * @param int[] $fileIds
     * @return array<string,bool>
     */
    private function loadExistingFileIds(array $fileIds): array {
        if (empty($fileIds)) {
            return [];
        }

        $fileIds = array_values(array_unique($fileIds));
        $qb = $this->db->getQueryBuilder();
        $qb->select('fileid')
            ->from('filecache')
            ->where(
                $qb->expr()->in(
                    'fileid',
                    $qb->createNamedParameter($fileIds, IQueryBuilder::PARAM_INT_ARRAY)
                )
            );

        $result = $qb->executeQuery();
        $existing = [];
        while (($row = $result->fetch()) !== false) {
            $existing[(string)$row['fileid']] = true;
        }
        $result->closeCursor();

        return $existing;
    }

    private function extractFileId(string $documentId): ?int {
        if (ctype_digit($documentId)) {
            return (int)$documentId;
        }

        if (preg_match('/^files:(\d+)$/', $documentId, $matches) === 1) {
            return (int)$matches[1];
        }

        return null;
    }
}

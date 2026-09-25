<?php
namespace OCA\Sunaq\Service;

use OCP\Files\IRootFolder;
use OCP\IUserSession;
use OCP\IConfig;

class ChatMetadataCorruptionException extends \RuntimeException {}

class ChatStore {
    const FOLDER = 'SunaQ-Chats';
    const MAX_MESSAGES = 80;

    /** @var IRootFolder */
    private $rootFolder;
    /** @var IUserSession */
    private $userSession;
    /** @var IConfig */
    private $config;

    public function __construct(IRootFolder $rootFolder, IUserSession $userSession, IConfig $config) {
        $this->rootFolder = $rootFolder;
        $this->userSession = $userSession;
        $this->config = $config;
    }

    private function userFolder() {
        $user = $this->userSession->getUser();
        if ($user === null) {
            throw new \RuntimeException('Keine angemeldete Nextcloud-Sitzung gefunden.');
        }
        return $this->rootFolder->getUserFolder($user->getUID());
    }

    private function normalizeArchivePath($path) {
        $value = trim((string)$path);
        $value = trim($value, '/');
        if ($value === '') {
            $value = self::FOLDER;
        }
        if (strlen($value) > 240 || strpos($value, '\\') !== false) {
            throw new \InvalidArgumentException('Ungültiger Chatarchiv-Pfad.');
        }
        $parts = explode('/', $value);
        foreach ($parts as &$part) {
            $part = trim((string)$part);
            if ($part === '' || $part === '.' || $part === '..' || preg_match('/[\x00-\x1F\x7F]/', $part)) {
                throw new \InvalidArgumentException('Ungültiger Chatarchiv-Pfad.');
            }
        }
        unset($part);
        return implode('/', $parts);
    }

    private function archivePath() {
        $user = $this->userSession->getUser();
        if ($user === null) {
            throw new \RuntimeException('Keine angemeldete Nextcloud-Sitzung gefunden.');
        }
        $stored = $this->config->getUserValue(
            $user->getUID(),
            'sunaq',
            'chat_archive_path',
            self::FOLDER
        );
        return $this->normalizeArchivePath($stored);
    }

    public function setArchivePath($path) {
        $user = $this->userSession->getUser();
        if ($user === null) {
            throw new \RuntimeException('Keine angemeldete Nextcloud-Sitzung gefunden.');
        }
        $value = $this->normalizeArchivePath($path);
        $this->config->setUserValue($user->getUID(), 'sunaq', 'chat_archive_path', $value);
        return $value;
    }

    private function archiveFolder($create = true) {
        $folder = $this->userFolder();
        foreach (explode('/', $this->archivePath()) as $segment) {
            if ($folder->nodeExists($segment)) {
                $next = $folder->get($segment);
                if (!method_exists($next, 'getDirectoryListing')) {
                    throw new \RuntimeException('Chatarchiv-Pfad kollidiert mit einer Datei.');
                }
                $folder = $next;
                continue;
            }
            if (!$create) {
                return null;
            }
            $folder = $folder->newFolder($segment);
        }
        return $folder;
    }

    private function cleanId($id) {
        $id = (string)$id;
        if ($id !== '' && preg_match('/^[A-Za-z0-9_-]{8,64}$/', $id)) {
            return $id;
        }
        return bin2hex(random_bytes(12));
    }

    private function metaName($id) {
        return '.' . $id . '.sunaq.json';
    }

    private function legacyMetaName($id) {
        return '.' . $id . '.akirag.json';
    }

    private function legacyHtmlName($id) {
        return $id . '.html';
    }

    private function cleanArchiveTitle($title) {
        $value = preg_replace('/[\\x00-\\x1F\\x7F\\/\\\\:*?"<>|#%]+/u', ' ', (string)$title);
        $value = preg_replace('/\\s+/u', ' ', trim((string)$value));
        if ($value === '') {
            $value = 'Recherche';
        }
        if (function_exists('mb_substr')) {
            return mb_substr($value, 0, 48);
        }
        return substr($value, 0, 48);
    }

    private function markdownName($record) {
        $date = substr((string)($record['created_at'] ?? ''), 0, 10);
        if (!preg_match('/^\\d{4}-\\d{2}-\\d{2}$/', $date)) {
            $date = gmdate('Y-m-d');
        }
        $title = $this->cleanArchiveTitle($record['title'] ?? 'Recherche');
        $shortId = substr((string)$record['id'], 0, 8);
        return $date . ' - ' . $title . ' - ' . $shortId . '.md';
    }

    private function recoverMarkdownName($folder, $id) {
        $shortId = substr((string)$id, 0, 8);
        if ($shortId === '') {
            return '';
        }
        $matches = [];
        $pattern = '/^\\d{4}-\\d{2}-\\d{2} - .+ - ' . preg_quote($shortId, '/') . '\\.md$/u';
        foreach ($folder->getDirectoryListing() as $node) {
            $name = (string)$node->getName();
            if (preg_match($pattern, $name)) {
                $content = (string)$node->getContent();
                if (strpos($content, "\n- Chat-ID: " . $id . "\n") === false) {
                    continue;
                }
                $matches[] = $name;
                if (count($matches) > 1) {
                    return '';
                }
            }
        }
        return count($matches) === 1 ? $matches[0] : '';
    }

    private function writeFile($folder, $name, $content) {
        if ($folder->nodeExists($name)) {
            $file = $folder->get($name);
        } else {
            $file = $folder->newFile($name);
        }
        $file->putContent((string)$content);
        return $file;
    }

    private function resolveArchiveFile($folder, $id, $record) {
        $archiveFile = is_array($record) ? trim((string)($record['archive_file'] ?? '')) : '';
        if ($archiveFile !== '' && $folder->nodeExists($archiveFile)) {
            return $archiveFile;
        }
        $recovered = $this->recoverMarkdownName($folder, $id);
        if ($recovered !== '') {
            return $recovered;
        }
        $legacyHtml = $this->legacyHtmlName($id);
        if ($folder->nodeExists($legacyHtml)) {
            return $legacyHtml;
        }
        return '';
    }

    private function deleteMetadataFiles($folder, $id) {
        foreach ([$this->metaName($id), $this->legacyMetaName($id)] as $name) {
            if ($folder->nodeExists($name)) {
                $folder->get($name)->delete();
            }
        }
    }

    private function normalizeScopes($scopes) {
        $allowed = ['documents', 'mailarchive', 'webarchive', 'chatarchive', 'web'];
        $out = [];
        if (!is_array($scopes)) {
            return $out;
        }
        foreach ($scopes as $scope) {
            $value = strtolower(trim((string)$scope));
            if (in_array($value, $allowed, true) && !in_array($value, $out, true)) {
                $out[] = $value;
            }
        }
        return $out;
    }

    private function normalizeMessages($messages) {
        $out = [];
        foreach (array_slice(is_array($messages) ? $messages : [], -self::MAX_MESSAGES) as $message) {
            if (!is_array($message)) {
                continue;
            }
            $role = isset($message['role']) ? (string)$message['role'] : '';
            if ($role !== 'user' && $role !== 'assistant') {
                continue;
            }
            $content = isset($message['content']) ? trim((string)$message['content']) : '';
            if ($content === '') {
                continue;
            }
            $item = ['role' => $role, 'content' => $content];
            $createdAt = isset($message['created_at']) ? trim((string)$message['created_at']) : '';
            if ($createdAt !== '' && strlen($createdAt) <= 64) {
                try {
                    $dt = new \DateTimeImmutable($createdAt);
                    $item['created_at'] = $dt->format(DATE_ATOM);
                } catch (\Exception $e) {
                    // Ignore malformed client timestamps; older chats have none.
                }
            }
            if ($role === 'assistant' && isset($message['source_scopes'])) {
                $sourceScopes = $this->normalizeScopes($message['source_scopes']);
                if ($sourceScopes) {
                    $item['source_scopes'] = $sourceScopes;
                }
            }
            if ($role === 'assistant' && isset($message['sources']) && is_array($message['sources'])) {
                $sources = [];
                foreach ($message['sources'] as $source) {
                    if (is_array($source)) {
                        $index = isset($source['index']) ? (int)$source['index'] : 0;
                        $reference = isset($source['reference']) ? trim((string)$source['reference']) : '';
                    } else {
                        $index = 0;
                        $reference = trim((string)$source);
                    }
                    if ($reference !== '') {
                        $sources[] = ['index' => $index, 'reference' => $reference];
                    }
                }
                if ($sources) {
                    $item['sources'] = $sources;
                }
            }
            $out[] = $item;
        }
        return $out;
    }

    private function defaultTitle($messages) {
        foreach ($messages as $message) {
            if (($message['role'] ?? '') === 'user') {
                $title = preg_replace('/\s+/', ' ', trim((string)$message['content']));
                if (function_exists('mb_substr')) {
                    return mb_substr($title, 0, 80);
                }
                return substr($title, 0, 80);
            }
        }
        return 'Neue Recherche';
    }

    private function renderMarkdown($record) {
        $title = preg_replace('/\\s+/u', ' ', trim((string)($record['title'] ?? 'Recherche')));
        $parts = [
            '# ' . $title,
            '',
            '**SunaQ Recherche**',
            '',
            '- Erstellt: ' . (string)($record['created_at'] ?? ''),
            '- Aktualisiert: ' . (string)($record['updated_at'] ?? ''),
            '- Chat-ID: ' . (string)($record['id'] ?? ''),
            '',
        ];
        $scopeLabels = [
            'documents' => 'Dokumente',
            'mailarchive' => 'Mailarchiv',
            'webarchive' => 'Webarchiv',
            'chatarchive' => 'Chatarchiv',
            'web' => 'Web',
        ];
        foreach ($record['messages'] as $message) {
            $role = ($message['role'] ?? '') === 'user' ? 'Benutzer' : 'SunaQ';
            $parts[] = '## ' . $role;
            $parts[] = '';

            $meta = [];
            $stamp = isset($message['created_at']) ? trim((string)$message['created_at']) : '';
            if ($stamp !== '') {
                $meta[] = $stamp;
            }
            $messageScopes = $this->normalizeScopes($message['source_scopes'] ?? []);
            if ($messageScopes) {
                $labels = array_map(function ($scope) use ($scopeLabels) {
                    return $scopeLabels[$scope] ?? $scope;
                }, $messageScopes);
                $meta[] = 'Quellen: ' . implode(', ', $labels);
            }
            if ($meta) {
                $parts[] = '*' . implode(' · ', $meta) . '*';
                $parts[] = '';
            }

            $parts[] = (string)($message['content'] ?? '');
            $parts[] = '';

            // Technical source handoff IDs stay in the hidden metadata sidecar.
            // The readable Markdown already contains the answer's user-facing
            // source list and must not expose internal files:<id> bookkeeping.
        }
        return rtrim(implode("\n", $parts)) . "\n";
    }

    public function save($id, $messages, $scopes = [], $title = '') {
        $folder = $this->archiveFolder(true);
        $id = $this->cleanId($id);
        $normalized = $this->normalizeMessages($messages);
        $now = gmdate('c');
        $metadataCorrupt = false;
        try {
            $existing = $this->load($id, false);
        } catch (ChatMetadataCorruptionException $e) {
            // Damaged metadata must not block saving a new message. Treat the
            // record as absent; the next save rewrites a valid metadata file.
            $existing = null;
            $metadataCorrupt = true;
        }
        $record = [
            'id' => $id,
            'title' => trim((string)$title) !== '' ? trim((string)$title) : ($existing['title'] ?? $this->defaultTitle($normalized)),
            'created_at' => $existing['created_at'] ?? $now,
            'updated_at' => $now,
            'scopes' => $this->normalizeScopes($scopes),
            'messages' => $normalized,
            'source_origin' => 'chat_archive',
            'format' => 'markdown',
        ];

        $previousArchiveFile = is_array($existing) ? trim((string)($existing['archive_file'] ?? '')) : '';
        if ($previousArchiveFile === '' && ($metadataCorrupt || is_array($existing))) {
            $previousArchiveFile = $this->recoverMarkdownName($folder, $id);
        }
        // Keep the readable file name stable after first creation so normal
        // chat title edits do not replace the Nextcloud file and change fileid.
        $archiveFile = (
            $previousArchiveFile !== ''
            && substr($previousArchiveFile, -3) === '.md'
            && $folder->nodeExists($previousArchiveFile)
        ) ? $previousArchiveFile : $this->markdownName($record);

        $markdown = $this->writeFile($folder, $archiveFile, $this->renderMarkdown($record));
        $record['archive_file'] = $archiveFile;
        $record['archive_path'] = $this->archivePath() . '/' . $archiveFile;
        $record['document_id'] = 'files:' . (string)$markdown->getId();

        $legacyHtml = $this->legacyHtmlName($id);
        if ($folder->nodeExists($legacyHtml)) {
            $folder->get($legacyHtml)->delete();
        }

        $this->writeFile(
            $folder,
            $this->metaName($id),
            json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT)
        );
        if ($folder->nodeExists($this->legacyMetaName($id))) {
            $folder->get($this->legacyMetaName($id))->delete();
        }
        return $record;
    }

    public function load($id, $throwIfMissing = true) {
        $id = $this->cleanId($id);
        $folder = $this->archiveFolder(false);
        if ($folder === null) {
            if ($throwIfMissing) {
                throw new \InvalidArgumentException('Chat nicht gefunden.');
            }
            return null;
        }
        $metaName = $this->metaName($id);
        if (!$folder->nodeExists($metaName) && $folder->nodeExists($this->legacyMetaName($id))) {
            $metaName = $this->legacyMetaName($id);
        }
        if (!$folder->nodeExists($metaName)) {
            if ($throwIfMissing) {
                throw new \InvalidArgumentException('Chat nicht gefunden.');
            }
            return null;
        }
        $raw = $folder->get($metaName)->getContent();
        $record = json_decode((string)$raw, true);
        if (!is_array($record)) {
            throw new ChatMetadataCorruptionException('Gespeicherter Chat ist beschädigt.');
        }

        // The readable archive file is the lifecycle anchor.  If a user deletes
        // it manually in Nextcloud, stale hidden metadata must not keep the chat
        // alive as an invisible duplicate.  The delete-event listener handles
        // the normal case immediately; this is the repair path for older/missed
        // events.
        $archiveFile = $this->resolveArchiveFile($folder, $id, $record);
        if ($archiveFile === '') {
            $this->deleteMetadataFiles($folder, $id);
            if ($throwIfMissing) {
                throw new \InvalidArgumentException('Chat nicht gefunden.');
            }
            return null;
        }
        if (empty($record['archive_file'])) {
            $record['archive_file'] = $archiveFile;
        }
        return $record;
    }

    public function listChats() {
        $folder = $this->archiveFolder(false);
        if ($folder === null) {
            return [];
        }
        $items = [];
        foreach ($folder->getDirectoryListing() as $node) {
            $name = $node->getName();
            if (!preg_match('/^\.([A-Za-z0-9_-]{8,64})\.(?:sunaq|akirag)\.json$/', $name, $match)) {
                continue;
            }
            try {
                $record = json_decode((string)$node->getContent(), true);
                if (is_array($record)) {
                    $id = (string)($record['id'] ?? $match[1]);
                    if ($this->resolveArchiveFile($folder, $id, $record) === '') {
                        $this->deleteMetadataFiles($folder, $id);
                        continue;
                    }
                    $items[] = [
                        'id' => $id,
                        'title' => (string)($record['title'] ?? 'Recherche'),
                        'updated_at' => (string)($record['updated_at'] ?? ''),
                        'created_at' => (string)($record['created_at'] ?? ''),
                        'scopes' => is_array($record['scopes'] ?? null) ? $record['scopes'] : [],
                    ];
                }
            } catch (\Exception $e) {
                // One damaged chat must not hide the rest of the archive.
            }
        }
        usort($items, function ($a, $b) {
            return strcmp((string)$b['updated_at'], (string)$a['updated_at']);
        });
        return $items;
    }

    public function rename($id, $title) {
        try {
            $record = $this->load($id);
        } catch (ChatMetadataCorruptionException $e) {
            throw new \InvalidArgumentException('Gespeicherter Chat ist beschädigt und kann nicht umbenannt werden.');
        }
        $title = trim((string)$title);
        if ($title === '') {
            throw new \InvalidArgumentException('Titel darf nicht leer sein.');
        }
        return $this->save($record['id'], $record['messages'], $record['scopes'] ?? [], $title);
    }

    public function delete($id) {
        $id = $this->cleanId($id);
        $folder = $this->archiveFolder(false);
        if ($folder === null) {
            return;
        }
        $metadataCorrupt = false;
        try {
            $record = $this->load($id, false);
        } catch (ChatMetadataCorruptionException $e) {
            // Confirmed damaged metadata must not prevent deletion of its
            // matching managed archive. Storage/read failures still propagate.
            $record = null;
            $metadataCorrupt = true;
        }
        $names = [$this->metaName($id), $this->legacyMetaName($id), $this->legacyHtmlName($id)];
        if (is_array($record) && !empty($record['archive_file'])) {
            $names[] = (string)$record['archive_file'];
        } elseif ($metadataCorrupt || is_array($record)) {
            $recoveredArchive = $this->recoverMarkdownName($folder, $id);
            if ($recoveredArchive !== '') {
                $names[] = $recoveredArchive;
            }
        }
        foreach (array_unique($names) as $name) {
            if ($folder->nodeExists($name)) {
                $folder->get($name)->delete();
            }
        }
    }
}

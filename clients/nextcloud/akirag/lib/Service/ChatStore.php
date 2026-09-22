<?php
namespace OCA\AkiRag\Service;

use OCP\Files\IRootFolder;
use OCP\IUserSession;

class ChatStore {
    const FOLDER = 'AKI-Chats';
    const MAX_MESSAGES = 80;

    /** @var IRootFolder */
    private $rootFolder;
    /** @var IUserSession */
    private $userSession;

    public function __construct(IRootFolder $rootFolder, IUserSession $userSession) {
        $this->rootFolder = $rootFolder;
        $this->userSession = $userSession;
    }

    private function userFolder() {
        $user = $this->userSession->getUser();
        if ($user === null) {
            throw new \RuntimeException('Keine angemeldete Nextcloud-Sitzung gefunden.');
        }
        return $this->rootFolder->getUserFolder($user->getUID());
    }

    private function archiveFolder($create = true) {
        $root = $this->userFolder();
        if (!$root->nodeExists(self::FOLDER)) {
            if (!$create) {
                return null;
            }
            return $root->newFolder(self::FOLDER);
        }
        return $root->get(self::FOLDER);
    }

    private function cleanId($id) {
        $id = (string)$id;
        if ($id !== '' && preg_match('/^[A-Za-z0-9_-]{8,64}$/', $id)) {
            return $id;
        }
        return bin2hex(random_bytes(12));
    }

    private function metaName($id) {
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

    private function writeFile($folder, $name, $content) {
        if ($folder->nodeExists($name)) {
            $file = $folder->get($name);
        } else {
            $file = $folder->newFile($name);
        }
        $file->putContent((string)$content);
        return $file;
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
            '**AKI Recherche**',
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
            $role = ($message['role'] ?? '') === 'user' ? 'Benutzer' : 'AKI';
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

            if (!empty($message['sources']) && is_array($message['sources'])) {
                $parts[] = '### Quellen';
                $parts[] = '';
                foreach ($message['sources'] as $source) {
                    $index = (int)($source['index'] ?? 0);
                    $reference = trim((string)($source['reference'] ?? ''));
                    if ($reference !== '') {
                        $prefix = $index > 0 ? '[' . $index . '] ' : '';
                        $parts[] = '- ' . $prefix . $reference;
                    }
                }
                $parts[] = '';
            }
        }
        return rtrim(implode("\n", $parts)) . "\n";
    }

    public function save($id, $messages, $scopes = [], $title = '') {
        $folder = $this->archiveFolder(true);
        $id = $this->cleanId($id);
        $normalized = $this->normalizeMessages($messages);
        $now = gmdate('c');
        $existing = $this->load($id, false);
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
        // Keep the readable file name stable after first creation so normal
        // chat title edits do not replace the Nextcloud file and change fileid.
        $archiveFile = (
            $previousArchiveFile !== ''
            && substr($previousArchiveFile, -3) === '.md'
            && $folder->nodeExists($previousArchiveFile)
        ) ? $previousArchiveFile : $this->markdownName($record);

        $markdown = $this->writeFile($folder, $archiveFile, $this->renderMarkdown($record));
        $record['archive_file'] = $archiveFile;
        $record['archive_path'] = self::FOLDER . '/' . $archiveFile;
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
        return $record;
    }

    public function load($id, $throwIfMissing = true) {
        $id = $this->cleanId($id);
        $folder = $this->archiveFolder(false);
        if ($folder === null || !$folder->nodeExists($this->metaName($id))) {
            if ($throwIfMissing) {
                throw new \InvalidArgumentException('Chat nicht gefunden.');
            }
            return null;
        }
        $raw = $folder->get($this->metaName($id))->getContent();
        $record = json_decode((string)$raw, true);
        if (!is_array($record)) {
            throw new \RuntimeException('Gespeicherter Chat ist beschädigt.');
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
            if (!preg_match('/^\.([A-Za-z0-9_-]{8,64})\.akirag\.json$/', $name, $match)) {
                continue;
            }
            try {
                $record = json_decode((string)$node->getContent(), true);
                if (is_array($record)) {
                    $items[] = [
                        'id' => (string)($record['id'] ?? $match[1]),
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
        $record = $this->load($id);
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
        $record = $this->load($id, false);
        $names = [$this->metaName($id), $this->legacyHtmlName($id)];
        if (is_array($record) && !empty($record['archive_file'])) {
            $names[] = (string)$record['archive_file'];
        }
        foreach (array_unique($names) as $name) {
            if ($folder->nodeExists($name)) {
                $folder->get($name)->delete();
            }
        }
    }
}

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

    private function htmlName($id) {
        return $id . '.html';
    }

    private function writeFile($folder, $name, $content) {
        if ($folder->nodeExists($name)) {
            $file = $folder->get($name);
        } else {
            $file = $folder->newFile($name);
        }
        $file->putContent((string)$content);
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

    private function renderHtml($record) {
        $title = htmlspecialchars((string)$record['title'], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
        $parts = [
            '<!doctype html>', '<html><head><meta charset="utf-8">',
            '<title>' . $title . '</title></head><body>',
            '<h1>' . $title . '</h1>',
            '<p><small>AKI Recherche · ' . htmlspecialchars((string)$record['updated_at'], ENT_QUOTES, 'UTF-8') . '</small></p>'
        ];
        foreach ($record['messages'] as $message) {
            $role = ($message['role'] ?? '') === 'user' ? 'Benutzer' : 'AKI';
            $stamp = isset($message['created_at']) ? trim((string)$message['created_at']) : '';
            $heading = '<section><h2>' . $role . '</h2>';
            if ($stamp !== '') {
                $heading .= '<p><small>' . htmlspecialchars($stamp, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . '</small></p>';
            }
            $parts[] = $heading . '<pre>' .
                htmlspecialchars((string)($message['content'] ?? ''), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') .
                '</pre></section>';
        }
        $parts[] = '</body></html>';
        return implode("\n", $parts);
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
        ];
        $this->writeFile($folder, $this->metaName($id), json_encode($record, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));
        $this->writeFile($folder, $this->htmlName($id), $this->renderHtml($record));
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
        foreach ([$this->metaName($id), $this->htmlName($id)] as $name) {
            if ($folder->nodeExists($name)) {
                $folder->get($name)->delete();
            }
        }
    }
}

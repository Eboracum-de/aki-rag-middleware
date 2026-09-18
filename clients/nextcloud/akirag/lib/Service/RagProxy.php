<?php
namespace OCA\AkiRag\Service;

use OCP\Http\Client\IClientService;
use OCP\IConfig;
use OCP\IUserSession;
use OCP\Security\ICrypto;

class RagProxy {
    const MODEL_ID = 'nextcloud-hybrid-rag';
    const MAX_MESSAGES = 30;
    const MAX_MESSAGE_CHARS = 30000;

    /** @var IClientService */
    private $clientService;

    /** @var IConfig */
    private $config;

    /** @var ICrypto */
    private $crypto;

    /** @var IUserSession */
    private $userSession;

    public function __construct(
        IClientService $clientService,
        IConfig $config,
        ICrypto $crypto,
        IUserSession $userSession
    ) {
        $this->clientService = $clientService;
        $this->config = $config;
        $this->crypto = $crypto;
        $this->userSession = $userSession;
    }

    public function chat(array $messages, array $sourceScopes = []) {
        $baseUrl = rtrim($this->config->getAppValue('akirag', 'middleware_url', ''), '/');
        $encryptedKey = $this->config->getAppValue('akirag', 'api_key_encrypted', '');
        if ($baseUrl === '' || $encryptedKey === '') {
            throw new \RuntimeException('AKI Recherche ist noch nicht konfiguriert.');
        }

        try {
            $apiKey = $this->crypto->decrypt($encryptedKey);
        } catch (\Exception $e) {
            throw new \RuntimeException('Der gespeicherte Middleware-API-Key kann nicht gelesen werden.');
        }

        $user = $this->userSession->getUser();
        if ($user === null) {
            throw new \RuntimeException('Keine angemeldete Nextcloud-Sitzung gefunden.');
        }
        $uid = $user->getUID();

        $cleanMessages = $this->sanitizeMessages($messages);
        if (count($cleanMessages) === 0) {
            throw new \InvalidArgumentException('Keine Anfrage übergeben.');
        }

        $this->applySourceScopes($cleanMessages, $sourceScopes);

        $payload = [
            'model' => self::MODEL_ID,
            'messages' => $cleanMessages,
            'stream' => false,
            'user' => $uid,
        ];

        $client = $this->clientService->newClient();
        try {
            $response = $client->post($baseUrl . '/v1/chat/completions', [
                'headers' => [
                    'Accept' => 'application/json',
                    'Content-Type' => 'application/json',
                    'Authorization' => 'Bearer ' . $apiKey,
                    'X-RAG-User-ID' => $uid,
                    'X-RAG-Web-Allowed' => 'true',
                ],
                'body' => json_encode($payload),
                'timeout' => 240,
                'connect_timeout' => 15,
            ]);
        } catch (\Exception $e) {
            throw new \RuntimeException('Middleware-Anfrage fehlgeschlagen: ' . $this->safeError($e->getMessage()));
        }

        $status = (int)$response->getStatusCode();
        $decoded = json_decode((string)$response->getBody(), true);
        if ($status < 200 || $status >= 300) {
            $detail = is_array($decoded) && isset($decoded['detail']) ? (string)$decoded['detail'] : 'HTTP ' . $status;
            throw new \RuntimeException('Middleware-Fehler: ' . $detail);
        }

        if (!is_array($decoded) || !isset($decoded['choices'][0]['message']['content'])) {
            throw new \RuntimeException('Middleware hat keine lesbare Chat-Antwort geliefert.');
        }

        $rawContent = (string)$decoded['choices'][0]['message']['content'];
        $sources = $this->extractSourceMarkers($rawContent);
        $cleanContent = preg_replace('/<!--rag-source:\d+:[^>]+-->/', '', $rawContent);
        $cleanContent = trim(preg_replace('/[ \t]+\n/', "\n", (string)$cleanContent));

        return [
            'content' => $cleanContent,
            'sources' => $sources,
            'id' => isset($decoded['id']) ? (string)$decoded['id'] : '',
            'model' => isset($decoded['model']) ? (string)$decoded['model'] : self::MODEL_ID,
        ];
    }

    private function sanitizeMessages(array $messages) {
        $messages = array_slice($messages, -self::MAX_MESSAGES);
        $clean = [];

        foreach ($messages as $message) {
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
            if (strlen($content) > self::MAX_MESSAGE_CHARS) {
                throw new \InvalidArgumentException('Eine Nachricht ist zu lang.');
            }
            if ($role === 'assistant' && isset($message['sources']) && is_array($message['sources'])) {
                $markers = [];
                foreach ($message['sources'] as $source) {
                    if (!is_array($source)) {
                        continue;
                    }
                    $index = isset($source['index']) ? (int)$source['index'] : 0;
                    $reference = isset($source['reference']) ? trim((string)$source['reference']) : '';
                    if ($index > 0 && $reference !== '' && strpos($reference, '-->') === false) {
                        $markers[] = '<!--rag-source:' . $index . ':' . $reference . '-->';
                    }
                }
                if ($markers) {
                    $content .= "\n\n" . implode('', $markers);
                }
            }
            $clean[] = ['role' => $role, 'content' => $content];
        }

        if (count($clean) === 0 || $clean[count($clean) - 1]['role'] !== 'user') {
            throw new \InvalidArgumentException('Die letzte Nachricht muss eine Benutzeranfrage sein.');
        }

        return $clean;
    }

    private function applySourceScopes(array &$messages, array $sourceScopes) {
        if (!$messages) {
            return;
        }
        $last = count($messages) - 1;
        if (($messages[$last]['role'] ?? '') !== 'user') {
            return;
        }
        $content = (string)($messages[$last]['content'] ?? '');
        if (preg_match('/^\s*(?:(?:\/(?:list:raw|documents|mailarchive|webarchive|chatarchive|files|vector|graph|elastic|web|list|new|force|health|help|use:[^\s]+))\s*)+/i', $content, $prefixMatch)) {
            $prefix = $prefixMatch[0];
            if (preg_match('/\/(?:documents|mailarchive|webarchive|chatarchive|web)\b/i', $prefix)) {
                return; // explicit user source selection wins over UI state
            }
            if (preg_match('/\/(?:use:|health\b|help\b)/i', $prefix)) {
                return; // direct/special commands are not source-scoped
            }
        }

        $allowed = ['documents', 'mailarchive', 'webarchive', 'chatarchive', 'web'];
        $selected = [];
        foreach ($sourceScopes as $scope) {
            $value = strtolower(trim((string)$scope));
            if (in_array($value, $allowed, true) && !in_array($value, $selected, true)) {
                $selected[] = $value;
            }
        }
        if (!$selected) {
            return;
        }
        $directives = array_map(function ($scope) { return '/' . $scope; }, $selected);
        $messages[$last]['content'] = implode(' ', $directives) . ' ' . ltrim($content);
    }

    private function extractSourceMarkers($content) {
        $sources = [];
        if (preg_match_all('/<!--rag-source:(\d+):([^>]+)-->/', (string)$content, $matches, PREG_SET_ORDER)) {
            foreach ($matches as $match) {
                $reference = trim((string)$match[2]);
                if ($reference !== '') {
                    $sources[] = ['index' => (int)$match[1], 'reference' => $reference];
                }
            }
        }
        return $sources;
    }

    private function safeError($message) {
        $message = preg_replace('/Bearer\\s+[^\\s]+/i', 'Bearer [redacted]', (string)$message);
        if (strlen($message) > 300) {
            $message = substr($message, 0, 300) . '…';
        }
        return $message;
    }
}

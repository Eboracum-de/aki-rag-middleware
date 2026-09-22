<?php
namespace OCA\AkiRag\Controller;

use OCA\AkiRag\Service\ChatStore;
use OCA\AkiRag\Service\RagProxy;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\DataResponse;
use OCP\IRequest;

class ChatController extends Controller {
    /** @var RagProxy */
    private $proxy;
    /** @var ChatStore */
    private $store;

    public function __construct($AppName, IRequest $request, RagProxy $proxy, ChatStore $store) {
        parent::__construct($AppName, $request);
        $this->proxy = $proxy;
        $this->store = $store;
    }

    /**
     * @NoAdminRequired
     *
     * @param array $messages
     * @param array $sourceScopes
     * @param string $conversationId
     * @return DataResponse
     */
    public function send($messages = [], $sourceScopes = [], $conversationId = '') {
        if (!is_array($messages)) {
            return new DataResponse(['error' => 'Ungültiger Gesprächsverlauf.'], 400);
        }
        if (!is_array($sourceScopes)) {
            $sourceScopes = [];
        }

        try {
            $result = $this->proxy->chat($messages, $sourceScopes);
            $stored = $messages;
            $assistantCreatedAt = gmdate('c');
            $assistant = [
                'role' => 'assistant',
                'content' => isset($result['content']) ? (string)$result['content'] : '',
                'created_at' => $assistantCreatedAt,
            ];
            if (!empty($result['sources']) && is_array($result['sources'])) {
                $assistant['sources'] = $result['sources'];
            }
            if (!empty($result['source_scopes']) && is_array($result['source_scopes'])) {
                $assistant['source_scopes'] = $result['source_scopes'];
            }
            $stored[] = $assistant;
            $chat = $this->store->save($conversationId, $stored, $sourceScopes);
            $this->proxy->registerChatArchive(
                $chat['document_id'] ?? '',
                $chat['archive_path'] ?? ''
            );
            $result['message_created_at'] = $assistantCreatedAt;
            $result['conversation'] = [
                'id' => $chat['id'],
                'title' => $chat['title'],
                'updated_at' => $chat['updated_at'],
                'scopes' => $chat['scopes'],
            ];
            return new DataResponse($result);
        } catch (\InvalidArgumentException $e) {
            return new DataResponse(['error' => $e->getMessage()], 400);
        } catch (\RuntimeException $e) {
            return new DataResponse(['error' => $e->getMessage()], 502);
        } catch (\Exception $e) {
            return new DataResponse(['error' => 'Middleware nicht erreichbar.'], 502);
        }
    }

    /**
     * @NoAdminRequired
     */
    public function listChats() {
        try {
            return new DataResponse(['chats' => $this->store->listChats()]);
        } catch (\Exception $e) {
            return new DataResponse(['error' => 'Chatarchiv konnte nicht gelesen werden.'], 500);
        }
    }

    /**
     * @NoAdminRequired
     */
    public function load($id = '') {
        try {
            return new DataResponse(['chat' => $this->store->load($id)]);
        } catch (\InvalidArgumentException $e) {
            return new DataResponse(['error' => $e->getMessage()], 404);
        } catch (\Exception $e) {
            return new DataResponse(['error' => 'Chat konnte nicht gelesen werden.'], 500);
        }
    }

    /**
     * @NoAdminRequired
     */
    public function rename($id = '', $title = '') {
        try {
            $chat = $this->store->rename($id, $title);
            $this->proxy->registerChatArchive(
                $chat['document_id'] ?? '',
                $chat['archive_path'] ?? ''
            );
            return new DataResponse(['ok' => true, 'chat' => $chat]);
        } catch (\InvalidArgumentException $e) {
            return new DataResponse(['error' => $e->getMessage()], 400);
        } catch (\Exception $e) {
            return new DataResponse(['error' => 'Chat konnte nicht umbenannt werden.'], 500);
        }
    }

    /**
     * @NoAdminRequired
     */
    public function delete($id = '') {
        try {
            $this->store->delete($id);
            return new DataResponse(['ok' => true]);
        } catch (\Exception $e) {
            return new DataResponse(['error' => 'Chat konnte nicht gelöscht werden.'], 500);
        }
    }
}

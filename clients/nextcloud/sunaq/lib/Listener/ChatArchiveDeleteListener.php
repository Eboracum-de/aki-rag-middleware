<?php
namespace OCA\Sunaq\Listener;

use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Files\Events\Node\BeforeNodeDeletedEvent;
use OCP\Files\File;

class ChatArchiveDeleteListener implements IEventListener {
    public function handle(Event $event): void {
        if (!($event instanceof BeforeNodeDeletedEvent)) {
            return;
        }

        if (method_exists($event, 'getNode')) {
            $node = $event->getNode();
        } elseif (method_exists($event, 'getTarget')) {
            $node = $event->getTarget();
        } else {
            return;
        }
        if (!($node instanceof File)) {
            return;
        }

        $name = (string)$node->getName();
        if (substr($name, -3) !== '.md') {
            return;
        }

        try {
            $content = (string)$node->getContent();
        } catch (\Exception $e) {
            return;
        }

        if (!preg_match('/(?:^|\r?\n)- Chat-ID: ([A-Za-z0-9_-]{8,64})(?:\r?\n|$)/', $content, $match)) {
            return;
        }
        $id = (string)$match[1];
        $shortId = substr($id, 0, 8);
        if ($shortId === '' || !preg_match('/ - ' . preg_quote($shortId, '/') . '\\.md$/u', $name)) {
            return;
        }

        try {
            $parent = $node->getParent();
            foreach (['.' . $id . '.sunaq.json', '.' . $id . '.akirag.json'] as $sidecar) {
                if ($parent->nodeExists($sidecar)) {
                    $parent->get($sidecar)->delete();
                }
            }
        } catch (\Exception $e) {
            // Never block the user's requested file deletion.  ChatStore also
            // prunes orphan metadata on its next list/load operation.
        }
    }
}

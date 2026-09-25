<?php
namespace OCA\Sunaq\AppInfo;

use OCA\Sunaq\Listener\ChatArchiveDeleteListener;
use OCP\AppFramework\App;
use OCP\AppFramework\Bootstrap\IBootContext;
use OCP\AppFramework\Bootstrap\IBootstrap;
use OCP\AppFramework\Bootstrap\IRegistrationContext;
use OCP\Files\Events\Node\BeforeNodeDeletedEvent;

class Application extends App implements IBootstrap {
    const APP_ID = 'sunaq';

    public function __construct() {
        parent::__construct(self::APP_ID);
    }

    public function register(IRegistrationContext $context): void {
        $context->registerEventListener(
            BeforeNodeDeletedEvent::class,
            ChatArchiveDeleteListener::class
        );
    }

    public function boot(IBootContext $context): void {
    }
}

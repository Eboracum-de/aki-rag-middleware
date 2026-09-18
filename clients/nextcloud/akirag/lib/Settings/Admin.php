<?php
namespace OCA\AkiRag\Settings;

use OCP\AppFramework\Http\TemplateResponse;
use OCP\IConfig;
use OCP\Settings\ISettings;

class Admin implements ISettings {
    /** @var IConfig */
    private $config;

    public function __construct(IConfig $config) {
        $this->config = $config;
    }

    public function getForm() {
        return new TemplateResponse('akirag', 'admin', [
            'middleware_url' => $this->config->getAppValue('akirag', 'middleware_url', ''),
            'has_api_key' => $this->config->getAppValue('akirag', 'api_key_encrypted', '') !== '',
        ]);
    }

    public function getSection() {
        return 'additional';
    }

    public function getPriority() {
        return 50;
    }
}

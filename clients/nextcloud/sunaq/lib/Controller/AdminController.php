<?php
namespace OCA\Sunaq\Controller;

use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\DataResponse;
use OCP\IConfig;
use OCP\IRequest;
use OCP\Security\ICrypto;

class AdminController extends Controller {
    /** @var IConfig */
    private $config;

    /** @var ICrypto */
    private $crypto;

    public function __construct($AppName, IRequest $request, IConfig $config, ICrypto $crypto) {
        parent::__construct($AppName, $request);
        $this->config = $config;
        $this->crypto = $crypto;
    }

    /**
     * @param string $middlewareUrl
     * @param string $apiKey
     * @param bool $allowInsecureHttp
     * @return DataResponse
     */
    public function save($middlewareUrl = '', $apiKey = '', $allowInsecureHttp = false) {
        $url = rtrim(trim((string)$middlewareUrl), '/');
        if ($url === '' || filter_var($url, FILTER_VALIDATE_URL) === false) {
            return new DataResponse(['error' => 'Bitte eine gültige Middleware-URL angeben.'], 400);
        }

        $scheme = strtolower((string)parse_url($url, PHP_URL_SCHEME));
        if ($scheme !== 'http' && $scheme !== 'https') {
            return new DataResponse(['error' => 'Die Middleware-URL muss http oder https verwenden.'], 400);
        }
        $allowInsecure = filter_var($allowInsecureHttp, FILTER_VALIDATE_BOOLEAN);
        if ($scheme === 'http' && !$allowInsecure) {
            return new DataResponse([
                'error' => 'HTTP würde den Provider-API-Key unverschlüsselt übertragen. Bitte HTTPS verwenden oder unsicheres HTTP ausdrücklich freigeben.'
            ], 400);
        }

        $this->config->setAppValue('sunaq', 'middleware_url', $url);
        $this->config->setAppValue('sunaq', 'allow_insecure_http', $allowInsecure ? '1' : '0');

        $apiKey = trim((string)$apiKey);
        if ($apiKey !== '') {
            $this->config->setAppValue('sunaq', 'api_key_encrypted', $this->crypto->encrypt($apiKey));
        } elseif ($this->config->getAppValue('sunaq', 'api_key_encrypted', '') === '') {
            // 0.2.x used app id "akirag". Reuse the encrypted value during the
            // one-time app-id migration without exposing/decrypting it here.
            $legacyKey = $this->config->getAppValue('akirag', 'api_key_encrypted', '');
            if ($legacyKey !== '') {
                $this->config->setAppValue('sunaq', 'api_key_encrypted', $legacyKey);
            }
        }

        return new DataResponse([
            'ok' => true,
            'middlewareUrl' => $url,
            'hasApiKey' => (
                $this->config->getAppValue('sunaq', 'api_key_encrypted', '') !== ''
                || $this->config->getAppValue('akirag', 'api_key_encrypted', '') !== ''
            ),
            'allowInsecureHttp' => $allowInsecure,
        ]);
    }
}

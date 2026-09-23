<?php
script('sunaq', 'admin');
style('sunaq', 'admin');
?>
<div id="sunaq-admin" class="section">
    <h2>SunaQ Recherche</h2>
    <p>Verbindung zur bestehenden RAG-Middleware. Der API-Key wird mit dem Nextcloud-Server-Secret verschlüsselt gespeichert.</p>

    <p>
        <label for="sunaq-middleware-url">SunaQ-URL</label><br>
        <input id="sunaq-middleware-url" type="url" class="long" value="<?php p($_['middleware_url']); ?>" placeholder="https://sunaq.example.org">
        <br><em>Basis-URL ohne <code>/v1</code>.</em>
    </p>

    <p>
        <label for="sunaq-api-key">API-Key</label><br>
        <input id="sunaq-api-key" type="password" class="long" value="" autocomplete="new-password" placeholder="<?php p($_['has_api_key'] ? 'API-Key ist gespeichert – leer lassen zum Beibehalten' : 'Provider-Client API-Key'); ?>">
    </p>

    <p>
        <button id="sunaq-save" class="primary">Speichern</button>
        <span id="sunaq-admin-status" class="sunaq-admin-status"></span>
    </p>
</div>

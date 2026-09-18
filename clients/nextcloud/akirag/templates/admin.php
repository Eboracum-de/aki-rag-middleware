<?php
script('akirag', 'admin');
style('akirag', 'admin');
?>
<div id="akirag-admin" class="section">
    <h2>AKI Recherche</h2>
    <p>Verbindung zur bestehenden RAG-Middleware. Der API-Key wird mit dem Nextcloud-Server-Secret verschlüsselt gespeichert.</p>

    <p>
        <label for="akirag-middleware-url">Middleware-URL</label><br>
        <input id="akirag-middleware-url" type="url" class="long" value="<?php p($_['middleware_url']); ?>" placeholder="https://rag.example.org">
        <br><em>Basis-URL ohne <code>/v1</code>.</em>
    </p>

    <p>
        <label for="akirag-api-key">API-Key</label><br>
        <input id="akirag-api-key" type="password" class="long" value="" autocomplete="new-password" placeholder="<?php p($_['has_api_key'] ? 'API-Key ist gespeichert – leer lassen zum Beibehalten' : 'Provider-Client API-Key'); ?>">
    </p>

    <p>
        <button id="akirag-save" class="primary">Speichern</button>
        <span id="akirag-admin-status" class="akirag-admin-status"></span>
    </p>
</div>

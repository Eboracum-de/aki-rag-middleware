<?php
script('akirag', 'app');
style('akirag', 'style');
?>
<div id="akirag-app" class="akirag-workspace">
    <aside class="akirag-sidebar" aria-label="Rechercheverlauf">
        <div class="akirag-sidebar-head">
            <strong>Recherchen</strong>
            <button id="akirag-new" type="button" class="button">+ Neu</button>
        </div>
        <div id="akirag-chat-list" class="akirag-chat-list">
            <span class="akirag-muted">Noch keine gespeicherten Recherchen.</span>
        </div>
    </aside>

    <section class="akirag-shell">
        <header class="akirag-header">
            <div>
                <h2>AKI Recherche</h2>
                <p class="akirag-help-hint"><code>/help</code> zeigt die Hilfe und die verfügbaren Befehle an.</p>
                <p class="akirag-context-hint">Chats sind kontextsensitiv. Wenn Sie ein Thema bearbeiten wollen, das nicht in Zusammenhang mit diesem Chat steht, nutzen Sie bitte einen neuen Chat.</p>
                <p>Interaktive Recherche in den ausgewählten Quellen. Explizite Slash-Directives in der Anfrage übersteuern die Auswahl.</p>
            </div>
        </header>

        <main id="akirag-messages" class="akirag-messages" aria-live="polite">
            <div class="akirag-message akirag-assistant">
                <div class="akirag-role">AKI</div>
                <div class="akirag-content">Was möchten Sie finden?</div>
            </div>
        </main>

        <form id="akirag-form" class="akirag-composer">
            <fieldset class="akirag-scopes">
                <legend>Suche in</legend>
                <label><input type="checkbox" name="akirag-scope" value="documents" checked> Dokumente</label>
                <label><input type="checkbox" name="akirag-scope" value="mailarchive" checked> Mailarchiv</label>
                <label><input type="checkbox" name="akirag-scope" value="webarchive"> Webarchiv</label>
                <label><input type="checkbox" name="akirag-scope" value="chatarchive"> Chatarchiv</label>
                <label><input type="checkbox" name="akirag-scope" value="web"> Web</label>
            </fieldset>
            <label class="hidden-visually" for="akirag-input">Suchanfrage</label>
            <textarea id="akirag-input" rows="3" placeholder="Frage oder Suchanfrage eingeben …" required></textarea>
            <div class="akirag-actions">
                <span id="akirag-status" class="akirag-status"></span>
                <div class="akirag-action-buttons">
                    <button id="akirag-cancel-edit" type="button" class="button" hidden>Bearbeiten abbrechen</button>
                    <button id="akirag-retry" type="button" class="button" hidden>Fehlgeschlagene Anfrage wiederholen</button>
                    <button id="akirag-send" type="submit" class="primary">Suchen</button>
                </div>
            </div>
        </form>
    </section>
</div>

from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "clients" / "nextcloud" / "sunaq"


def test_sunaq_client_is_packaged_for_nextcloud_23_plus():
    root = ET.parse(APP / "appinfo" / "info.xml").getroot()
    assert root.findtext("version") == "0.3.0"
    dependency = root.find("./dependencies/nextcloud")
    assert dependency is not None
    assert dependency.attrib.get("min-version") == "23"


def test_sunaq_client_has_safe_markdown_and_branch_controls():
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")
    assert "appendMarkdown" in js
    assert "textContent" in js
    assert "innerHTML = content" not in js
    assert "Erneut senden" in js
    assert "Bearbeiten & erneut senden" in js
    assert "messages.slice(0, index)" in js


def test_sunaq_client_keeps_api_key_server_side_and_sends_scoped_user_header():
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    assert "api_key_encrypted" in proxy
    assert "X-RAG-User-ID" in proxy
    assert "X-RAG-User-Groups" in proxy
    assert "IGroupManager" in proxy
    assert "getUserGroups" in proxy
    assert "X-RAG-Web-Allowed" in proxy


def test_sunaq_client_registers_navigation_and_custom_icon():
    root = ET.parse(APP / "appinfo" / "info.xml").getroot()
    nav = root.find("./navigations/navigation")
    assert nav is not None
    assert nav.findtext("route") == "sunaq.page.index"
    assert nav.findtext("icon") == "app.svg"
    icon = (APP / "img" / "app.svg").read_text(encoding="utf-8")
    assert "<svg" in icon and "viewBox" in icon


def test_sunaq_024_persists_timestamps_and_renders_tables():
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")
    main = (APP / "templates" / "main.php").read_text(encoding="utf-8")
    store = (APP / "lib" / "Service" / "ChatStore.php").read_text(encoding="utf-8")
    assert "table" in js.lower()
    assert "timestamp" in js.lower()
    assert "/help" in main
    assert "SunaQ-Chats" in store
    assert "AKI-Chats" in store  # legacy archive root remains readable


def test_sunaq_chat_routes_use_nextcloud23_compatible_noadmin_docblocks():
    controller = (APP / "lib" / "Controller" / "ChatController.php").read_text(encoding="utf-8")

    # Nextcloud 23's ControllerMethodReflector matches annotations only on
    # dedicated docblock lines of the form " * @NoAdminRequired".
    for method in ("send", "models", "status", "listChats", "load", "rename", "delete"):
        marker = f"public function {method}"
        method_pos = controller.index(marker)
        doc_start = controller.rfind("/**", 0, method_pos)
        doc_end = controller.find("*/", doc_start, method_pos)
        assert doc_start >= 0
        assert doc_end >= 0
        docblock = controller[doc_start:doc_end + 2]
        assert "\n     * @NoAdminRequired\n" in docblock

    assert "/** @NoAdminRequired */" not in controller



def test_sunaq_025_marks_context_boundary_and_persists_effective_source_scopes():
    main = (APP / "templates" / "main.php").read_text(encoding="utf-8")
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    controller = (APP / "lib" / "Controller" / "ChatController.php").read_text(encoding="utf-8")
    store = (APP / "lib" / "Service" / "ChatStore.php").read_text(encoding="utf-8")

    assert "Chats sind kontextsensitiv" in main
    assert "nutzen Sie bitte einen neuen Chat" in main
    assert "source_scopes" in proxy
    assert "preg_match_all" in proxy
    assert "explicit user source selection wins over UI state" in proxy
    assert "direct/special commands are not source-scoped" in proxy
    assert "source_scopes" in controller
    assert "source_scopes" in store
    assert "Quellen:" in js
    assert "sunaq-message-scopes" in js


def test_sunaq_026_archive_registration_is_bounded_and_damaged_chats_remain_deletable():
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    store = (APP / "lib" / "Service" / "ChatStore.php").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")

    assert "'timeout' => 3" in proxy
    assert "'connect_timeout' => 2" in proxy
    assert "'X-RAG-User-ID' => $uid" in proxy
    assert "Damaged metadata must not block saving a new message" in store
    assert "class ChatMetadataCorruptionException extends \\RuntimeException" in store
    assert "throw new ChatMetadataCorruptionException" in store
    assert store.count("catch (ChatMetadataCorruptionException $e)") >= 2
    assert "recoverMarkdownName" in store
    assert "count($matches) > 1" in store
    assert 'strpos($content, "\\n- Chat-ID: " . $id . "\\n")' in store
    assert store.count("$this->recoverMarkdownName($folder, $id)") >= 2
    assert "$previousArchiveFile === '' && ($metadataCorrupt || is_array($existing))" in store
    assert "elseif ($metadataCorrupt || is_array($record))" in store
    assert "Storage/read failures still propagate." in store
    assert "Gespeicherter Chat ist beschädigt und kann nicht umbenannt werden." in store
    assert "$item['sources'] = $sources;" in store
    assert "### Quellen" not in store
    assert readme.startswith("# SunaQ Recherche 0.3.0")
    assert "persistent per-user chat history as Markdown plus metadata" in readme
    assert "Legacy-HTML" in readme


def test_sunaq_markdown_strong_weight_is_browser_independent():
    css = (APP / "css" / "style.css").read_text(encoding="utf-8")
    assert ".sunaq-content strong" in css
    assert "font-weight: 700" in css


def test_sunaq_client_exposes_user_allowed_sunaq_models_and_sends_selection():
    routes = (APP / "appinfo" / "routes.php").read_text(encoding="utf-8")
    controller = (APP / "lib" / "Controller" / "ChatController.php").read_text(encoding="utf-8")
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    main = (APP / "templates" / "main.php").read_text(encoding="utf-8")
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")

    assert "chat#models" in routes
    assert "'/models'" in routes
    assert "public function models()" in controller
    assert "public function send($messages = [], $sourceScopes = [], $conversationId = '', $model = '', $requestId = '')" in controller
    assert "$this->proxy->chat($messages, $sourceScopes, $model, $requestId)" in controller

    assert "$baseUrl . '/v1/models'" in proxy
    assert "'X-RAG-User-ID' => $uid" in proxy
    assert "public function chat(array $messages, array $sourceScopes = [], $modelId = '', $requestId = '')" in proxy
    assert "$payload['model'] = $modelId" in proxy

    assert 'id="sunaq-model"' in main
    assert "apiRequest('/models', 'GET')" in js
    assert "modelSelect = document.getElementById('sunaq-model')" in js
    assert "model: modelSelect ? modelSelect.value : ''" in js


def test_sunaq_client_polls_identity_scoped_pipeline_progress():
    routes = (APP / "appinfo" / "routes.php").read_text(encoding="utf-8")
    controller = (APP / "lib" / "Controller" / "ChatController.php").read_text(encoding="utf-8")
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")

    assert "chat#status" in routes
    assert "/status/{requestId}" in routes
    assert "public function status($requestId = '')" in controller
    assert "$this->proxy->status($requestId)" in controller
    assert "public function chat(array $messages, array $sourceScopes = [], $modelId = '', $requestId = '')" in proxy
    assert "$headers['X-RAG-Request-ID'] = $requestId" in proxy
    assert "$baseUrl . '/v1/status/' . rawurlencode($requestId)" in proxy
    assert "'X-RAG-User-ID' => $uid" in proxy

    assert "function newRequestId()" in js
    assert "function startProgress(requestId)" in js
    assert "function scheduleProgressPoll(requestId)" in js
    assert "activeRequestId !== requestId" in js
    assert "requestId: requestId" in js
    assert "apiRequest('/status/' + encodeURIComponent(requestId), 'GET')" in js
    assert "window.setTimeout" in js
    assert "800" in js



def test_sunaq_app_id_migration_reads_legacy_akirag_configuration():
    info = (APP / "appinfo" / "info.xml").read_text(encoding="utf-8")
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    settings = (APP / "lib" / "Settings" / "Admin.php").read_text(encoding="utf-8")
    admin = (APP / "lib" / "Controller" / "AdminController.php").read_text(encoding="utf-8")

    assert "<id>sunaq</id>" in info
    assert "<namespace>Sunaq</namespace>" in info
    assert "OCA\\Sunaq" in proxy
    assert "getAppValue('akirag'" in proxy
    assert "getAppValue('akirag'" in settings
    assert "getAppValue('akirag'" in admin


def test_sunaq_chat_store_writes_new_metadata_but_accepts_legacy_sidecars():
    store = (APP / "lib" / "Service" / "ChatStore.php").read_text(encoding="utf-8")
    assert "'.sunaq.json'" in store
    assert "'.akirag.json'" in store
    assert "LEGACY_FOLDER = 'AKI-Chats'" in store
    assert "FOLDER = 'SunaQ-Chats'" in store

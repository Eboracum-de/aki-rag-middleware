from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "clients" / "nextcloud" / "akirag"


def test_aki_client_is_packaged_for_nextcloud_23_plus():
    root = ET.parse(APP / "appinfo" / "info.xml").getroot()
    assert root.findtext("version") == "0.2.6"
    dependency = root.find("./dependencies/nextcloud")
    assert dependency is not None
    assert dependency.attrib.get("min-version") == "23"


def test_aki_client_has_safe_markdown_and_branch_controls():
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")
    assert "appendMarkdown" in js
    assert "textContent" in js
    assert "innerHTML = content" not in js
    assert "Erneut senden" in js
    assert "Bearbeiten & erneut senden" in js
    assert "messages.slice(0, index)" in js


def test_aki_client_keeps_api_key_server_side_and_sends_scoped_user_header():
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    assert "api_key_encrypted" in proxy
    assert "X-RAG-User-ID" in proxy
    assert "X-RAG-User-Groups" in proxy
    assert "IGroupManager" in proxy
    assert "getUserGroups" in proxy
    assert "X-RAG-Web-Allowed" in proxy


def test_aki_client_registers_navigation_and_custom_icon():
    root = ET.parse(APP / "appinfo" / "info.xml").getroot()
    nav = root.find("./navigations/navigation")
    assert nav is not None
    assert nav.findtext("route") == "akirag.page.index"
    assert nav.findtext("icon") == "app.svg"
    icon = (APP / "img" / "app.svg").read_text(encoding="utf-8")
    assert "<svg" in icon and "viewBox" in icon


def test_aki_024_persists_timestamps_and_renders_tables():
    js = (APP / "js" / "app.js").read_text(encoding="utf-8")
    main = (APP / "templates" / "main.php").read_text(encoding="utf-8")
    store = (APP / "lib" / "Service" / "ChatStore.php").read_text(encoding="utf-8")
    assert "table" in js.lower()
    assert "timestamp" in js.lower()
    assert "/help" in main
    assert "AKI-Chats" in store


def test_aki_chat_routes_use_nextcloud23_compatible_noadmin_docblocks():
    controller = (APP / "lib" / "Controller" / "ChatController.php").read_text(encoding="utf-8")

    # Nextcloud 23's ControllerMethodReflector matches annotations only on
    # dedicated docblock lines of the form " * @NoAdminRequired".
    for method in ("send", "listChats", "load", "rename", "delete"):
        marker = f"public function {method}"
        method_pos = controller.index(marker)
        doc_start = controller.rfind("/**", 0, method_pos)
        doc_end = controller.find("*/", doc_start, method_pos)
        assert doc_start >= 0
        assert doc_end >= 0
        docblock = controller[doc_start:doc_end + 2]
        assert "\n     * @NoAdminRequired\n" in docblock

    assert "/** @NoAdminRequired */" not in controller



def test_aki_025_marks_context_boundary_and_persists_effective_source_scopes():
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
    assert "akirag-message-scopes" in js


def test_aki_026_archive_registration_is_bounded_and_damaged_chats_remain_deletable():
    proxy = (APP / "lib" / "Service" / "RagProxy.php").read_text(encoding="utf-8")
    store = (APP / "lib" / "Service" / "ChatStore.php").read_text(encoding="utf-8")
    readme = (APP / "README.md").read_text(encoding="utf-8")

    assert "'timeout' => 3" in proxy
    assert "'connect_timeout' => 2" in proxy
    assert "catch (\\Exception $e)" in store
    assert "Damaged metadata must not prevent deletion" in store
    assert readme.startswith("# AKI Recherche 0.2.6")
    assert "Markdown plus Metadaten" in readme
    assert "Legacy-HTML" in readme


def test_aki_markdown_strong_weight_is_browser_independent():
    css = (APP / "css" / "style.css").read_text(encoding="utf-8")
    assert ".akirag-content strong" in css
    assert "font-weight: 700" in css

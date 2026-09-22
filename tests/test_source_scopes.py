import sqlite3

from rag.openai_provider import _parse_retrieval_directives


def test_source_directives_are_orthogonal_to_retrieval_arms():
    parsed = _parse_retrieval_directives('/documents /mailarchive /vector Rechnung 2025')
    assert parsed.error is None
    assert parsed.source_scopes == {'documents', 'mailarchive'}
    assert parsed.retrieval_arms == {'vector'}
    assert parsed.web_requested is False
    assert parsed.query == 'Rechnung 2025'


def test_web_alone_is_web_only_but_documents_plus_web_is_mixed():
    web = _parse_retrieval_directives('/web aktueller Stand')
    assert web.web_requested is True
    assert web.web_only is True
    mixed = _parse_retrieval_directives('/documents /web aktueller Stand')
    assert mixed.web_requested is True
    assert mixed.web_only is False
    assert mixed.source_scopes == {'documents'}


def test_explicit_archives_parse_without_changing_engine():
    parsed = _parse_retrieval_directives('/webarchive /chatarchive Vorgang')
    assert parsed.error is None
    assert parsed.source_scopes == {'webarchive', 'chatarchive'}
    assert parsed.retrieval_arms is None


def test_source_origin_classifies_mail_and_chat_scopes(tmp_path, monkeypatch):
    import rag.source_origin as source_origin

    db = tmp_path / 'users.sqlite'
    con = sqlite3.connect(db)
    con.execute('CREATE TABLE mail_accounts(target_path TEXT, eml_target_path TEXT)')
    con.execute("INSERT INTO mail_accounts VALUES('Archive/Mail','Archive/EML')")
    con.commit()
    con.close()

    monkeypatch.setattr(source_origin, '_credential_store_path', lambda: db)
    source_origin._mail_archive_roots_for_stamp.cache_clear()
    assert source_origin.classify_source_origin('Archive/Mail/Inbox/x.html') == 'mail_archive'
    assert source_origin.classify_source_origin('AKI-Chats/abc.html') == 'chat_archive'
    assert source_origin.source_scope_allows_path('Ordner/Datei.pdf', {'documents'})
    assert not source_origin.source_scope_allows_path('Archive/Mail/Inbox/x.html', {'documents'})
    assert source_origin.source_scope_allows_path('Archive/Mail/Inbox/x.html', {'mailarchive'})
    assert source_origin.source_scope_allows_path('AKI-Chats/abc.html', {'chatarchive'})
    assert not source_origin.source_scope_allows_path('AKI-Chats/abc.html', None)


def test_aki_client_has_scope_ui_and_server_side_chat_archive():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / 'clients' / 'nextcloud' / 'akirag'
    main = (root / 'templates' / 'main.php').read_text(encoding='utf-8')
    proxy = (root / 'lib' / 'Service' / 'RagProxy.php').read_text(encoding='utf-8')
    store = (root / 'lib' / 'Service' / 'ChatStore.php').read_text(encoding='utf-8')
    controller = (root / 'lib' / 'Controller' / 'ChatController.php').read_text(encoding='utf-8')
    for scope in ['documents', 'mailarchive', 'webarchive', 'chatarchive', 'web']:
        assert f'value="{scope}"' in main
    assert 'explicit user source selection wins over UI state' in proxy
    assert "const FOLDER = 'AKI-Chats'" in store
    assert '.akirag.json' in store
    assert "'source_origin' => 'chat_archive'" in store
    assert "'format' => 'markdown'" in store
    assert "'.md'" in store
    assert "renderMarkdown" in store
    assert "renderHtml" not in store
    assert "/v1/archive/chat/register" in proxy
    assert "registerChatArchive" in controller


def test_chat_archive_registration_writes_registry_before_es_mirror(monkeypatch):
    from types import SimpleNamespace

    import rag.api as api
    from rag.acl import AclDecision

    class FakeAcl:
        enabled = True

        def authorize(self, results, *, rag_user_id=None):
            assert rag_user_id == 'alice'
            return AclDecision(True, list(results), len(results), len(results))

    calls = []
    monkeypatch.setattr(api, 'live_acl', FakeAcl())
    monkeypatch.setattr(api, 'chat_archive_roots', lambda: ('AKI-Chats',))
    monkeypatch.setattr(
        api,
        'register_document',
        lambda document_id, source_origin, **kwargs: calls.append(
            (document_id, source_origin, kwargs)
        ) or True,
    )
    monkeypatch.setattr(
        api,
        'auto_mirror_registry_to_elasticsearch',
        lambda **kwargs: {'checked': 1, 'updated': 0, 'missing': 1},
    )

    result = api.register_chat_archive_source(
        api.ChatArchiveRegisterRequest(
            document_id='files:74710',
            path='AKI-Chats/2026-09-22 - Vogelsang 280 - abcdef12.md',
        ),
        SimpleNamespace(headers={'x-rag-user-id': 'alice'}),
    )

    assert result['ok'] is True
    assert result['source_origin'] == 'chat_archive'
    assert calls == [(
        'files:74710',
        'chat_archive',
        {
            'source_path': 'AKI-Chats/2026-09-22 - Vogelsang 280 - abcdef12.md',
            'classification_source': 'chat_archive_write',
        },
    )]

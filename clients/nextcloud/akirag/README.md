# AKI Recherche 0.2.5

Schlankes Nextcloud-23+-Frontend für RAG Middleware 0.8.5.

- Server-seitiger Proxy mit Nextcloud-UID (`X-RAG-User-ID`)
- Middleware-URL und Provider-Key nur im Nextcloud-Adminbereich
- sicheres, frameworkfreies Markdown-Subset (kein Raw-HTML)
- pro Benutzerfrage: **Erneut senden** und **Bearbeiten & erneut senden**
- sichtbarer Hinweis in jedem Chat, für thematisch unabhängige Fragen einen neuen Chat zu verwenden
- pro AKI-Antwort persistierte und neben dem Zeitstempel angezeigte effektive Source Scopes (UI-Auswahl oder explizite Source-Directives)
- persistente per-user Chat-Historie als strukturierte HTML/Metadaten unter `AKI-Chats/`; `/chatarchive` bleibt ein eigener Source Scope

Beim Bearbeiten wird der Verlauf ab der ausgewählten Benutzerfrage verzweigt. Die
alte Frage und ihre späteren Antworten werden nicht zusammen mit der geänderten
Frage an die Middleware geschickt.

- 0.2.1: korrekte Nextcloud-Navigationsregistrierung und eigenes AKI-SVG-Icon.
- 0.2.3: sichere Markdown-Tabellen, Zeitstempel, persistente Saved-Chats/Sidebar, `/help`-Hinweis und Eingabe direkt unter dem Verlauf.
- 0.2.4: Nextcloud-23-kompatible `@NoAdminRequired`-Docblocks für Chat-Historie, Laden, Umbenennen und Löschen; normale Benutzer erhalten keinen irrtümlichen 403 mehr.
- 0.2.5: Kontext-Hinweis im Chat-Header sowie pro Antwort persistierte/angezeigte effektive Quellenbereiche; explizite Source-Directives werden gegenüber der Checkbox-Auswahl korrekt ausgewiesen.

## Installation

Copy the `akirag` app directory into the Nextcloud `apps/` tree and enable it:

```bash
sudo -u <web-user> php occ app:enable akirag
```

Configure **Middleware URL** and **Provider API key** under **Settings →
Administration → Additional settings**. The app registers a normal Nextcloud
navigation entry and ships its own `img/app.svg`.

For an intentionally internal middleware URL, Nextcloud may require
`allow_local_remote_servers => true`. The Nextcloud host must trust the TLS CA used
by the middleware endpoint. Users still complete the middleware's one-time Nextcloud
Login Flow; the resulting app credential is also reusable for live ACL and optional
Kontakt-DB synchronization.

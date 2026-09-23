# SunaQ Recherche 0.3.0

Schlankes Nextcloud-23+-Frontend für SunaQ / Eboracum Research Gateway 0.8.6.

## Current behaviour

- server-side proxy with the current Nextcloud UID (`X-RAG-User-ID`); the provider key never reaches browser JavaScript;
- authenticated model discovery through `/v1/models`; the selector exposes only profiles allowed for the current user;
- compact chat composer with model selection, source chips and Enter-to-send;
- collapsible per-user research sidebar;
- safe framework-free Markdown subset (no raw HTML);
- request progress polling through the identity-scoped SunaQ status endpoint;
- verifier progress can report the current document batch, for example
  `Prüfe Dokumente 11–15 von 48 …`;
- per user question: **Erneut senden** and **Bearbeiten & erneut senden**;
- provider follow-up actions are rendered as compact buttons below the current
  answer, for example **Mit Tief erneut suchen** or **Anfrage präzisieren**;
- a stronger-model suggestion is shown only when a strictly stronger profile is
  currently allowed for that user;
- visible context-boundary hint: unrelated topics should use a new chat;
- effective source scopes are shown next to each SunaQ answer;
- persistent per-user chat history as Markdown plus metadata below
  `SunaQ-Chats/`; legacy `AKI-Chats` / `.akirag.json` archives remain readable.
- Legacy-HTML chat archives remain readable; when such a conversation is saved or renamed again, the current Markdown representation is written and the superseded managed HTML archive is removed.

The model list is loaded when the app starts. If an administrator changes a
user's model entitlement while an existing browser tab remains open, reload the
app to refresh the selector.

Follow-up suggestions are deliberately transient UI actions. They are returned
with the live provider response but are not persisted in the archived chat,
because a later session may have different model entitlements or retrieval
state.

## Source selection

The provider's client-neutral implicit default is **Documents only**.

The SunaQ app intentionally starts with **Documents** and **Mail** selected and
therefore sends both scopes explicitly unless the user changes the chips. Other
OpenAI-compatible clients that send no source directive use the provider default
and search ordinary documents only.

Explicit directives in the user request override the UI selection:

- `/documents`
- `/mailarchive`
- `/webarchive`
- `/chatarchive`
- `/web`

## Chat branching

When a user edits an earlier question, the conversation is branched at that
question. The old question and its later answers are not sent together with the
edited question.

## Installation

Copy the `sunaq` app directory into the Nextcloud `apps/` tree and enable it:

```bash
sudo -u <web-user> php occ app:enable sunaq
```

Configure **SunaQ URL** and **Provider API key** under **Settings →
Administration → Additional settings**. The app registers a normal Nextcloud
navigation entry and ships its own `img/app.svg`.

For an intentionally internal SunaQ URL, Nextcloud may require
`allow_local_remote_servers => true`. The Nextcloud host must trust the TLS CA
used by the middleware endpoint. Users still complete the middleware's one-time
Nextcloud Login Flow; the resulting app credential is reusable for live ACL and
optional Kontakt-DB synchronization.

## Compatibility history

- 0.2.1: Nextcloud navigation registration and app icon.
- 0.2.3: safe Markdown tables, timestamps, persistent saved-chat sidebar and
  `/help` hint.
- 0.2.4: Nextcloud-23-compatible non-admin chat-history endpoints.
- 0.2.5: context-boundary hint and persisted/effective source scopes.
- 0.2.6: readable Markdown chat archives with stable provenance.
- 0.3.0: SunaQ app id/name, model selector, request progress, source chips and
  provider follow-up actions.

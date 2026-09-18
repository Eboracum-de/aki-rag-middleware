# AKI RAG Middleware
## Technische Dokumentation und Befehlsreferenz

**Version:** `0.8.5-rc3`
**Stand:** 16. September 2026

Diese Datei ist die konsolidierte technische Referenz für den aktuellen Snapshot. Nicht veröffentlichte interne Entwicklungs- und Migrationsentwürfe sind nicht Bestandteil des öffentlichen Baseline-Repositories; bei Widersprüchen zum aktuellen Code gilt diese Referenz zusammen mit `config.yaml`, `web.yaml`, `provider.env.example` und `versions.lock.yaml`.

---

# 1. Verzeichnis- und Prozessmodell

Standardinstallation:

```text
/opt/nextcloud-rag/
```

Wichtige Prozesse:

| Prozess | Standardport | Aufgabe |
|---|---:|---|
| `rag-api` | 8765 | Retrieval, ACL, Web, Graph API, Admin UI |
| `rag-provider` | 8766 | OpenAI-kompatible Chat-Schnittstelle / Orchestrator |
| `graph-worker` | – | asynchrone GraphQueue-Verarbeitung |
| `mail-worker` | – | periodische rekursive Mail-Synchronisation |
| `sync-worker` | – | periodischer Elasticsearch→Qdrant-Abgleich |
| OpenWebUI | 3000 loopback | optionales Frontend |
| Qdrant | 6333 loopback | optional lokaler Vektorstore |
| Neo4j | 7687/7474 | optional lokaler Graph/Browser gemäß Compose |

Reverse-Proxy-Pfade:

```text
/             Benutzer-UI; OpenWebUI falls installiert
/rag-admin/   geschützte RAG-Administration
/rag-api/     Middleware/Diagnostik
/auth/        Nextcloud Login Flow
/v1/          OpenAI-kompatibler Provider
```

Ohne Benutzer-UI leitet `/` auf `/rag-admin/` um.

---

# 2. Installation

## 2.1 Plan anzeigen

```bash
sudo ./install/install.sh --plan --full
```

## 2.2 Installer-Optionen

| Option | Bedeutung |
|---|---|
| `--prefix PATH` | Installationsverzeichnis, Default `/opt/nextcloud-rag` |
| `--user USER` | Service-User, Default `rag` |
| `--skip-system-packages` | OS-Pakete/Docker nicht installieren |
| `--with-qdrant` | lokalen Qdrant installieren/starten |
| `--with-neo4j` | lokalen Neo4j installieren/starten |
| `--core` | Qdrant + Neo4j |
| `--with-openwebui` | gepinntes OpenWebUI installieren/starten |
| `--full` | Qdrant + Neo4j + OpenWebUI |
| `--no-proxy` | gebündelten nginx nicht starten |
| `--no-proxy-basic-auth` | nginx-Basic-Auth-Gate abschalten; Rate-Limits bleiben |
| `--multi-user` | explizit Multiuser/credential_store; Default |
| `--single-user` | expliziter Einbenutzermodus, Live-ACL bleibt an |
| `--acl-off` | Diagnosemodus ohne Live-ACL; nicht für gemeinsame Bestände |
| `--with-systemd` | optionale systemd-Units installieren/aktivieren |
| `--no-systemd` | Legacy-Alias: keine systemd-Integration |
| `--no-reranker-download` | lokalen HF-Reranker nicht vorladen |
| `--plan` | nur Plan anzeigen |
| `-y`, `--yes` | nicht-interaktiv bestätigen |

Nicht mehr gebündelt:

- Ollama: `--with-ollama` wird mit Fehler abgewiesen,
- SearXNG: `--with-searxng` wird mit Fehler abgewiesen.

Beide können extern betrieben und konfiguriert werden.

## 2.3 Empfohlene Referenzinstallation

```bash
sudo ./install/install.sh --plan --with-openwebui --with-qdrant --with-neo4j
sudo ./install/install.sh       --with-openwebui --with-qdrant --with-neo4j
```

Danach **vor dem ersten Start** mindestens `config.yaml`, `provider.env` und `runtime.env` prüfen.

---

# 3. Konfigurationsdateien

## 3.1 `config.yaml`

### Elasticsearch

```yaml
elasticsearch:
  enabled: true
  url: "https://es.example:9200"
  index: "nextcloud-index"
  username: "rag-readonly"
  password_env: "ELASTICSEARCH_PASSWORD"
  verify_tls: true
  ca_file: "/etc/nextcloud-rag/es-ca.pem"
  page_size: 50
```

Das Passwort gehört ausschließlich in `runtime.env` oder einen vergleichbar geschützten Environment-Store.

### Embeddings

Referenz lokal:

```yaml
embedding:
  backend: ollama
  url: "http://127.0.0.1:11434"
  model: "qwen3-embedding:4b"
  profile: custom
  document_prefix: ""
  query_prefix: "Instruct: Given a user query, retrieve relevant passages from a private document archive that answer or relate to the query\nQuery: "
  dimensions: 1024
  api_key_env: "EMBEDDING_API_KEY"
  verify_tls: true
  timeout: 300
```

Die Embedding-Schicht ist modellagnostisch: `query_prefix` und `document_prefix` werden explizit konfiguriert und niemals aus dem Modellnamen abgeleitet. Das Referenzbeispiel verwendet für Qwen3 eine Query-only Retrieval-Instruktion; für andere Modelle können passende Prefixes gesetzt oder beide leer gelassen werden. `dimensions` ist optional und backend-/modellabhängig; im Referenzbetrieb hält `dimensions: 1024` die Qdrant-Collection trotz des 4B-Modells bei 1024 Dimensionen. Ein Modellwechsel erfordert einen separaten/neuen Vektorbestand, weil verschiedene Embedding-Räume nicht gemischt werden dürfen.

Der Sync ergänzt standardmäßig nur für den Embedding-Input den Dateibasename (`sync.embedding_include_basename: true`). Der in Qdrant gespeicherte Evidence-Chunk bleibt unverändert. Für einen einmaligen GPU-Erstsync kann `rag.sync --embedding-url http://GPU-HOST:11434` verwendet werden, ohne die dauerhafte CPU-Konfiguration zu ändern.

Ein externer OpenAI-kompatibler Embedding-Endpunkt ist möglich. Achtung: Bei externer Vektorisierung wird der zu indexierende Volltext chunkweise an diesen Provider übertragen.

### Qdrant

```yaml
qdrant:
  enabled: true
  url: "http://127.0.0.1:6333"
  collection: "nextcloud_rag"
```

### Retrieval, Query Rewrite und optionale Runden

Der normale Retrievalvertrag ist bewusst klein. Runde 1 schreibt die
Benutzerfrage genau einmal in einen SearchSpec um:

```json
{
  "elastic_query": "+examplehost +2025 +Rechnung",
  "semantic_query": "Rechnungen von examplehost aus dem Jahr 2025",
  "entities": ["examplehost"],
  "concepts": ["Rechnung"],
  "constraints": [{"kind": "Jahr", "value": "2025"}],
  "verification_requirements": [
    "Das Dokument ist selbst eine Rechnung von examplehost.",
    "Das relevante Jahr ist 2025."
  ]
}
```

Vor dem Rewrite wird ein kompakter Neo4j-Seed-/Alias-Kontext bereitgestellt.
`elastic_query` ist eine menschenlesbare Nextcloud-Volltextanfrage, keine rohe
Elasticsearch-DSL. Die API parst sie und erzeugt daraus deterministisch die
Elasticsearch-JSON-Abfrage; `semantic_query` geht ausschließlich an Qdrant, sofern
aktiviert. `entities`, `concepts`, `constraints` und
`verification_requirements` beeinflussen Graph-Light/Verifier/Provenienz, aber
schreiben die `elastic_query` nicht heimlich um.

Die Backend-Ergebnisse werden wie bisher fusioniert, dedupliziert und optional
gerankt. Danach folgen Live-Nextcloud-ACL und Candidate Verifier. Der SearchSpec-
Pfad loggt die vom LLM erzeugte `elastic_query`, den tatsächlich an Elasticsearch
gesendeten JSON-Querybody und eine kompakte Trefferliste ohne Dokumentinhalt.

Aktuelle Referenzwerte:

```yaml
search:
  es_limit: 50
  vector_limit: 80
  vector_threshold: 0.55
  rrf_k: 60
  rerank_candidates: 10
  final_limit: 15

# Legacy-Abschnittsname aus Konfigurationskompatibilität.
# Runde 1 führt immer Query Rewrite + Retrieval aus.
retrieval_planner:
  enabled: true              # nur zusätzliche Runden
  max_retrieval_rounds: 1    # 1 = keine automatische zweite Runde
  model: ""                 # leer = allgemeines LLM_MODEL
  max_tokens: 700
  context_max_chars: 12000
  max_complete_documents: 15
  overflow_acl_scan_limit: 80
  verification_candidate_limit: 6
  bounded_verification_candidate_limit: 30
  exhaustive_verification_candidate_limit: 30
  verification_max_chars_per_document: 2500
  verification_max_tokens: 900
  verification_batch_size: 6
```

Sind weitere Runden aktiviert, darf der Rewriter anhand des bisherigen sichtbaren
Trefferbilds einen **neuen SearchSpec** erzeugen. Jede Runde durchläuft dieselbe
Pipeline; es gibt im normalen Pfad keine `lexical`/`strict_lexical`/`semantic`
Probe-Sprache mehr. Die alten Multi-Probe-Funktionen und `/multi-search` bleiben
vorerst als Kompatibilitäts-/Diagnoseoberfläche im Code, werden vom normalen
Providerpfad jedoch nicht verwendet.

### Qdrant-Sync

```yaml
sync:
  chunk_size: 3000
  chunk_overlap: 400
  embedding_batch_size: 8
  max_documents: 0
  state_db: "state.sqlite"
```

Die semantische Corpus-Filterung arbeitet auf bereits von Nextcloud/Elasticsearch extrahiertem Text; die Middleware dekodiert keine Binärdateien selbst.

### Live ACL

```yaml
acl:
  enabled: true
  identity_mode: credential_store
  credential_store: "runtime/users.sqlite"
  verify_tls: true
  timeout: 15
  batch_size: 100
```

`credential_store` ist der sichere Multiuser-Default. `acl-off` ist Diagnosemodus.

### Neo4j / Graph

```yaml
neo4j:
  enabled: true
  uri: "bolt://127.0.0.1:7687"
  username: "neo4j"
  password_env: "NEO4J_PASSWORD"
  database: "neo4j"
```

GraphQueue, Entity Discovery und Relation Discovery besitzen separate Budgets/Schwellwerte in `config.yaml`.

### Reranker

Lokal:

```yaml
reranker:
  backend: local
  model: "BAAI/bge-reranker-v2-m3"
  device: cpu
  max_length: 512
  batch_size: 4
```

External TEI:

```yaml
reranker:
  backend: tei
  tei_url: "http://127.0.0.1:8081"
  timeout_seconds: 30
  tei_batch_size: 32
  fallback_backend: none
```

Super-Light disables the reranker intentionally:

```yaml
reranker:
  backend: none
  fallback_backend: none
```

This does **not** disable candidate deduplication. `dedup.enabled:true` remains an
independent preprocessing step before the optional reranker/RRF fallback and prevents
PDF/ODT/copy variants or near-identical text from consuming several candidate slots.
The Super-Light normal verifier window is 10 authorized candidates; the standard
reference profile remains at 6.

### RetrievalRecord

Nicht standardmäßig eingeschaltet. Optional ergänzen:

```yaml
retrieval_record:
  enabled: true
  directory: "runtime/retrieval-records"
```

Die Records enthalten strukturierte Retrieval-/Evidence-Metadaten, nicht den vollständigen Dokumentkörper.

### Periodischer ES→Qdrant-Sync

```yaml
sync_worker:
  enabled: true
  poll_interval_seconds: 300
  max_documents: 0
  enqueue_graph: false
```

Der Worker ruft periodisch **denselben** inkrementellen `rag.sync` auf wie die CLI. `max_documents: 0` ist für den Dauerbetrieb wichtig: ein festes Limit könnte Dokumente weiter hinten im Elasticsearch-Index dauerhaft vom Abgleich ausschließen. Vollständiges Graph-Enqueue bleibt separat opt-in.

### Mail

```yaml
mail:
  enabled: false
  state_file: mail_state.sqlite
  poll_interval_seconds: 300
```

Konten, Server, Mailbox-Wurzeln, Zielpfade und Credentials sind benutzerbezogen in `runtime/users.sqlite` und werden über Admin UI/CLI verwaltet. Jede konfigurierte Mailbox ist eine **rekursive Wurzel**: der Worker ermittelt mit IMAP `LIST` alle selektierbaren Unterordner.

---

## 3.2 `provider.env` / `runtime.env`

Getesteter OpenAI-Referenzpfad:

```bash
LLM_BACKEND=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-5.6-luna
FOLLOWUP_MODEL=gpt-5.6-luna
EVIDENCE_MODEL=gpt-5.6-luna
ANSWER_MODEL=gpt-5.6-luna
ANSWER_THINKING=false
```

Secret ausschließlich in `runtime.env`:

```bash
LLM_API_KEY='...'
ELASTICSEARCH_PASSWORD='...'
NEO4J_PASSWORD='...'
WEB_SEARCH_API_KEY='...'
# optional eigener Schlüssel nur für den Web-Relevance-LLM:
WEB_LLM_API_KEY='...'
```

Ist `WEB_LLM_API_KEY` leer, kann der Web-Relevance-Pfad auf den normalen `LLM_API_KEY` zurückfallen.

Die benutzergebundenen Nextcloud-/IMAP-Secrets liegen **nicht** in `runtime.env`. Für deren verschlüsselten Store gelten zusätzlich:

```bash
RAG_CREDENTIAL_MASTER_KEY_FILE=/opt/nextcloud-rag/runtime/credential-master.key
RAG_CREDENTIAL_ENCRYPTION=required
```

Der Master-Key selbst steht niemals in `runtime.env`; dort steht nur sein Pfad. `runtime.env` enthält in Stufe 1 weiterhin globale Provider-/Infrastruktur-Secrets und bleibt deshalb `0600`-geschützt.

Für native `api.openai.com` + GPT-5.6 setzt die Provider-Implementierung kompatible Parameter (`reasoning_effort`, `max_completion_tokens`) und entfernt nicht unterstützte Sampling-Parameter.

---

## 3.3 `web.yaml`

Aktueller Aufbau:

```yaml
enabled: true

search:
  provider: brave
  url: ""
  api_key_env: "WEB_SEARCH_API_KEY"
  max_results: 10
  timeout: 20
  verify_tls: true

fetch:
  timeout: 25
  verify_tls: true
  concurrency: 4
  max_redirects: 5
  max_bytes: 15000000
  max_text_chars: 300000
  allow_private: false

relevance:
  api_key_env: "WEB_LLM_API_KEY"
  verify_tls: true
  timeout: 180
  num_ctx: 16384
  num_predict: 800
  preview_chars: 4200
  min_score: 0.58
  max_sources: 5

archive:
  enabled: true
  exclude_from_internal_retrieval: true
  write_research_markdown: true
  write_text_snapshot: true
  write_raw_pdf: true
  write_raw_html: false
  write_fetch_log: true
  write_metadata_json: true
  write_rendered_pdf: true
  renderer:
    enabled: false
    url: "http://127.0.0.1:8090/render"
    timeout: 45
    verify_tls: true
    max_bytes: 52428800
    landscape: true
    prefer_css_page_size: false
    viewport:
      width: 1440
      height: 900
    persist_state: true
    cleanup:
      cookie_consent: off
      dismiss_overlays: false
      remove_overlays: false
```

### Brave

`provider: brave` und leerer `url` verwendet automatisch den Brave-Web-Search-Endpunkt. Schlüssel: `WEB_SEARCH_API_KEY`.

### SearXNG

Beispiel:

```yaml
search:
  provider: searxng
  url: "http://127.0.0.1:8080"
  api_key_env: ""
```

SearXNG muss JSON-Ausgabe unterstützen. Der restliche Fetch-/Relevance-/Archive-Pfad bleibt identisch.

`fetch.allow_private:false` sollte für öffentliche Web-Recherche beibehalten werden; die Regel gilt für Zielseiten, nicht für den lokal betriebenen Search-Provider.

---

# 4. Start, Stop und Status

```bash
cd /opt/nextcloud-rag
./start-all.sh
./status.sh
./stop-all.sh
```

`start-all.sh` startet:

- API,
- Provider,
- Graph Worker nur wenn Neo4j + GraphQueue aktiviert sind,
- ES→Qdrant Sync Worker nur wenn `sync_worker.enabled=true` und Qdrant aktiviert ist,
- Mail Worker nur wenn `mail.enabled=true`.

Einzelstarts:

```bash
./start-api.sh
./start-openwebui-provider.sh
./start-graph-worker.sh
./start-sync-worker.sh
./start-mail-worker.sh
```

Logs liegen bei Startskriptbetrieb unter:

```text
log/api.log
log/provider.log
log/graph-worker.log
log/sync-worker.log
log/mail-worker.log
```

---

# 5. Benutzerbefehle im Chat

Alle Slash-Directives müssen am **Anfang** der Anfrage stehen. Für normale Benutzer zeigt `/help` bewusst nur die alltagsrelevanten Befehle. `Help`, `Hilfe` und einige geläufige Entsprechungen in anderen Sprachen werden ebenfalls als Hilfeanfrage erkannt.

## 5.1 Kurzreferenz

| Befehl | Wirkung |
|---|---|
| `/new` | neuen Gesprächskontext für RAG-Auflösung beginnen |
| `/web` | ausschließlich öffentliche Web-Recherche |
| `/list` | gererankte Trefferliste mit relevanter Passage |
| `/force` | Unspezifischkeits-Frühabbruch umgehen |
| `/use:...` | Quellen der unmittelbar vorherigen Antwort oder ein eindeutig benanntes Dokument direkt verwenden |
| `/help` | eingebaute Kurzreferenz |

## 5.2 Beispiele

Normale Hybridsuche:

```text
Welche Verbindung besteht zwischen Max Mustermann und Musterhof 280?
```

Trefferliste:

```text
/list Rechnungen der Beispiel GmbH
```

Web-Recherche:

```text
/web Aktueller Stand zur Beispiel GmbH
```

Vorherige interne Quellen weiterverwenden:

```text
/use:1,2 Vergleiche diese beiden Dokumente.
```

Archivierte Webquellen weiterverwenden:

```text
/use:W1,W2 Vergleiche diese beiden Quellen.
```

Direkte Datei:

```text
/use:"RG-EX-2025-001.odt" Fasse die Rechnung zusammen.
```

## 5.3 Kombinationsregeln

- `/use` darf im Slash-Modus nur mit `/new` kombiniert werden.
- `/web` ist im Slash-Modus ein eigener öffentlicher Evidence-Arm.
- `/force` und `/list` können kombiniert werden, soweit semantisch sinnvoll.
- Interne Diagnose-/Expertendirectives bleiben technisch verfügbar, werden aber nicht in der normalen Benutzerhilfe beworben.
- Der Systemstatus wird nicht über den Chat offengelegt; Administratoren verwenden Admin-UI, `status.sh` oder die geschützten Health-Endpunkte.

---

# 6. Natürliche Steueranweisungen im führenden Klammerblock

Komplexere Workflows können in **genau einem führenden Klammerblock** beschrieben werden. Der restliche Text bleibt die eigentliche Aufgabe.

Beispiel:

```text
(Nutze Dokument 2 und suche anschließend im Web)
Gleiche die darin enthaltenen Angaben mit öffentlichen Quellen ab.
```

Der Instruction-Compiler darf nur einen geschlossenen Satz interner Aktionen wählen:

- vorherige Quellen verwenden,
- neue interne Suche `auto`, `files/vector/graph` oder `elastic`,
- Web an/aus,
- Web parallel oder anschließend,
- gerankte/rohe Liste,
- `/force`-Äquivalent,
- Kontextreset.

Beispiele:

```text
(Suche intern und anschließend im Web)
Vergleiche die internen Angaben zu Firma X mit dem aktuellen öffentlichen Stand.
```

```text
(Nutze diese Dokumente und suche anschließend im Web)
Prüfe die darin genannten Personen und Firmen anhand öffentlicher Quellen.
```

```text
(Suche nur in Dokumenten und Vektor)
Wo geht es um eine unberechtigte Geschäftsadresse?
```

```text
(Suche nur im Web)
Michaela Merz
```

### Einschränkung

Direkte Dokumentauswahl **plus gleichzeitig eine neue interne Suche** ist in diesem Stand noch nicht vorgesehen. Direkte Dokumentauswahl + Web ist dagegen ausdrücklich unterstützt.

Ein führendes `/` aktiviert immer den Slash-Directive-Modus; ein späterer Klammerausdruck ist normaler Benutzertext.

---

# 7. Web-Workflows

## 7.1 Explizit Web-only

```text
/web <Suchauftrag>
```

Ablauf:

1. Brave/SearXNG sucht.
2. Zielseiten werden tatsächlich geladen.
3. Reranker/Passage-Selektion bestimmt eine aussagekräftige Passage pro Seite.
4. Relevance-LLM bewertet jede geladene Quelle.
5. Nur Quellen oberhalb `min_score` und mit `relevant=true` werden Evidence.
6. Antwort zitiert `[W1]`, `[W2]`, ...
7. Optionales Archiv wird geschrieben.

Search-Snippets werden niemals als Evidence verwendet.

## 7.2 Interne Informationen mit Web vergleichen

Empfohlen:

```text
(Suche intern und anschließend im Web)
Suche nach XY und vergleiche die internen Informationen mit öffentlichen Quellen.
```

Bei `web_timing=after` darf der Provider aus der bereits ausgewählten internen Evidence bis zu drei konkrete Webqueries ableiten.

## 7.3 Bestimmtes Dokument gegen Web prüfen

```text
(Nutze Dokument 2 und suche anschließend im Web)
Gleiche die Aussagen mit öffentlichen Quellen ab.
```

Dabei wird **keine neue interne Suche** durchgeführt; Dokument 2 ist direkte interne Evidence. Der Webquery-Helper darf relevante Eigennamen, Firmen, Orte, Aktenzeichen oder Relationen aus dieser Evidence als Suchanker verwenden.

## 7.4 Automatischer Web-Fallback

Für vertrauenswürdige Frontends kann bei unzureichender interner Evidence Web hinzugenommen werden. Voraussetzungen:

1. `web.yaml: enabled: true`,
2. Web Research im Admin UI für den kanonischen Benutzer aktiviert,
3. Client sendet:

```http
X-RAG-Web-Allowed: true
```

4. konservativer Web-Gate entscheidet `use_web=true`.

Ein interner Nulltreffer löst daher nicht automatisch und blind einen externen Request aus.

---

# 8. Webarchiv

Multiuser-Archivziele werden pro kanonischem Benutzer im Admin UI/`users.sqlite` gespeichert. Nextcloud WebDAV bleibt die Schreibberechtigungsinstanz.

Layout:

```text
<archive-root>/2026-09/09-191542-abcd/
    recherche.md
    fetch-log.jsonl
    01-source.txt
    .01-source.metadata.json
    01-source.pdf
    02-source.txt
    .02-source.metadata.json
    02-source.pdf
```

Der `.txt`-Snapshot enthält u. a.:

- Final-URL,
- Original-URL,
- Titel,
- Publisher,
- Veröffentlichungsdatum falls erkannt,
- Abrufzeitpunkt,
- Content-Type,
- SHA-Hash,
- Search-Provider,
- Search-Rank,
- Relevance-Score und -Reason,
- Query,
- extrahierten Text.

`fetch-log.jsonl` schreibt pro tatsächlich angefordertem Suchtreffer genau einen JSON-Datensatz mit Requested/Final URL, HTTP-Status, Redirect-Zahl, Fetch-Fehler, Content-Hash und der vollständigen Relevance-Entscheidung. Damit bleiben auch verworfene Recherchepfade nachvollziehbar.

`write_metadata_json:true` erzeugt für jede ausgewählte Quelle eine separate, versteckte Metadatendatei (`.NN-source.metadata.json`). Wenn `archive.renderer.enabled:true` gesetzt ist, werden ausgewählte HTML-Quellen nach dem synchronen Text-/Metadaten-Archivschritt in einer begrenzten In-Process-Background-Queue gerendert. Das Sidecar steht zunächst auf `render.status=pending` und wird anschließend auf `complete` oder `failed` aktualisiert. Bereits gelieferte PDFs werden unverändert gespeichert. Renderer-Fehler sind fail-open und beeinflussen die Text-Evidence oder Benutzerantwort nicht.

Der gemeinsame Playwright-Renderer nutzt standardmäßig einen Desktop-Viewport von 1440×900 und A4 Landscape. Optionaler best-effort Consent/Overlay-Cleanup bleibt bewusst begrenzt. Bei `persist_state:true` wird Browser-Storage pro angefordertem Host in einem lokalen Renderer-Volume wiederverwendet, damit normale Cookie-Zustimmungen nicht bei jeder Recherche neu erscheinen. Der Archiv-Renderer ist für öffentliche Quellen gedacht: Login-Walls, Paywalls, CAPTCHAs und Zugriffssperren werden nicht umgangen oder automatisch entfernt. Die Sidecar-Metadaten protokollieren Landscape/Viewport, State-Reuse und Cleanup-Aktionen.

`write_raw_html:true` speichert zusätzlich den originalen Haupt-HTML-Response. Das ist **kein** vollständiger WARC-/Browser-Snapshot mit Unterressourcen. Auch das Playwright-PDF ist eine visuelle Momentaufnahme und kein forensisches Capture.

Archivierte `.txt`-Quellen können unmittelbar über `/use:W1` wiederverwendet werden, ohne auf eine spätere Elasticsearch-Synchronisation zu warten. Der Zugriff erfolgt erneut über den aktuellen Benutzer-WebDAV-Zugang.

---

# 9. Trusted Clients und Benutzeridentität

Provider-Bearer identifizieren Frontend-Clients, nicht Personen.

```text
scoped identity = client_id::external_user_id
canonical user  = (nextcloud_server, nextcloud_login)
```

Ein Benutzer kann über mehrere Trusted Clients denselben kanonischen Nextcloud-Account erreichen.

Externes OpenWebUI:

```json
{
  "X-OpenWebUI-User-Id": "{{USER_ID}}"
}
```

Automatischer Web-Fallback zusätzlich:

```json
{
  "X-OpenWebUI-User-Id": "{{USER_ID}}",
  "X-RAG-Web-Allowed": "true"
}
```

Jedes Frontend erhält einen eigenen Provider-Client-Key.

---

# 10. Administrations-CLI

Alle Beispiele aus `/opt/nextcloud-rag`:

```bash
cd /opt/nextcloud-rag
```

## 10.1 Trusted Provider Clients

Modul:

```bash
sudo -u rag ./.venv/bin/python -m rag.provider_clients ...
```

Befehle:

```text
list
create <client_id> [--name NAME]
rotate <client_id> [--name NAME]
enable <client_id>
disable <client_id>
delete <client_id>
```

Beispiele:

```bash
sudo -u rag ./.venv/bin/python -m rag.provider_clients list
sudo -u rag ./.venv/bin/python -m rag.provider_clients create openwebui-office --name "OpenWebUI Office"
sudo -u rag ./.venv/bin/python -m rag.provider_clients rotate openwebui-office
sudo -u rag ./.venv/bin/python -m rag.provider_clients disable openwebui-office
```

Create/Rotate geben den neuen API-Key **einmal** aus; gespeichert wird nur der Hash.

`delete` entfernt den Client und frontendgebundene Identitäts-/Nextcloud-Credential-Daten dieses Clients. Kanonische Benutzer und deren Mail-/Web-Einstellungen bleiben bestehen, sofern sie noch anderweitig genutzt werden können.

## 10.2 Kanonische Benutzer

```bash
sudo -u rag ./.venv/bin/python -m rag.user_admin list
sudo -u rag ./.venv/bin/python -m rag.user_admin show <login> [--server URL]
sudo -u rag ./.venv/bin/python -m rag.user_admin reauth <login> [--server URL]
sudo -u rag ./.venv/bin/python -m rag.user_admin set-mail-password <login> [--server URL] [--account-id ID]
```

`reauth` entfernt Nextcloud-App-Passwörter und Pending Login Flows; der kanonische Benutzer sowie Mail-/Web-Einstellungen bleiben.

### Legacy/fortgeschrittene Credential-CLI

```bash
sudo -u rag ./.venv/bin/python -m rag.user_credentials list-users
sudo -u rag ./.venv/bin/python -m rag.user_credentials set-nextcloud <user_id> <username> --client <client> --server <url>
sudo -u rag ./.venv/bin/python -m rag.user_credentials delete-nextcloud <user_id> --client <client>
```

Diese CLI ist für manuelle/diagnostische Bindings; normal ist Nextcloud Login Flow v2 zu bevorzugen.

---

# 11. Sync- und Retrieval-Diagnostik

## 11.1 Elasticsearch -> Qdrant Sync

```bash
sudo -u rag ./.venv/bin/python -m rag.sync [Optionen]
```

Optionen:

```text
-c, --config FILE
--include-path PREFIX       wiederholbar; überschreibt sync.include_paths
--exclude-path PREFIX       wiederholbar; überschreibt sync.exclude_paths
--max-documents N           0 = unbegrenzt
--dry-run                   keine Änderungen an Qdrant/State/Queue
--log-level LEVEL
--enqueue-graph             neue/geänderte Dokumente zusätzlich einreihen
--no-enqueue-graph          Graph-Enqueue für diesen Lauf deaktivieren
```

Beispiele:

```bash
sudo -u rag ./.venv/bin/python -m rag.sync --dry-run --include-path Nordstern
sudo -u rag ./.venv/bin/python -m rag.sync --include-path Nordstern --max-documents 500
```

Im Normalbetrieb übernimmt `start-sync-worker.sh` diesen Aufruf periodisch. Das ist kein eigener Synchronisationscode: State, Chunking, Embedding und Qdrant-Lifecycle bleiben vollständig in `rag.sync`. Der Mail-spezifische `post_sync.qdrant`-Hook sollte bei aktivem Sync Worker normalerweise deaktiviert bleiben.

## 11.2 Qdrant-/Embedding-Smoke

```bash
sudo -u rag ./.venv/bin/python -m rag.qdrant_smoke -c config.yaml
sudo -u rag ./.venv/bin/python -m rag.qdrant_smoke -c config.yaml --json
```

Der Probe erzeugt ein Embedding und prüft Qdrant/Collection. Qdrant und Embedding-Backend sind konzeptionell getrennte Fehlerquellen; bei Diagnose beide separat prüfen.

## 11.3 Live-ACL-Smoke

```bash
sudo -u rag ./.venv/bin/python -m rag.acl_smoke files:42040 files:66732 --user-id 'client::userid'
```

Numerische IDs werden automatisch zu `files:<id>` normalisiert.

## 11.4 Manuelle Hybridsuche

```bash
sudo -u rag ./.venv/bin/python -m rag.hybrid_search \
  "unberechtigter Zugang" \
  --must Firmenadresse \
  --should Geschäftsanschrift \
  --phrase "Nutzungsuntersagung" \
  --limit 10
```

Optionen:

```text
semantic                         optionale semantische Query
--must TERM                      wiederholbar
--should TERM                    wiederholbar
--not TERM                       wiederholbar
--phrase PHRASE                  wiederholbar
--from-date YYYY-MM-DD
--to-date YYYY-MM-DD
--limit N
--es-limit N
--vector-limit N
--threshold FLOAT
```

---

# 12. Graph-Administration

Hauptmodul:

```bash
sudo -u rag ./.venv/bin/python -m rag.graph --config config.yaml <command>
```

## 12.1 Basis und Inspektion

```text
check
init
stats
candidates
find <query> [--limit N]
merges [query] [--limit N]
entity --entity <ENTITY_ID>
observations --entity <ENTITY_ID>
forms --entity <ENTITY_ID>
blocked-entities
```

## 12.2 Kandidaten/Backfills

```text
refresh-candidates [--max-candidates N]
identity-backfill
curation-backfill
form-policy-backfill
```

Diese Backfills sind konservative Wartungsoperationen; `identity-backfill` führt keine automatischen Entity-Merges aus.

## 12.3 Merge und Negative Identity

Preview ist Default:

```bash
sudo -u rag ./.venv/bin/python -m rag.graph merge \
  --keep <ENTITY_A> --merge <ENTITY_B>
```

Tatsächlich ausführen:

```bash
sudo -u rag ./.venv/bin/python -m rag.graph merge \
  --keep <ENTITY_A> --merge <ENTITY_B> --alias-policy contextual --yes
```

Merge dauerhaft ablehnen:

```bash
sudo -u rag ./.venv/bin/python -m rag.graph reject-merge \
  --left <ENTITY_A> --right <ENTITY_B> --reason manual_rejection --yes
```

## 12.4 Namen, Aliase, Policies

```bash
sudo -u rag ./.venv/bin/python -m rag.graph correct-name \
  --entity <ID> --name "Max Alexander Mustermann" --yes

sudo -u rag ./.venv/bin/python -m rag.graph add-alias \
  --entity <ID> --alias "Max Mustermann" --policy contextual --weight 0.95 --yes

sudo -u rag ./.venv/bin/python -m rag.graph remove-alias \
  --entity <ID> --alias "Mäx Mustermann" --yes

sudo -u rag ./.venv/bin/python -m rag.graph set-form-policy \
  --entity <ID> --form "D. Wahl" --policy search_only --yes
```

Policies:

| Policy | Wirkung |
|---|---|
| `exclusive` | Query + harte Ingestion-Identitätsauflösung |
| `contextual` | Query/Kandidat, keine harte Ingestion-Auflösung |
| `search_only` | nur Query-Erweiterung |
| `document_only` | nicht als globaler Resolver/Search-Form exponiert |

## 12.5 Observation korrigieren / Nicht-Entity löschen

```bash
sudo -u rag ./.venv/bin/python -m rag.graph correct-observation \
  --observation <OBS_ID> --entity <TARGET_ENTITY> --reason ocr --yes

sudo -u rag ./.venv/bin/python -m rag.graph delete-entity \
  --entity <ID> --reason manual_not_an_entity --yes
```

`delete-entity` erhält die zugrunde liegenden Observations als verworfene Evidence, statt Provenienz spurlos zu entfernen.

## 12.6 CardDAV-Provenienz

```text
contact-sources
contact-import-runs [--limit N]
contacts [--cloud ID] [--source-user ID] [--addressbook NAME] [--import-run ID] [--limit N]
contact-provenance-backfill [--cloud ID] [--source-user ID]
rollback-contacts [Scope...] [--priority high|normal|background] [--no-relink] [--yes]
reassign-contact --contact <CONTACT_ID> --entity <ENTITY_ID> [--priority ...] [--no-relink] [--yes]
```

## 12.7 Totaler Graph-Reset

```bash
sudo -u rag ./.venv/bin/python -m rag.graph reset --yes-really-delete-all
```

Dieser Befehl löscht **alle** Graphdaten und erfordert bewusst eine eigene Bestätigungsoption.

---

# 13. GraphQueue und GraphWorker

## Queue-Status

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_queue stats
sudo -u rag ./.venv/bin/python -m rag.graph_queue recent --limit 20
```

## Pfad einreihen

Preview:

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_queue enqueue-path \
  Nordstern/Beteiligungen --priority normal
```

Ausführen:

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_queue enqueue-path \
  Nordstern/Beteiligungen \
  --exclude-path Nordstern/Beteiligungen/Archiv \
  --priority background --yes
```

## Worker

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_worker
sudo -u rag ./.venv/bin/python -m rag.graph_worker --once
sudo -u rag ./.venv/bin/python -m rag.graph_worker --once --ignore-idle
```

Der Worker respektiert standardmäßig Idle-Zeit und konfigurierte Quiet Hours.

---

# 14. Graph-Indexierung/Rebuild

## Ein Dokument manuell indexieren

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_indexer \
  --document files:66732 \
  --query "manuelle Graphanalyse"
```

Optionen:

```text
--document ID       wiederholbar; erforderlich
--query TEXT
--no-fuzzy
--no-discovery      kein LLM-Entity-Discovery; nur bekannte Entities relinken
--no-relations      keine LLM-Relation-/Claim-Discovery
--force             unveränderte Hashes trotzdem neu verarbeiten
```

## Queue-Evidence durch Graph v3 replayen

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_rebuild --phase both
```

Optionen:

```text
--phase discover|relink|relations|both
--limit N
--offset N
--document ID       wiederholbar
--sleep SECONDS
--log-level LEVEL
--force
--force-oversize
```

## Entity-Duplikate nur vorschlagen

```bash
sudo -u rag ./.venv/bin/python -m rag.identity_suggestions \
  --type Person --min-score 0.70 --limit 50
```

Die Scores sind Triage-Heuristiken, keine Identitätswahrscheinlichkeiten; es werden keine Daten verändert.

## Query-Entity-Auflösung diagnostizieren

```bash
sudo -u rag ./.venv/bin/python -m rag.graph_entities \
  "Welche Verbindung besteht zwischen Max Mustermann und Musterhof 280?"
```

Optionen: `--no-fuzzy`, `--fuzzy-threshold`, `--fuzzy-max-candidates`.

---

# 15. CardDAV-Sync / Kontakt-Seeds

Im Mehrbenutzerbetrieb wird CardDAV über den verifizierten Nextcloud-Account administriert. Die interne `canonical_user_id` ist nur Join-Key; UI und CLI verwenden `nextcloud_login` und bei Mehrdeutigkeit zusätzlich `--server`. Das bereits durch Login Flow gespeicherte Nextcloud-Credential wird wiederverwendet.

Admin UI:

```text
RAG Admin -> Users -> <Nextcloud-Login> -> Kontakt-DB
```

Native CLI:

```bash
sudo -u rag ./.venv/bin/python -m rag.contacts list
sudo -u rag ./.venv/bin/python -m rag.contacts status --user alice
sudo -u rag ./.venv/bin/python -m rag.contacts books --user alice
sudo -u rag ./.venv/bin/python -m rag.contacts sync --user alice
```

Dockerized Super-Light:

```bash
cd /opt/nextcloud-rag/install/super-light
./contacts.sh list
./contacts.sh status --user alice
./contacts.sh books --user alice
./contacts.sh sync --user alice
```

Optionen für `sync`: `--dry-run`, `--limit`, `--force`; bei identischem Login auf mehreren Nextcloud-Instanzen zusätzlich `--server URL`. Fehlt das Nextcloud-Credential, ist der Benutzer/die Kontaktquelle deaktiviert oder existieren keine Kontakte, endet der Lauf als No-op statt als Stack-Fehler. Der Admin-UI-Aufruf startet einen Hintergrundjob und zeigt einen Fortschrittsbalken. Die UI kann verfügbare Adressbücher mit Anzeigename und technischem Slug ermitteln. Nach einem vollständigen erfolgreichen Lauf werden verschwundene CardDAV-hrefs aus den ContactRecords reconciled; `--limit`, `--dry-run` oder fehlgeschlagene Scans führen keine Quellenlöschung aus.

Die ContactRecord-Provenienz bleibt extern nachvollziehbar über Nextcloud-Instanz (`cloud_id`), `source_user_id`/Login, Adressbuch und vCard-UID. Die kanonische UUID wird nicht zur fachlichen Quellenidentität. Das alte `python -m rag.carddav_sync` ohne `--user` und `NEXTCLOUD_USERNAME`/`NEXTCLOUD_APP_PASSWORD` bleibt nur als Single-User-Kompatibilitätspfad.

---

# 16. Mail-Sync

Der langlaufende Scheduler ist deployment-neutral: native/systemd startet `.venv/bin/python -m rag.mail_worker`, Docker startet `python -m rag.mail_worker`. Der Prozess bleibt auch bei deaktiviertem Mail/Worker-Schalter aktiv und liest Konfiguration/Intervall regelmäßig neu.

Global muss `config.yaml: mail.enabled=true` gesetzt sein; zusätzlich muss ein aktives Mailkonto für den kanonischen Benutzer existieren.

```bash
sudo -u rag ./.venv/bin/python -m rag.mail_sync
```

Filter:

```text
--user <login|canonical_user_id>
--account <account_id|name>
--mailbox <IMAP-folder>       diese Mailbox als rekursive Wurzel
--max-messages N             Limit pro tatsächlich synchronisierter Mailbox
--dry-run
```

Beispiel:

```bash
sudo -u rag ./.venv/bin/python -m rag.mail_sync \
  --user demo-user --mailbox INBOX --max-messages 50 --dry-run
```

## Rekursive Mailboxen

Die in einem Mailkonto konfigurierten `mailboxes` sind Wurzeln, keine statische Liste. Vor jedem Account-Lauf fragt die Middleware den Server mit IMAP `LIST` ab und synchronisiert die Wurzel sowie alle **selektierbaren Unterordner** rekursiv. `\Noselect`-Container werden übersprungen, ihre selektierbaren Kinder bleiben erhalten. Der vom IMAP-Server gemeldete Hierarchietrenner wird übernommen; die Ordnerhierarchie bleibt damit auch in Nextcloud sichtbar.

Beispiel für `INBOX/Projekte/2026`:

```text
<target>/<account>/INBOX/Projekte/2026/<year>/<month>/...
```

Nicht-ASCII-Mailboxnamen werden für klassisches IMAP4rev1 als Modified UTF-7 behandelt.
Im Admin kann **Verbindung testen & Mailboxen ermitteln** die vom Server sichtbaren Mailboxen, Flags und Hierarchietrenner anzeigen; diese Anzeige verwendet dieselbe Discovery-Funktion wie der Sync.

## Ein Ordner pro E-Mail

Neue Importe werden ab dieser Version ausschließlich im Directory-per-Mail-Layout geschrieben:

```text
<target>/<account>/<mailbox-hierarchy>/<year>/<month>/
  <timestamp>_<uid>_<subject>/
    mail.txt
    .mailmeta.json
    a01_<attachment>
    a02_<attachment>
    ...
    message.eml              # optional
```

`mail.txt` ist die indexierbare Normalform. `.mailmeta.json` enthält deterministische Mail-/Thread-Metadaten, IMAP UID/UIDVALIDITY, Importzeitpunkt, ausgewählte technische Header (`Return-Path`, `Received`, Authentication-/DKIM-/SPF-Informationen) sowie SHA-256 und Byte-Länge der vom IMAP-Server geholten Rohmessage. Attachments liegen direkt bei der Nachricht. Neue Konten speichern die redundante `message.eml` standardmäßig **nicht**; `store_eml=true` bleibt als explizite Option für Roh-/Forensik-Aufbewahrung erhalten.

Alte flache Archive bleiben durch den Sidecar-Reader lesbar, werden aber **nicht automatisch verschoben**. Das vermeidet eine destruktive Datenmigration. Für einen vollständigen Neuaufbau sollte ein neuer/leerer Zielpfad verwendet und der Mail-State kontrolliert neu initialisiert werden.

## Nachlauf zu Elasticsearch/Qdrant

Optional kann der Mail-Sync weiterhin Nextcloud FullTextSearch für tatsächlich beschriebene Monatsverzeichnisse anstoßen. Der generische ES→Qdrant-Abgleich sollte danach über den dedizierten `sync_worker` erfolgen. So werden nicht nur Mails, sondern auch alle anderen neuen/geänderten Nextcloud-Dokumente nach derselben Logik in Qdrant übernommen.

---

# 17. Reset der semantischen Daten

```bash
./reset-rag.sh
```

zeigt nur Warnung. Tatsächlicher Reset:

```bash
./reset-rag.sh --yes
```

Gelöscht werden:

- lokaler SQLite-Sync-State,
- konfigurierte Qdrant-Collection.

**Nicht** verändert werden Elasticsearch und Nextcloud.

---

# 18. HTTP-API-Kurzreferenz

Interne API (standardmäßig `127.0.0.1:8765`):

```text
POST   /auth/nextcloud/start
POST   /auth/nextcloud/ensure
GET    /auth/nextcloud/status/{flow_id}
DELETE /auth/nextcloud/{rag_user_id}
GET    /health
POST   /web/search
POST   /web/archive/finalize
POST   /plan
GET    /graph/stats
POST   /graph/document
POST   /graph/enqueue-evidence
GET    /graph/queue/stats
GET    /graph/queue/jobs
POST   /graph/index-evidence
POST   /documents/resolve
POST   /elastic/search
POST   /multi-search
POST   /search
```

Diese Endpunkte sind primär interne Provider-/Admin-Schnittstellen; normale Benutzer sprechen den OpenAI-kompatiblen Provider unter `/v1/` an.

---

# 19. Sicherheit und Credentials

## 19.1 Verschlüsselter `runtime/users.sqlite`-Store

Wichtige Tabellen:

```text
provider_clients
canonical_users
identity_bindings
credentials
nextcloud_login_flows
mail_accounts
user_web_settings
contact_sync_settings
web_archive_roots
store_meta
```

Credential-Primärschlüssel berücksichtigen u. a. `rag_user_id`, `service`, `account_id`. **Nie** Credentials nur nach `username` per SQL aktualisieren.

Reversible Werte in `credentials` (`nextcloud`, `mail_imap`) sowie Nextcloud-Login-Flow-Poll-Tokens werden in `0.8.3-rc6` mit **AES-256-GCM** verschlüsselt. Das gespeicherte Format ist versioniert (`enc:v1:`). Additional Authenticated Data bindet den Ciphertext an seine fachliche Identität; das Kopieren eines Ciphertexts auf einen anderen Benutzer/Service/Account führt deshalb zu einem Authentifizierungsfehler.

Trusted-Client-Keys in `provider_clients` bleiben nicht reversibel und werden weiterhin nur als SHA-256-Digest gespeichert.

## 19.2 Master-Key und Betriebsmodi

Fresh Install:

```text
runtime/credential-master.key   root:rag 0640
runtime/users.sqlite            rag:rag 0600
```

Konfiguration:

```bash
RAG_CREDENTIAL_MASTER_KEY_FILE=/opt/nextcloud-rag/runtime/credential-master.key
RAG_CREDENTIAL_ENCRYPTION=required
```

Modi:

- `required`: Produktionsmodus; Klartext-Credential-Reads und fehlender/unsicherer Master-Key führen fail-closed zum Fehler.
- `preferred`: Migrations-/Entwicklungsmodus; vorhandener Key wird genutzt, ältere Klartexte können kontrolliert migriert werden.
- `disabled`: ausschließlich Diagnose/Legacy; neue Secrets bleiben Klartext und dieser Modus ist nicht für Produktion vorgesehen.

Der Master-Key muss separat gesichert werden. Ein Backup von `users.sqlite` ohne den zugehörigen Master-Key ist für verschlüsselte Credentials nicht wiederherstellbar.

## 19.3 Secret-Administration

```bash
cd /opt/nextcloud-rag
./.venv/bin/python -m rag.secret_admin status
sudo ./.venv/bin/python -m rag.secret_admin init-key --group rag
sudo -u rag ./.venv/bin/python -m rag.secret_admin migrate
sudo -u rag ./.venv/bin/python -m rag.secret_admin verify
```

`status`, `migrate` und `verify` geben niemals Secret-Werte aus. `verify` liefert Exit-Code 2, wenn Klartextreste oder Entschlüsselungsfehler vorhanden sind.

Das RAG-Admin-Interface zeigt unter `/rag-admin/security` ausschließlich Statusinformationen. IMAP-Credentials werden getrennt von der Mailkonto-Konfiguration gesetzt/ersetzt; gespeicherte Passwörter werden niemals als Formularwert zurückgegeben.

## 19.4 Grenzen von Stufe 1

Der Dienstaccount `rag` benötigt für den laufenden Betrieb Leserechte auf den Master-Key. Stufe 1 schützt damit insbesondere SQLite-/Backup-/Admin-Zugriffe, ist aber kein Schutz gegen `root` oder einen vollständig kompromittierten `rag`-Prozess.

Globale Secrets wie `LLM_API_KEY`, `WEB_SEARCH_API_KEY`, `ELASTICSEARCH_PASSWORD`, `NEO4J_PASSWORD`, `RAG_ADMIN_PASSWORD` und `PROVIDER_API_KEY` liegen weiterhin in `runtime.env`. Eine spätere Stufe 2 kann sie in dieselbe Secret-Abstraktion überführen und auf modernen Hosts optional systemd credentials/TPM oder einen privilegierten Helper verwenden.

## 19.5 TLS

Für Nextcloud ist TLS-Verifikation Default. `security.allow_insecure_nextcloud=true` ist ausschließlich Lab-Escape-Hatch.

Für Elasticsearch/LLM/Web können private CAs über die jeweiligen CA-/Verify-Einstellungen eingebunden werden. Im dockerisierten Super-Light-Deployment kann `install.sh --profile super-light --ca-certificate <PEM>` wiederholt angegeben werden; die Zertifikate werden in den System-Trust des API/Provider-Images aufgenommen. Für die native Standardinstallation wird die private CA im Host-Truststore gepflegt; falls die Python-Laufzeit nicht automatisch den System-Bundle nutzt, `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` auf den kombinierten Host-CA-Bundle setzen.

---

# 20. OpenWebUI

Gepinnte Bundle-Version laut `versions.lock.yaml`:

```text
ghcr.io/open-webui/open-webui:v0.11.0
```

Der aktuelle Installer stellt OpenWebUI bereit und bindet es loopback an den Provider. Die geplante restriktive Vorkonfiguration als „reines Frontend“ ist **noch nicht vollständig umgesetzt**. Bis dahin kann ein Administrator OpenWebUI selbst härten und insbesondere eigene RAG-/Knowledge-, Tool-, Plugin-, Websearch-, Update- und Workspace-Funktionen deaktivieren.

OpenWebUI-Follow-up-Helper wird bereits providerseitig unterdrückt und erzeugt keinen LLM-Aufruf.

Die Einbindung von OpenWebUI als externe Seite in Nextcloud funktioniert ohne besondere Middleware-Unterstützung und ist eine geeignete Navigationsintegration.

---

# 21. Health und Troubleshooting

## Gesamtstatus

```bash
./status.sh
```

Im Chat:

```text
/health
```

Direkt:

```bash
curl -s http://127.0.0.1:8765/health | jq
curl -s http://127.0.0.1:8766/live | jq      # cheap provider liveness, no remote LLM probe
curl -s http://127.0.0.1:8766/health | jq    # explicit provider diagnostics; may probe configured LLM backends
```

## Web

Wenn `/web` meldet, dass keine relevante abrufbare Quelle gefunden wurde:

1. API-Log prüfen, nicht nur Provider-Log.
2. Search-Anzahl vs. Fetch-Anzahl prüfen.
3. `web relevance decisions` prüfen.
4. `WEB_SEARCH_API_KEY` und optional `WEB_LLM_API_KEY` prüfen.
5. Bei Brave 401/429/5xx Search-Provider diagnostizieren.
6. Bei Fetch-Ausfällen TLS, Redirects, Content-Type und SSRF/private-target-Regeln prüfen.

Die Web-Relevance-Prüfung erwartet vollständige Structured-Output-Entscheidungen für alle geladenen Quellen; unvollständige Antworten werden retried und danach explizit als Fehler ausgegeben.

## Vector/Qdrant

Qdrant-Status und Embedding-Backend getrennt prüfen:

```bash
sudo -u rag ./.venv/bin/python -m rag.qdrant_smoke --json
```

Ein verbleibender bekannter Diagnosepunkt im aktuellen Freeze-Kandidaten ist, dass bestimmte Vector-Fehler in übergeordneten Meldungen noch zu generisch als `vector unavailable` zusammengefasst werden können. Ein echter Nulltreffer sollte konzeptionell nicht dasselbe sein wie ein Backend-Ausfall; bei Unklarheit API-Log und Smoke-Probe verwenden.

## ACL

```bash
sudo -u rag ./.venv/bin/python -m rag.acl_smoke files:<id> --user-id '<client>::<user>'
```

Keine ACL-Fehler durch künstlichen Backfill „kompensieren“.

---

# 22. Aktueller Feature-/Freeze-Status

**0.8.5-rc3 implementiert und im Tarball enthalten:**

- gemeinsamer Middleware-Core mit `standard+native` und `super-light+dockerized`,
- Query Rewriter/SearchSpec + Elasticsearch + optional Qdrant; Neo4j für Seed-/Alias-Expansion,
- Super-Light ohne Qdrant/lokalen Reranker, aber mit unabhängiger Dublettenerkennung,
- abgeleiteter QueryFrame / kompakter Verifier / RetrievalRecord-Code,
- Live Nextcloud ACL ohne Backfill,
- rollenabhängige lokale/remote LLM-Konfiguration,
- Brave und SearXNG Web Search, Fetch + Passage Selection + Relevance-Gate,
- gemeinsamer Playwright-Renderer mit 1440×900 Desktop-Viewport und A4 Landscape,
- versteckte Webarchiv-Metadaten-Sidecars und best-effort persistenter Consent-State,
- Graph CLI/Curation und `AKI Recherche`-Findings mit manueller Graph-Lite-Entity-/Claim-Kuration und Bulk-Entscheidungen,
- CardDAV-Seeds pro verifiziertem Nextcloud-Benutzer über Admin UI/CLI,
- Multiuser Nextcloud Login Flow,
- admin-gesteuerte Mail-/Web-/Kontakt-Einstellungen,
- AKI Recherche 0.2.3 für Nextcloud 23+ mit Chatpersistenz, Sidebar, sicheren Markdown-Tabellen, Zeitstempeln und Source-Scopes.

**Bewusst außerhalb des 0.8.5-Beta-Scope:**

- vollständiger Browser-/WARC/WACZ-Snapshot,
- automatische globale Faktmaterialisierung aus QueryFrames,
- `standard+dockerized` als freigegebener Deploymentpfad,
- komplexe site-spezifische Cookie/Paywall/Login-Automation.

Weitere operative Grenzen stehen in `docs/KNOWN-LIMITATIONS.md`. Nach dem
0.8.5-RC1-Architekturfreeze werden vor allem Query-Rewrite, optionale Retrieval-Runden,
Retrieval-Qualität und UI-Komfort weiterentwickelt.

---

# 23. Releasevalidierung

Der 0.8.5-rc3 Tarball wird beim Packaging und nach erneuter Extraktion geprüft auf:

```text
MANIFEST                 264/264 OK
pytest                    375 passed
YAML                      13 Dateien OK
XML                       2 Dateien OK
Shell syntax              OK
Python compile            OK
AKI/PHP                   9 Dateien OK
JavaScript syntax         OK
Package hygiene           OK
```

Die zugrunde liegenden Super-Light-Feldpfade wurden auf einem frischen Leap-15.3-Klon in der internen RC2-Linie erfolgreich installiert und betrieben. Die RC3-spezifischen Änderungen betreffen vor allem Findings-Kuration, Admin-JavaScript/CSP, Veröffentlichungshygiene und Dokumentation. In der neutralen Packaging-Umgebung wurde **kein neuer Blank-VM-Lauf** ausgeführt; dieser bleibt Teil der Betreiber-Akzeptanz vor produktivem Rollout. Die Docker-Images in `versions.lock.yaml` sind digest-gepinnt. Secrets sind nicht Bestandteil des Pakets.

# Role-specific LLM routing

The canonical `LLM_*` variables remain the compatibility default. The following
optional prefixes override individual roles:

```text
PLANNER_LLM_*
VERIFIER_LLM_*
EVIDENCE_LLM_*
ANSWER_LLM_*
```

Each role accepts `BACKEND`, `BASE_URL`, `MODEL`, `API_KEY`, `VERIFY_TLS`,
`CA_FILE` and `SCOPE` (`local|remote`). Unset values inherit the default.
Provider `/health` reports effective role routing and scope.

Remote evidence budgets are configured by:

```text
REMOTE_LLM_MAX_CHARS_PER_DOCUMENT
REMOTE_LLM_MAX_TOTAL_CHARS
REMOTE_VERIFIER_MAX_CANDIDATES
REMOTE_VERIFIER_MAX_CHARS_PER_DOCUMENT
REMOTE_ANSWER_MAX_DOCUMENTS
```

The graph worker is controlled by `graph_queue.worker.enabled`; cited documents
are automatically enqueued only when `graph_queue.auto_enqueue_cited_documents`
is true. Mail background polling is independently controlled by
`mail.worker.enabled`.

Web archive TLS verification is independent of search/fetch/relevance TLS and is
controlled by `web.yaml: archive.verify_tls`. The current default does not archive
raw HTML (`write_raw_html: false`); fetched text snapshots and raw PDFs remain
available for provenance while reducing write amplification.

## AKI-Recherche-Findings (RC10)

`POST /graph/research-findings` übernimmt ausschließlich bereits strukturierte Query-Rewriter-/Verifier-Ergebnisse. Der Endpunkt startet keinen Graph-Worker und keinen LLM-Lauf. Akzeptiert werden nur Dokumenteinträge mit `verification_status=match` und `relation_binding=direct`.

Konfiguration:

```yaml
research_findings:
  enabled: true
  timeout: 5
  max_documents_per_request: 30
```

Neo4j-Modell:

```text
(:ResearchFinding:AKIResearchFinding)-[:SUPPORTED_BY]->(:Document)
(:ResearchFinding)-[:QUERY_ENTITY {role, text, resolution}]->(:Entity)   # nur eindeutig exakt aufgelöst
```

Wesentliche Properties sind `finding_id`, `frame_hash`, `query_frame_json`, `evidence_frame_json`, `intent`, `entity_texts`, `relation_texts`, `constraints_json`, `concepts`, `provenance_code=aki_research`, `provenance_label=AKI Recherche`, Query-Rewriter-/Verifier-Modell, Softwareversion sowie First/Last-Seen und `observation_count`. `finding_id` ist deterministisch aus Provenienz, Dokument-ID und kanonischem Query-Frame gebildet.

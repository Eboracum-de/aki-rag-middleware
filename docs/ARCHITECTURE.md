# AKI RAG Middleware
## Architecture and design baseline 0.8.5-rc3

**Stand:** 16. September 2026
**Status:** Release Candidate
**Referenzversion:** `0.8.5-rc3`

---

## 1. Zusammenfassung

Die AKI RAG Middleware verbindet einen bestehenden Nextcloud-Dokumentbestand mit mehreren voneinander unabhängigen Retrieval-Pfaden und einer nachgelagerten LLM-Antwortschicht. Ziel ist keine neue Dokumentenablage und keine zweite Berechtigungsdatenbank, sondern eine rechercheorientierte Vermittlungsschicht zwischen natürlicher Sprache, vorhandener Volltextsuche, semantischer Suche, einem dokumentengeerdeten Wissensgraphen und optionaler öffentlicher Web-Recherche.

Das zentrale Sicherheitsprinzip lautet:

> **Retrieval-Systeme liefern nur Kandidaten. Nextcloud selbst bleibt die letzte Autorisierungsinstanz.**

Elasticsearch, Qdrant und Neo4j dürfen deshalb Kandidaten vorschlagen, aber kein Treffer erreicht Verifier oder Antwortmodell, wenn der aktuell angemeldete Nextcloud-Benutzer den Zugriff nicht live über Nextcloud bestätigt bekommt. Werden Kandidaten durch die ACL entfernt, werden bewusst **keine** schlechter gerankten Dokumente nachgeschoben.

Die aktuelle Referenzarchitektur kombiniert:

- Nextcloud FullTextSearch / Elasticsearch für lexikalisches Retrieval,
- Qdrant für semantisches Retrieval,
- Neo4j für Entity-/Relationssignale und dokumentengeerdete Graphpfade,
- Reciprocal Rank Fusion (RRF) zur Zusammenführung,
- einen optional lokalen oder externen Cross-Encoder-Reranker,
- Live-Nextcloud-ACL,
- einen kompakten dokumentengeerdeten Kandidaten-Verifier,
- ein LLM für Antwortgenerierung,
- optional Brave Search oder SearXNG als öffentliche Web-Discovery,
- einen Web-Relevance-Gate, der nur tatsächlich geladene Seiten als Evidence zulässt,
- ein WebDAV-Webarchiv in Nextcloud.

Im Referenzbetrieb laufen Embeddings lokal (`qwen3-embedding:4b` über Ollama), während Query-Rewriter, Verifier, Evidence-Controller und Antwortmodell rollenweise lokal oder über einen OpenAI-kompatiblen Provider angesprochen werden können. Die LLM- und Embedding-Schichten sind bewusst getrennt. Das Embedding-Modell ist austauschbar; Prefixes/Rollenformatierung und optionale Ausgabedimension werden explizit konfiguriert und nicht aus Modellnamen abgeleitet.

---

## 2. Problemstellung

Klassische Volltextsuche setzt voraus, dass der Benutzer die im Dokument verwendeten Wörter, Schreibweisen, Zeitangaben oder Suchsyntax hinreichend genau kennt. In realen Ablagen treten jedoch typischerweise folgende Probleme auf:

- unterschiedliche Schreibweisen und Abkürzungen,
- OCR-Fehler,
- unvollständige oder umgangssprachliche Benutzerfragen,
- Beziehungen, die nicht in einem einzelnen Schlüsselwort ausdrückbar sind,
- relevante Dokumente, in denen gesuchte Rollen oder Beziehungen nur indirekt beschrieben werden,
- viele semantisch ähnliche, aber sachlich falsche Treffer,
- unterschiedliche Dokumentversionen und widersprüchliche Arbeitsstände,
- Berechtigungen, die sich in Nextcloud laufend ändern.

Die Middleware übersetzt natürliche Sprache zunächst in einen kleinen SearchSpec. Das LLM formuliert dabei eine menschenlesbare Nextcloud-Volltextanfrage (`elastic_query`, z. B. `+examplehost +2025 +Rechnung`) und parallel eine natürliche `semantic_query` für Qdrant. `entities`, `concepts`, `constraints` und `verification_requirements` fallen als analytische Nebenprodukte für Graph-Light, Verifier und Provenienz an. Die Middleware erzeugt daraus weiterhin kontrolliert Elasticsearch-JSON; das LLM schreibt keine rohe Elasticsearch-DSL und keine frei kombinierbaren Probe-Workflows.

---

## 3. Designziele

### 3.1 Hoher Recall ohne feste Fachontologie

Der Query Rewriter darf Begriffe, Rollen, Relationen und Constraints aus der Benutzerfrage in einem SearchSpec strukturieren, aber die Middleware enthält bewusst **keinen festen Katalog von Dokumenttypen oder Geschäftsprozessen**. Eine Rechnung, ein Vertrag, eine E-Mail oder ein Behördenvorgang werden nicht über hartcodierte Domänenregeln erkannt.

### 3.2 Dokumentengeerdete Präzision

Eine semantische Ähnlichkeit allein genügt nicht. Ein Dokument, in dem dieselben Firmen und dieselbe Rechnungsnummer erwähnt werden, kann für die konkrete Relation trotzdem falsch sein. Deshalb gibt es nach Retrieval, Ranking und ACL einen kompakten Verifier.

### 3.3 Nextcloud bleibt Berechtigungsquelle

Die Middleware repliziert ACLs nicht dauerhaft in Qdrant oder Neo4j. Das vermeidet Synchronisationsfehler, bei denen veraltete Shares oder Gruppenrechte unbeabsichtigt Zugriff gewähren könnten.

### 3.4 Fehlende Evidenz wird nicht erfunden

Wenn relevante Dokumente wegen ACL ausfallen oder kein belastbarer Treffer vorhanden ist, antwortet das System lieber mit weniger Evidenz oder gar nicht, statt schlechtere Kandidaten nachzurücken.

### 3.5 Provider und Modelle bleiben austauschbar

Answer-LLM, Embedding-Backend, Reranker und Web-Suchprovider sind getrennte Komponenten. Ein Wechsel des Answer-LLM darf keine Neuindexierung des Vektorraums erzwingen; ein Wechsel des Embedding-Modells dagegen schon.

### 3.6 Web-Recherche bleibt separater Evidence-Arm

Öffentliche Webquellen sind nicht einfach zusätzliche interne Dokumente. Sie werden separat gesucht, tatsächlich abgerufen, auf Relevanz geprüft, mit `W1`, `W2`, ... zitiert und auf Wunsch in Nextcloud archiviert.

---

## 4. Architektur

```text
                         Benutzer / AKI / OpenWebUI
                                |
                         OpenAI-kompatible API
                                |
                         Provider / Orchestrator
                                |
                +---------------+----------------+
                |                                |
          interner RAG-Pfad                öffentlicher Web-Pfad
                |                                |
        Query Rewriter                      Brave / SearXNG
        -> SearchSpec                           |
                |                           URL-Treffer
        Neo4j Seed/Alias Expansion              |
                |                           HTTP Fetch
          +-----+------+                         |
          |            |                   Passage Selection
   Elasticsearch     Qdrant                      |
      (files)       (optional)             Relevance Gate
          |            |                         |
          +-----+------+                   Web-Evidence W1..Wn
                |                                |
              Fusion                             |
                |                                |
             Dedup                               |
                |                                |
          optional Reranker                      |
                |                                |
          Live Nextcloud ACL                     |
                |                                |
        optional Candidate Verifier              |
                |                                |
                +---------------+----------------+
                                |
                          Antwortmodell
                                |
                   Quellen + optionale Archive
```

### 4.1 Komponenten und Rollen

| Komponente | Rolle | Autorisiert Dokumentzugriff? |
|---|---|---:|
| Query Rewriter | erzeugt `elastic_query`, `semantic_query` und Analysemetadaten | Nein |
| Neo4j | Seed-/Alias-/Entity-Expansion beim Rewrite; expliziter `/graph`-Dokumentarm bleibt optional | Nein |
| Elasticsearch | lexikalische Kandidaten aus der Nextcloud-kompatiblen `elastic_query` | Nein |
| Qdrant | semantische Kandidaten aus `semantic_query` | Nein |
| Reranker | optionale gemeinsame Relevanzsortierung | Nein |
| Nextcloud WebDAV ACL | Live-Sichtbarkeit des konkreten Benutzers | **Ja** |
| Candidate Verifier | optionale sachliche Passung zur Suchhypothese | Nein |
| Answer LLM | formuliert Antwort aus freigegebener Evidence | Nein |
| Brave/SearXNG | öffentliche Such-Discovery | nicht anwendbar |
| Web Relevance Gate | prüft tatsächlich geladene öffentliche Quellen | nicht anwendbar |

---

## 5. Interner Retrieval-Pfad

### 5.1 Normalmodus

Der Normalpfad verwendet pro Retrieval-Runde immer dieselbe kleine Schnittstelle:

1. Vor dem Rewrite wird aus Neo4j ein kompakter Seed-/Alias-Kontext geladen. Neo4j ist dabei kein automatischer Dokument-Retrieval-Arm.
2. Die Benutzerfrage wird in **einen** SearchSpec umgeschrieben. Der Rewriter formuliert eine Nextcloud-kompatible `elastic_query` und parallel eine natürliche `semantic_query`.
3. Der Files-Arm parst die `elastic_query` (`+must`, `-exclude`, Phrasen, weiche Begriffe) und kompiliert sie deterministisch in Elasticsearch-JSON mit den bewährten `content ODER title`-Semantiken.
4. Qdrant erhält – sofern aktiviert – ausschließlich `semantic_query`.
5. Elasticsearch und Qdrant werden fusioniert; Dubletten werden unabhängig vom Reranker unterdrückt.
6. Der Cross-Encoder-Reranker ist optional.
7. Die Live-Nextcloud-ACL entfernt nicht sichtbare Dokumente; es wird nicht mit schwächeren Treffern aufgefüllt.
8. Der Candidate Verifier kann die sachliche Passung prüfen; bei angeforderten Dokumenttypen muss das Dokument selbst diesem Typ entsprechen.
9. Das Antwortmodell formuliert quellengebunden.

Beispiel:

```text
Benutzer: Suche Rechnungen von examplehost aus dem Jahr 2025

SearchSpec:
  elastic_query:  +examplehost +2025 +Rechnung
  semantic_query: Rechnungen von examplehost aus dem Jahr 2025
  entities:       examplehost
  concepts:       Rechnung
  constraints:    Jahr=2025

Super-Light:
  Elasticsearch <- +examplehost +2025 +Rechnung
  Qdrant         <- deaktiviert

Standard:
  Elasticsearch <- +examplehost +2025 +Rechnung
  Qdrant         <- natürliche semantic_query
  -> Fusion
```

Die konkrete Elasticsearch-Query wird im SearchSpec-Pfad auf INFO geloggt. Dadurch ist administrativ nachvollziehbar, welche Query tatsächlich an ES ging.

Die Referenzwerte in `config.yaml` sind derzeit:

```yaml
search:
  es_limit: 50
  vector_limit: 80
  vector_threshold: 0.55
  rrf_k: 60
  rerank_candidates: 10
  final_limit: 15

# Der historische Abschnittsname bleibt aus Kompatibilitätsgründen.
# Runde 1 rewritet immer; enabled steuert nur zusätzliche Runden.
retrieval_planner:
  enabled: true
  max_retrieval_rounds: 1
  model: ""
  max_tokens: 700
  context_max_chars: 12000
  verification_candidate_limit: 6
  bounded_verification_candidate_limit: 30
  exhaustive_verification_candidate_limit: 30
```

`max_retrieval_rounds: 1` bedeutet: Query-Rewrite + genau ein Retrieval-Lauf. Sind weitere Runden konfiguriert und `enabled: true`, bewertet der Rewriter das sichtbare Trefferbild und darf einen **neuen SearchSpec** erzeugen. Jede Runde durchläuft danach wieder dieselbe ES/Qdrant/Fusionspipeline; es gibt keine separate Probe-/Arm-Syntax.

### 5.2 Explizite Retrieval-Arme

Der Benutzer kann den normalen Pfad überschreiben:

- `/files` – nur Elasticsearch, aber weiterhin über den strukturierten Query-Rewrite,
- `/vector` – nur Qdrant mit `semantic_query`,
- `/graph` – expliziter Legacy/Diagnose-Dokumentarm über Neo4j,
- Kombinationen wie `/files /vector` sind möglich,
- `/elastic` bleibt ein separater direkter Nextcloud-/Elasticsearch-Volltextmodus ohne Rewrite, Vector, Fusion oder Reranker.

Neo4j-Seed/Alias-Expansion ist davon unabhängig und kann auch bei `graph: disabled` in der Retrieval-Policy aktiv bleiben.

---

## 6. SearchSpec, QueryFrame, EvidenceFrame und RetrievalRecord

### 6.1 SearchSpec und QueryFrame: Suchhypothese

Der Query Rewriter erzeugt primär einen kleinen `SearchSpec`. Für Verifier-, Provenienz- und Research-Finding-Kompatibilität wird daraus zusätzlich ein offener `QueryFrame` abgeleitet:

```json
{
  "intent": "Rechnungen aus 2025 finden, die Nordstern GmbH an Example Logistics GmbH gestellt hat",
  "entities": [
    {"id": "q1", "text": "Nordstern GmbH", "role": "Rechnungsaussteller"},
    {"id": "q2", "text": "Example Logistics GmbH", "role": "Rechnungsempfänger"}
  ],
  "relations": [
    {"source": "q1", "predicate": "stellt Rechnung aus an", "target": "q2"}
  ],
  "constraints": [
    {"kind": "Jahr", "value": "2025"}
  ],
  "concepts": ["Rechnung"]
}
```

Diese Struktur ist **keine Tatsache**. Sie beschreibt ausschließlich, was gesucht wird.

### 6.2 EvidenceFrame: dokumentengeerdete Beobachtung

Der Verifier darf Relationen nur aus dem Kandidatendokument ableiten. Dadurch wird beispielsweise ein Dokument verworfen, das zwar `Nordstern GmbH`, `Example Logistics GmbH` und `2025` erwähnt, aber tatsächlich eine Rechnung von DL an einen dritten Empfänger beschreibt.

Wichtige Bindungszustände sind insbesondere:

- `direct` – die gesuchte Relation ist im Dokument direkt belegt,
- `reference_only` – gesuchte Entitäten/Begriffe werden nur erwähnt,
- `contradicted` – die dokumentierte Relation widerspricht der Suchhypothese,
- `unclear` – aus dem Dokument nicht belastbar entscheidbar.

### 6.3 RetrievalRecord

Optional kann pro Query ein strukturierter Datensatz archiviert werden:

```yaml
retrieval_record:
  enabled: true
  directory: "runtime/retrieval-records"
```

Der Record speichert Query, SearchSpec/QueryFrame, Verifikationsmetadaten, Dokumentreferenzen und EvidenceFrames, aber **keine vollständigen Dokumentkörper**. Er eignet sich als Audit-/Debug-Artefakt und als spätere Eingabe für eine kuratierte Graph-Erweiterung.

Die wichtigste Regel bleibt:

> QueryFrame niemals automatisch als Graph-Fakt importieren.

---

## 7. Reranking

Die Middleware unterstützt zwei Reranker-Backends:

### Lokal

```yaml
reranker:
  backend: local
  model: BAAI/bge-reranker-v2-m3
  device: cpu
```

Dies funktioniert ohne GPU, kann aber auf CPU bei größeren Cross-Encodern teuer sein.

### External TEI

```yaml
reranker:
  backend: tei
  tei_url: "http://127.0.0.1:8081"
  fallback_backend: none
```

Der TEI-Pfad lädt im RAG-Prozess keine lokalen Torch-/Transformers-Gewichte, solange kein lokaler Fallback konfiguriert ist. Das ist insbesondere für kleine CPU-only-RAG-VMs sinnvoll.

---

## 8. Live-ACL und Fail-Closed-Verhalten

Die ACL-Prüfung liegt bewusst **nach Retrieval und Ranking**. Das ermöglicht gute Suchqualität ohne ACL-Schattenindex, hält aber Nextcloud als verbindliche Quelle der Zugriffsrechte.

```text
Kandidaten:      [A, B, C, D, E]
Reranking:       [C, A, E, B, D]
Live ACL erlaubt [C, E]
Antwortkontext:  [C, E]
```

Es werden **nicht** anschließend F, G oder H nachgeladen, nur um wieder eine bestimmte Trefferzahl zu erreichen.

Dieses Verhalten hat zwei Vorteile:

1. Ein Benutzer erhält keine durch niedrigere Kandidaten künstlich „vervollständigte“ Antwort.
2. Die Tatsache, dass höher gerankte, aber gesperrte Dokumente existieren, wird nicht indirekt durch Nachrücklogik offengelegt.

---

## 9. Graph: Entity Resolution statt universeller Wahrheitsspeicher

Neo4j ist der dritte Retrieval-Pfad, nicht die primäre Dokumentenquelle.

### 9.1 Seed und Provenienz

CardDAV-Kontakte können als kuratierbarer Nucleus importiert werden. Dokumente ergänzen anschließend `Observation`-/`Claim`-/Relations-Evidence. Die Herkunft jeder Beobachtung bleibt erhalten.

### 9.2 Namen und Aliase

Formen besitzen eine `resolution_policy`:

- `exclusive` – für Query und harte Ingestion-Identitätsauflösung,
- `contextual` – für Query/Kandidaten, aber nicht für harte Dokumentauflösung,
- `search_only` – nur Query-Erweiterung,
- `document_only` – nicht als globaler Resolver exponiert.

Damit können unsichere Varianten, OCR-Fehler oder Namensformen nutzbar sein, ohne sie vorschnell als globale Identität festzuschreiben.

### 9.3 Merge/Split/Korrektur

Die CLI unterstützt bereits u. a.:

- Merge-Vorschläge,
- manuelles Merge mit Preview,
- persistentes `NOT_SAME_AS`,
- Alias- und Policy-Pflege,
- Namenskorrektur,
- Re-Zuordnung einzelner Observations oder CardDAV-Records,
- Provenienz- und Import-Run-Ansichten.

Eine komfortablere Graph-Admin-Oberfläche ist für den Freeze-/Post-Freeze-Schritt vorgesehen; die CLI ist bereits die autoritative Administrationsschicht.

### 9.4 Indirekte Beziehungen

Eine dokumentengeerdete Kette `A → C → B` darf als **indirekte Verbindung** ausgegeben werden, wenn beide Hops jeweils durch Dokumente belegt sind. Sie darf niemals in eine direkte Relation `A ↔ B` umgedeutet werden.

---

## 10. Öffentliche Web-Recherche

### 10.1 Discovery-Provider

Aktuell unterstützt der Web-Arm:

- Brave Search API,
- extern betriebenes SearXNG.

Der Search-Provider liefert zunächst nur URLs, Titel und Discovery-Metadaten. **Suchmaschinen-Snippets gelten nicht als Evidence.**

### 10.2 Evidence-Pipeline

```text
Search Provider
   -> URL-Liste
   -> echte HTTP-Abrufe
   -> Text-/PDF-Extraktion
   -> bestpassende Passage pro Seite
   -> LLM-Relevance-Gate
   -> maximal konfigurierte relevante Quellen
   -> Antwort mit [W1], [W2], ...
```

Die aktuelle Implementierung verwendet für native OpenAI-Modelle ein Strict-Structured-Output-kompatibles Relevance-Schema. Unvollständige Quellenentscheidungen werden nicht als „irrelevant“ verschluckt, sondern erneut angefordert und bei erneutem Vertragsbruch als Fehler gemeldet.

### 10.3 Explizit, gemischt oder als Fallback

Web kann genutzt werden als:

- expliziter Web-only-Arm: `/web ...`,
- Teil eines natürlich beschriebenen Workflows,
- Abgleich ausgewählter interner Dokumente mit dem Web,
- automatischer Fallback bei unzureichender interner Evidence, sofern der vertrauenswürdige Client `X-RAG-Web-Allowed: true` setzt und der Benutzer vom Admin für Web Research freigeschaltet ist.

Der automatische Fallback wird zusätzlich durch einen konservativen Web-Gate geprüft; ein interner Nulltreffer führt nicht blind zu einer externen Suchanfrage.

### 10.4 Webarchiv

Für freigeschaltete Benutzer kann jeder Web-Recherchelauf per WebDAV in Nextcloud archiviert werden:

```text
<Benutzer-Archivroot>/YYYY-MM/DD-HHMMSS-xxxx/
    recherche.md
    fetch-log.jsonl
    01-source.txt
    .01-source.metadata.json
    01-source.pdf        # Original-PDF oder optionales Playwright-Screen-PDF
    01-source.html       # optionaler HTML-Rohsnapshot
    ...
```

`recherche.md` dokumentiert Suchanfrage, Abrufzeitpunkt, verwendete Quellen, Relevance-Metadaten und nach Abschluss die LLM-Antwort. `fetch-log.jsonl` enthält **alle tatsächlich angeforderten Suchtreffer**, auch verworfene oder fehlgeschlagene Fetches, mit Original-/Final-URL, HTTP-Status, Redirect-Zahl, Content-Hash, Fetch-Ergebnis und Relevance-Entscheidung. Für jede ausgewählte Quelle wird zusätzlich eine `.metadata.json` mit Retrieval-, Relevance- und Snapshot-Metadaten geschrieben.

Ist der optionale lokale Playwright-Renderer aktiviert, werden ausgewählte HTML-Quellen zusätzlich mit einem 1440×900-Desktop-Viewport als A4-Landscape-PDF gerendert. Best-effort Consent/Overlay-Cleanup bleibt bewusst begrenzt; optionaler Browser-Storage wird pro angefordertem Host getrennt persistiert, damit gewöhnliche Cookie-Zustimmungen wiederverwendet werden können. Login-Walls, Paywalls, CAPTCHAs und Zugriffssperren werden nicht umgangen. Renderfehler sind fail-open und beeinflussen die Text-Evidence nicht. In RC2 läuft die Playwright-PDF-Erzeugung nach dem synchronen Evidenz-/Metadatenarchiv als begrenzte Hintergrundaufgabe; das Sidecar verfolgt `pending/complete/failed`. Bereits als PDF gelieferte Quellen werden unverändert archiviert und nicht erneut gerendert.

Der Raw-HTML-Snapshot ist weiterhin nur der tatsächlich abgerufene HTTP-Body der Hauptseite. Auch das Playwright-PDF ist **kein vollständiges WARC-/forensisches Browser-Capture**; es dient als visuell lesbare Momentaufnahme.

Webarchiv-Pfade werden aus der normalen internen Retrieval-Pipeline ausgeschlossen, damit archivierte Webquellen nicht später unbemerkt als unabhängige interne Quellen wieder auftauchen.

---

## 11. Datenschutz und Datenflüsse

Die Trennung von Embedding- und Answer-LLM ist ein bewusstes Datenschutzmerkmal.

### 11.1 Lokale Embeddings

Für lokale oder externe Embedding-Modelle gilt derselbe generische Vertrag. Die Referenz verwendet `qwen3-embedding:4b`; andere Ollama- oder OpenAI-kompatible Embedding-Modelle können mit expliziten Query-/Dokument-Prefixes eingesetzt werden:

- vollständige Dokumenttexte bleiben für die Vektorisierung lokal,
- Qdrant bleibt lokal,
- an ein externes Answer-LLM gehen nur die für die konkrete Anfrage notwendigen Prompts und nach ACL freigegebenen Kandidatenausschnitte.

### 11.2 Externe Embeddings

Wird `embedding.backend` auf einen externen API-Provider umgestellt, müssen alle zu indexierenden Text-Chunks an diesen Provider gesendet werden. Bei einem Vollindex entspricht das praktisch dem gesamten indexierbaren Volltextbestand. Das ist datenschutzseitig eine wesentlich größere Grenze als der selektive Answer-/Verifier-Pfad.

### 11.3 CPU-only-Betrieb

Embeddings sind nicht GPU-pflichtig. `qwen3-embedding:4b` mit 1024 Ausgabedimensionen kann auf einem CPU-only-Server über Ollama betrieben werden; die initiale Vollindexierung kann dort jedoch alle Kerne auslasten. Für den Erstlauf kann derselbe Modell-/Dimensionsstand einmalig über `rag.sync --embedding-url` auf einen GPU-Ollama umgeleitet werden; inkrementelle Folgesyncs können anschließend wieder über CPU laufen. Für einen CPU-Reranker ist ein separater TEI-Dienst eine saubere Option. Embedding- und Reranker-Dienste bleiben administratorverwaltet und können unabhängig von der Middleware skaliert werden.

---

### 11.4 Verschlüsselter Credential-Store

In `0.8.3-rc6` werden reversible Benutzer-Credentials nicht als Klartext in `runtime/users.sqlite` gespeichert. Nextcloud-App-Passwörter, IMAP-Passwörter und kurzlebige Nextcloud-Login-Flow-Poll-Tokens werden mit AES-256-GCM verschlüsselt. Der Master-Key liegt außerhalb der SQLite-Datenbank und wird auf einer Standardinstallation von `root` verwaltet; der Dienstaccount `rag` erhält ausschließlich die zum Betrieb nötige Leseberechtigung.

Die Verschlüsselung ist kontextgebunden: Authenticated Data bindet Ciphertexte an Benutzer, Service und Account. Ein aus der Datenbank kopierter Ciphertext lässt sich deshalb nicht unbemerkt einem anderen Credential-Datensatz zuordnen. Nicht reversible Trusted-Client-Keys werden weiterhin nur als Hash gespeichert.

Diese Maßnahme trennt Datenbank-/Admin-Zugriff besser vom tatsächlichen Secret-Inhalt, ist jedoch bewusst keine vollständige Isolation gegen `root` oder einen kompromittierten Dienstprozess. Globale Runtime-Secrets bleiben in diesem Release Candidate in `runtime.env`; eine spätere Ausbaustufe kann dafür systemd credentials/TPM oder einen privilegierten Secret-Helper verwenden.

## 12. Mail-Integration

Die Mail-Synchronisation ist administrativ pro kanonischem Nextcloud-Benutzer konfigurierbar. Passwörter werden getrennt nach Credential-Service gespeichert; insbesondere darf ein Mail-Passwort niemals durch ein unqualifiziertes SQL-Update denselben Nextcloud-Benutzernamen überschreiben.

**Aktueller Implementierungsstand:** Konfigurierte IMAP-Mailboxen sind rekursive Wurzeln. Der Worker ermittelt selektierbare Unterordner mit IMAP `LIST`, übernimmt den serverseitigen Hierarchietrenner und spiegelt die Struktur in Nextcloud. Jede neue Nachricht erhält einen eigenen Ordner:

```text
<target>/<account>/<mailbox-hierarchy>/<YYYY>/<MM>/
  <timestamp>_<uid>_<subject>/
    mail.txt
    .mailmeta.json
    a01_<attachment>
    ...
    message.eml          # optional; neue Konten standardmäßig store_eml=false
```

Der Sidecar enthält deterministische Metadaten für Graph-/Thread-Verarbeitung und wird nicht als normaler Retrieval-Text behandelt. Alte flache Archive bleiben lesbar, werden aber nicht automatisch umsortiert.

---

## 13. OpenWebUI

OpenWebUI ist Referenz-Frontend, nicht Bestandteil der Retrieval-Logik. Der Installer pinnt derzeit `v0.11.0` auf einen festen Image-Digest. Der Reverse Proxy reserviert:

```text
/             -> OpenWebUI, falls installiert
/rag-admin/   -> RAG-Administration
/rag-api/     -> Middleware API
/v1/          -> OpenAI-kompatibler Provider
/auth/        -> Nextcloud Login Flow
```

Ein externes OpenWebUI kann mit einem eigenen Trusted-Client-Key und dem Header

```json
{"X-OpenWebUI-User-Id":"{{USER_ID}}"}
```

angebunden werden. Für den automatischen Web-Fallback kommt optional hinzu:

```json
{"X-RAG-Web-Allowed":"true"}
```

Die gewünschte restriktive Endnutzer-Vorkonfiguration – insbesondere Abschalten von eigenem OpenWebUI-RAG, Tools/Plugins, Websuche, Update-Check, Workspaces und sonstigen Konfigurationsmöglichkeiten – ist **noch nicht vollständig in den Installer integriert**. Sie gehört zu den letzten Freeze-Arbeiten.

---

## 14. Referenzbetrieb und beobachtete Performance

In einem Live-Beta-Test mit einer Rechnungsanfrage und OpenAI GPT-5.6 Luna ergaben sich ungefähr:

```text
Query Rewrite            ~4 s
Retrieval/Rerank/ACL     ~9-10 s
Verifier                 ~5 s
Antwort                  ~3 s
Gesamt                   ~24 s
```

Der gleiche Workflow war mit lokalem Qwen3 auf der vorhandenen Hardware deutlich langsamer. Die Zahlen sind keine Benchmark-Garantie; sie zeigen aber, dass nach der Umstellung auf einen schnellen externen LLM-Provider der größte weitere Latenzhebel nicht mehr das Antwortmodell, sondern Retrieval/Hydration/ACL ist.

---

## 15. Fehler- und Unsicherheitsmodell

Die Middleware bevorzugt explizite Unsicherheit gegenüber scheinbarer Vollständigkeit:

- fehlende oder unvollständige Structured Outputs werden retried oder als Fehler behandelt,
- ACL-Denials führen nicht zu Backfill,
- indirekte Graphketten werden als indirekt markiert,
- Web-Snippets sind keine Evidence,
- nicht abrufbare Webseiten gelten nicht als Quellen,
- ein Dokument, das eine Suchentität nur erwähnt, kann als `reference_only` verworfen werden,
- fehlende Treffer werden als „in den gefundenen/vorliegenden Quellen nicht belegt“ formuliert, nicht als globale Nichtexistenzaussage.

---

## Mail- und Vektorsynchronisation im Freeze-Stand

Der Mail-Import behandelt konfigurierte IMAP-Mailboxen als rekursive Wurzeln. Selektierbare Unterordner werden mit `LIST` entdeckt und als echte Nextcloud-Hierarchie gespiegelt. Jede neue E-Mail erhält einen eigenen Ordner mit indexierbarer Textrepräsentation, verstecktem Metadaten-Sidecar, Attachments und optionalem RFC822-Original. Damit bleibt das Archiv für Benutzer und Administratoren navigierbar und zugleich maschinell eindeutig strukturiert.

Der Elasticsearch→Qdrant-Abgleich ist als eigener periodischer Worker operationalisiert. Dieser Worker implementiert keine zweite Indexlogik, sondern startet denselben zustandsbehafteten `rag.sync`, der auch manuell verwendet wird. Dadurch gelten für periodische und manuelle Läufe dieselben Chunking-, Embedding-, Update- und Löschregeln.

---

## 16. Grenzen des Release Candidates

`0.8.5-rc3` ist der erste öffentliche Release Candidate und der
aktuelle Beta-Kandidat. Der Architektur-/Deployment-Stand ist für den Beta-Betrieb
weitgehend eingefroren. Erwartete nächste Änderungen liegen primär bei Query-Rewrite, optionalen Retrieval-Runden und Retrieval-Qualität und UI-Komfort, nicht bei einer erneuten Aufteilung
des Stacks.

Die in 0.8.5 bewusst verbleibenden Grenzen sind in `KNOWN-LIMITATIONS.md` gesammelt.
Wesentlich sind: nur die Kombinationen `standard+native` und
`super-light+dockerized` sind als Deploymentpfade freigegeben; der Kontakt-Sync hat
die Installer-CA-Datei wird noch nicht als allererste
Preflight-Prüfung validiert; Web-PDFs sind best-effort Research-Snapshots und kein
WARC/WACZ-Archiv.

Nicht Bestandteil dieses Release Candidates sind ein vollständiger Browser-/WARC-Crawler,
eine unkontrollierte automatische QueryFrame-zu-Global-Fact-Übernahme oder ein frei
programmierbarer LLM-Workflow.

---

## 17. Schlussfolgerung

Die aktuelle Middleware trennt vier Aufgaben, die in vielen RAG-Systemen unnötig vermischt werden:

1. **Kandidaten finden** – Elasticsearch, Qdrant, Neo4j, Web Search,
2. **Zugriff autorisieren** – ausschließlich Nextcloud für private Dokumente,
3. **Evidenz verifizieren** – dokumentengeerdete Verifier/Relevance-Gates,
4. **Antwort formulieren** – LLM auf freigegebener und geprüfter Evidence.

Diese Trennung ist der zentrale Architekturwert des Systems. Sie erlaubt den Austausch einzelner Modelle und Provider, ohne die Sicherheits- oder Provenienzlogik neu zu erfinden, und verhindert zugleich, dass semantische Ähnlichkeit oder ein Wissensgraph fälschlich als Berechtigung oder Wahrheit interpretiert werden.

## Role routing and private retrieval plane

The LLM path is no longer a single implicit backend. Planner, candidate
verifier, evidence control and final answer generation can inherit the default
backend or override it independently. This makes the trust boundary explicit:
full-corpus retrieval, embeddings, vector storage, reranking and live ACL can
remain local while selected evidence is processed by a remote model.

Remote roles are subject to hard evidence budgets. Graph extraction is excluded
from that normal evidence path because it may inspect substantially larger
portions of a document; its backend remains separately configured and automatic
graph processing is disabled by default in the current reference configuration. See
`PRIVACY-ARCHITECTURE.md` for the normative deployment model.

## RC10: AKI-Recherche-Findings – bereits geleistete Semantik wiederverwenden

RC10 führt **keinen weiteren Graphisierungs-Lauf** für erfolgreiche Recherchen ein. Der Query Rewriter erzeugt den SearchSpec; daraus wird für Provenienz/Verifier ein kompatibler `query_frame` (Intent, Entities/Rollen, Constraints, Concepts) abgeleitet. Der Candidate-Verifier erzeugt für geprüfte Dokumente einen `evidence_frame` und entscheidet `match` / `uncertain` / `reject` sowie die Dokumentbindung.

Nur positive Treffer mit `verification_status=match` und `relation_binding=direct` werden als `ResearchFinding:AKIResearchFinding` persistiert. Unsichere und abgelehnte Kandidaten werden nicht gespeichert. Das Finding verweist über `SUPPORTED_BY` auf das Dokument und trägt die Provenienz `AKI Recherche` sowie Query-Rewriter-/Verifier-Versionen. Query-Frame-Relationen bleiben Beobachtungsdaten des Findings und werden **nicht** automatisch zu globalen Entity-Relationen.

Existierende CardDAV-/kuratierte Entities können über `QUERY_ENTITY` verlinkt werden, aber ausschließlich bei eindeutigem exaktem Query-Form-/Alias-Treffer. Es werden durch diesen Pfad keine neuen Entities, Aliase oder Merge-Entscheidungen erzeugt. Wiederholte gleichartige Recherchen koaleszieren anhand eines kanonischen Frame-Hashes plus Dokument-ID; dadurch wächst der Graph mit bestätigter Nutzung statt mit negativen Suchpaaren.

Der Pfad ist bewusst fail-open und leichtgewichtig:

```text
query -> query rewrite/SearchSpec + Neo4j seed expansion -> ES [+ Qdrant] -> fusion/rerank -> live ACL
      -> candidate verifier (positive match + evidence_frame)
      -> answer path
      -> batch write: AKI Recherche finding -> Neo4j
```

Es gibt keinen zusätzlichen Modellaufruf. Die Konfiguration erfolgt über `research_findings.enabled`; bei deaktiviertem oder nicht erreichbarem Neo4j bleibt die Benutzerantwort unverändert verfügbar.


## 0.8.4 Packaging: Funktionsprofil und Deployment-Modus

Die Middleware-Codebasis ist unabhängig von der Verpackung. Zwei Achsen sind zu
unterscheiden:

- **Funktionsprofil:** welche Retrieval-/Graph-/UI-Fähigkeiten aktiviert sind
  (`standard`, `super-light`, perspektivisch weitere Profile).
- **Deployment-Modus:** wie API/Provider und Hilfsdienste betrieben werden
  (`native` oder `dockerized`).

0.8.4 unterstützt und testet `standard + native` und `super-light + dockerized`.
Bei `super-light + dockerized` laufen API und Provider im selben Python-Image;
Neo4j und Playwright sind ebenfalls Container, während Nextcloud/Elasticsearch
und das LLM externe Dienste bleiben. Das ist eine Installationsvariante, kein
Fork. Die Trennung erlaubt später beispielsweise `standard + dockerized`, ohne
Retrieval-/ACL-/Query-Rewrite-Code zu duplizieren.

## Policy between query understanding and execution

The normal retrieval contract is intentionally small:

```text
Query Rewriter -> SearchSpec
       + Neo4j seed/alias expansion
       -> Elasticsearch + optional Qdrant
       -> fusion / dedup / optional reranker
       -> live ACL / optional verifier
```

The LLM does not choose backend syntax or invent retrieval-arm workflows. Administrator policy decides which implemented arms are available; normal automatic retrieval uses `files` plus optional `vector`, while Neo4j participates in entity/alias expansion. Explicit user directives can still request supported diagnostic/specialized arms.

Retrieval rounds remain an optional outer controller. A later round may emit a revised SearchSpec after seeing the bounded result picture, but it runs through the exact same retrieval pipeline. Round counts, candidate budgets, verifier limits and backend enablement remain deterministic configuration.

### RC3 Findings / Graph-Lite boundary

Research Findings preserve verified query/evidence frames and supporting-document provenance. Administrators may manually resolve finding entities into document-grounded mentions and may create document-grounded RelationObservation claims. **Findings and Claims are deliberately not retrieval edges in RC3**: there is no automatic promotion into global Entity relations or alias/query-expansion structures.

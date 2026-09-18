#!/bin/bash
# SPDX-FileCopyrightText: 2026 Eboracum GmbH
# SPDX-License-Identifier: AGPL-3.0-only

#
# nextcloud-eml.sh
#
# Zerlegt eine per Nextcloud angelieferte RFC822-/EML-Datei in:
#   - Original-EML
#   - Textdarstellung
#   - ggf. HTML-MIME-Part als PDF (HTML bleibt nur temporaer)
#   - extrahierte Anlagen
#   - Readme.md
#   - .mailmeta.json mit strukturierten Mail-/Thread-Metadaten
#
# Danach werden die erzeugten Dateien Nextcloud bekannt gemacht und
# optional der FullTextSearch-Index aktualisiert.
#
# Bewusst konservativ überarbeitet:
# - Dateistruktur und grundsätzlicher Ablauf bleiben erhalten.
# - Kein "set -e": einzelne Werkzeuge dürfen weiterhin kontrolliert fehlschlagen.
# - Historisch vorhandener doppelter fulltextsearch:index-Aufruf bleibt
#   standardmäßig aktiv, kann aber unten abgeschaltet werden.
#

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

MakeOcr=True
MakeHTML2Pdf=True
MakeMailMeta=True

# Historisch wurden zwei fulltextsearch:index-Aufrufe ausgeführt:
#   1. nur mit path
#   2. mit user + path
# Da unklar ist, ob der erste auf der alten Installation noch eine Sonderfunktion
# erfüllt, bleibt dieses Verhalten zunächst erhalten.
# Auf False setzen, wenn nach Test nur der benutzerspezifische Aufruf benötigt wird.
RunLegacyPathOnlyFtsIndex=True

occPfad="/srv/www/htdocs/nextcloud"
DataPfad="/srv/www/htdocs/nextcloud/data"
LogFile="$DataPfad/nextcloud-convertmails.txt"

# ---------------------------------------------------------------------------
# Laufzeit / Logging
# ---------------------------------------------------------------------------

Start=$(date +%s%N)

log()
{
    printf '%s@%s %s\n' "$$" "$(date +%H:%M:%S)" "$*" >> "$LogFile"
}

die()
{
    log "$*"
    exit 1
}

# ---------------------------------------------------------------------------
# Mountpoint für Gruppenordner
# ---------------------------------------------------------------------------

mountPointFunction()
{
    case "$NGOrdnerNr" in
        1)
            NMountPoint="${NEXTCLOUD_GROUPFOLDER_1_NAME:-}"
            [ -n "$NMountPoint" ] || die "NEXTCLOUD_GROUPFOLDER_1_NAME ist nicht gesetzt"
            log "MountPoint: $NMountPoint"
            ;;
        *)
            die "MountPoint für Gruppenordner '$NGOrdnerNr' nicht gefunden"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# Hilfe
# ---------------------------------------------------------------------------

helpFunction()
{
    cat <<EOF

Usage: $0 -f Dateiname -o User -n Nextcloud-Pfad

  -f  Systempfad der Datei
  -o  Owner / Nextcloud-Benutzer
  -n  Nextcloud-Pfad der Datei

EOF
    exit 1
}

# ---------------------------------------------------------------------------
# Parameter
# ---------------------------------------------------------------------------

while getopts "f:o:n:" opt
do
    case "$opt" in
        f) NFile="$OPTARG" ;;
        o) NUser="$OPTARG" ;;
        n) NDFile="$OPTARG" ;;
        *) helpFunction ;;
    esac
done

if [ -z "${NFile:-}" ] || [ -z "${NUser:-}" ] || [ -z "${NDFile:-}" ]
then
    log "Dateiname, Eigentümer oder Nextcloud-Pfad fehlt"
    helpFunction
fi

printf 'Hallo, dies ist %s (pid %s) am %s\n' "$0" "$$" "$(date)" >> "$LogFile"
log "Parameter: $*"

Pfad=$(dirname -- "$NFile")
Datei=$(basename -- "$NFile")
NDPfad=$(dirname -- "$NDFile")

log "Pfad in NC: $NDPfad"

# ---------------------------------------------------------------------------
# Nextcloud-Pfad bestimmen
# ---------------------------------------------------------------------------
#
# Gruppenordner können in älteren Nextcloud-Versionen problematisch sein.
# Die bestehende Pfadlogik wird bewusst beibehalten.
#

if [[ "$Pfad" == "$DataPfad"* ]]
then
    log "Liegt im Datenpfad"

    PruefungGO="__groupfolders/"
    log "Prüfe Gruppenordner: $PruefungGO"

    if [[ "$NDPfad" == "$PruefungGO"* ]]
    then
        log "Gruppenordner"

        NGPfad=${NDPfad:${#PruefungGO}}
        log "Nextcloud Gruppen-Pfad: $NGPfad"

        NGOrdnerNr=${NGPfad%%/*}
        log "OrdnerNummer: $NGOrdnerNr"

        mountPointFunction

        # NC 20:
        # NAbsPfad="$NUser/files/$NMountPoint${NGPfad:${#NGOrdnerNr}}"
        #
        # NC 23: historisch verwendete Variante:
        NAbsPfad=${NGPfad:${#NGOrdnerNr}}
        log "Nextcloud absoluter Pfad: $NAbsPfad"
    else
        log "Kein Gruppenordner"

        NAbsPfad=${Pfad:${#DataPfad}}
        log "Nextcloud absoluter Pfad: $NAbsPfad"
    fi
else
    die "Liegt nicht im Datenpfad; beende"
fi

# ---------------------------------------------------------------------------
# Quelldatei prüfen
# ---------------------------------------------------------------------------

if [ ! -e "$NFile" ]
then
    die "File nicht vorhanden: $NFile"
fi

log "File vorhanden"

MimeType=$(file -b --mime-type -- "$NFile" 2>>"$LogFile")

if [ "$MimeType" = "message/rfc822" ]
then
    log "Email erkannt (MIME: $MimeType)"
else
    die "Keine Email (MIME: ${MimeType:-unbekannt}); beende"
fi

# ---------------------------------------------------------------------------
# Maildatum
# ---------------------------------------------------------------------------

EmailDatumOriginal=$(formail -x Date < "$NFile" 2>>"$LogFile")
log "Email Datum Original: $EmailDatumOriginal"

if EmailDatum=$(date -d "$EmailDatumOriginal" +%Y-%m-%d-%H%M%S 2>>"$LogFile")
then
    log "Email Datum konvertiert: $EmailDatum"
else
    # Fallback: besser ein reproduzierbarer lokaler Timestamp als ein Abbruch.
    EmailDatum=$(date +%Y-%m-%d-%H%M%S)
    log "WARNUNG: Email-Datum nicht interpretierbar; verwende aktuellen Timestamp: $EmailDatum"
fi

# Technische Thread-Metadaten einmal auslesen. Die kanonische maschinenlesbare
# Fassung wird spaeter mit Python direkt aus der EML in .mailmeta.json erzeugt.
# Diese Variablen dienen nur der menschenlesbaren Readme.md.
MessageId=$(formail -x Message-ID < "$NFile" 2>/dev/null | tr '\n\t' '  ' | tr -s ' ' | sed -E 's/^ +| +$//g')
InReplyTo=$(formail -x In-Reply-To < "$NFile" 2>/dev/null | tr '\n\t' '  ' | tr -s ' ' | sed -E 's/^ +| +$//g')
ReferencesHeader=$(formail -x References < "$NFile" 2>/dev/null | tr '\n\t' '  ' | tr -s ' ' | sed -E 's/^ +| +$//g')

# ---------------------------------------------------------------------------
# Dateiname / Ordnername bereinigen
# ---------------------------------------------------------------------------

# Nur die Endung .eml entfernen, nicht jedes Vorkommen von "eml" im Namen.
NDateiS=${Datei%.[eE][mM][lL]}

# Sonderzeichen durch Leerzeichen ersetzen, Klammer-/Bracket-Reste wie bisher kappen.
NDateiS=$(printf '%s' "$NDateiS" \
    | sed -E 's/[<>@,:!§$%&\/(){}"'\'' ]/ /g' \
    | sed 's/\[.*$//g' \
    | sed -E 's/\(.*$//g' \
    | sed 's/\.//g' \
    | tr -s ' ' \
    | sed -E 's/^ +| +$//g; s/ +/-/g')

if [ -z "$NDateiS" ]
then
    NDateiS="mail"
fi

NOrdnerS="${EmailDatum}-Email-${NDateiS}"

# Dateiname kappen wie bisher
NOrdnerS=${NOrdnerS:0:100}

log "Neuer Name: $NDateiS"
log "Neuer Ordner: $NOrdnerS"

# ---------------------------------------------------------------------------
# Verzeichnisse anlegen
# ---------------------------------------------------------------------------

NOrdner="$Pfad/$NOrdnerS"
NArbOrdner="$NOrdner/tmp"

if [ -e "$NOrdner" ]
then
    die "Ordner bereits vorhanden: $NOrdner"
fi

log "Ordner nicht vorhanden, lege an"

if ! mkdir -- "$NOrdner" 2>>"$LogFile"
then
    die "Konnte Ordner nicht anlegen: $NOrdner"
fi

if ! mkdir -- "$NArbOrdner" 2>>"$LogFile"
then
    die "Konnte Arbeitsordner nicht anlegen: $NArbOrdner"
fi

# ---------------------------------------------------------------------------
# Anhänge extrahieren
# ---------------------------------------------------------------------------

log "Extrahiere Anlagen"

if ! mu extract --target-dir="$NOrdner" -a "$NFile" 2>>"$LogFile"
then
    log "WARNUNG: mu extract -a meldete einen Fehler"
fi

# ---------------------------------------------------------------------------
# OCR für PDFs
# ---------------------------------------------------------------------------

if [ "$MakeOcr" = "True" ]
then
    OcrStart=$(date +%s%N)
    log "OCR aktiviert"

    # -print0: robust auch bei Leerzeichen und Sonderzeichen in Dateinamen.
    while IFS= read -r -d '' line
    do
        log "Pdf-Datei gefunden: $line"

        # Für jede PDF eine eigene temporäre Datei verwenden.
        # Dadurch können Reste eines vorherigen Fehlers nicht übernommen werden.
        TmpPdf="$NArbOrdner/ocr-$(printf '%s' "$line" | sha256sum | cut -d' ' -f1).pdf"
        rm -f -- "$TmpPdf"

        # --skip-text: bereits durchsuchbare Seiten nicht unnötig OCRen.
        if ocrmypdf --skip-text "$line" "$TmpPdf" >>"$LogFile" 2>&1
        then
            if [ -s "$TmpPdf" ]
            then
                if mv -- "$TmpPdf" "$line" 2>>"$LogFile"
                then
                    log "OCR erfolgreich: $line"
                else
                    log "WARNUNG: OCR-Datei konnte Original nicht ersetzen: $line"
                    rm -f -- "$TmpPdf"
                fi
            else
                log "WARNUNG: OCR-Ergebnis ist leer: $line"
                rm -f -- "$TmpPdf"
            fi
        else
            log "WARNUNG: OCR fehlgeschlagen: $line"
            rm -f -- "$TmpPdf"
        fi

    done < <(find "$NOrdner" -type f -iname '*.pdf' -print0)

    OcrEnde=$(date +%s%N)
else
    log "Kein OCR"
fi

# ---------------------------------------------------------------------------
# Email-Text schreiben
# ---------------------------------------------------------------------------

log "Schreibe Email-Body"

EmailText="${EmailDatum}-Text-${NDateiS}.txt"

if ! mu view "$NFile" > "$NOrdner/$EmailText" 2>>"$LogFile"
then
    log "WARNUNG: mu view konnte Textdarstellung nicht vollständig erzeugen"
fi

# MIME-Inhalte der Mail listen
if ! mu extract "$NFile" > "$NArbOrdner/Inhalt.txt" 2>>"$LogFile"
then
    log "WARNUNG: mu extract konnte MIME-Inhaltsliste nicht erzeugen"
    : > "$NArbOrdner/Inhalt.txt"
fi

# Erfolgreich erzeugte PDFs aus HTML-MIME-Parts werden hier fuer .mailmeta.json
# gesammelt. Ein Dateiname pro Zeile; die eigentlichen HTML-Dateien bleiben im tmp.
HtmlPdfList="$NArbOrdner/html-pdf-files.txt"
: > "$HtmlPdfList"

# ---------------------------------------------------------------------------
# HTML-Teile extrahieren
# ---------------------------------------------------------------------------
#
# Sicherheits-/Archivierungsprinzip:
# - HTML-MIME-Parts werden nur in den temporaeren Arbeitsordner extrahiert.
# - Falls aktiviert, werden sie dort durch LibreOffice in PDF gerendert.
# - Im Nextcloud-Zielordner bleibt niemals eine vom Skript erzeugte HTML-Datei.
# - Bei Konvertierungsfehlern bleibt die Information weiterhin in der Original-EML.
#

while IFS= read -r line
do
    if printf '%s\n' "$line" | grep -q 'text/html'
    then
        # Nicht nur das erste Zeichen nehmen: MIME-Part 10, 11, ... muss funktionieren.
        MailPart=${line%% *}

        if ! [[ "$MailPart" =~ ^[0-9]+$ ]]
        then
            log "WARNUNG: Konnte MIME-Part nicht bestimmen: $line"
            continue
        fi

        EmailHtml="${EmailDatum}-HTML-${MailPart}-${NDateiS}"
        log "Extrahiere HTML-Part $MailPart (nur temporaer)"

        if mu extract --target-dir="$NArbOrdner" --parts="$MailPart" "$NFile" 2>>"$LogFile"
        then
            MsgPart="$NArbOrdner/$MailPart.msgpart"
            HtmlFile="$NArbOrdner/$EmailHtml.html"

            if [ -e "$MsgPart" ]
            then
                if ! mv -- "$MsgPart" "$HtmlFile" 2>>"$LogFile"
                then
                    log "WARNUNG: HTML-MIME-Part konnte nicht umbenannt werden: $MsgPart"
                    continue
                fi

                if [ "$MakeHTML2Pdf" = "True" ]
                then
                    log "Wandle HTML-Email in Pdf um"

                    if soffice \
                        --headless \
                        --norestore \
                        --writer \
                        --convert-to pdf \
                        "$HtmlFile" \
                        --outdir "$NOrdner" \
                        >>"$LogFile" 2>&1
                    then
                        HtmlPdf="$NOrdner/$EmailHtml.pdf"
                        if [ -s "$HtmlPdf" ]
                        then
                            printf '%s\n' "$(basename -- "$HtmlPdf")" >> "$HtmlPdfList"
                            log "HTML->PDF erfolgreich: $HtmlPdf"
                        else
                            log "WARNUNG: HTML->PDF meldete Erfolg, aber PDF fehlt/ist leer: $HtmlPdf"
                        fi
                    else
                        log "WARNUNG: HTML->PDF fehlgeschlagen: $HtmlFile"
                    fi
                else
                    log "HTML->PDF deaktiviert; HTML-Part wird nach Verarbeitung verworfen"
                fi

                # HtmlFile liegt im tmp und wird spaeter ohnehin geloescht. Explizites
                # Entfernen reduziert die Zeit, in der aktives HTML auf Platte liegt.
                rm -f -- "$HtmlFile" 2>>"$LogFile"
            else
                log "WARNUNG: Erwarteter HTML-MIME-Part fehlt: $MsgPart"
            fi
        else
            log "WARNUNG: HTML-Part $MailPart konnte nicht extrahiert werden"
        fi
    fi
done < "$NArbOrdner/Inhalt.txt"

# ---------------------------------------------------------------------------
# Readme.md
# ---------------------------------------------------------------------------

log "Anlegen von $NOrdner/Readme.md"

Readme="$NOrdner/Readme.md"

{
    # Strukturierte Marker für Suche/RAG; bestehende menschenlesbare Struktur bleibt.
    echo "CONTENT-KIND: EMAIL"

    if [ -n "$MessageId" ]
    then
        echo "MESSAGE-ID: $MessageId"
    fi
    if [ -n "$InReplyTo" ]
    then
        echo "IN-REPLY-TO: $InReplyTo"
    fi
    if [ -n "$ReferencesHeader" ]
    then
        echo "REFERENCES: $ReferencesHeader"
    fi

    echo

    # Bisher standen die ersten fünf Zeilen der mu-Textdarstellung hier.
    # Das bleibt als Fallback erhalten.
    if [ -s "$NOrdner/$EmailText" ]
    then
        head -5 "$NOrdner/$EmailText"
    else
        formail -X From: -X To: -X Cc: -X Subject: -X Date: < "$NFile"
    fi

    echo
    echo "Originaldatei: $Datei"
    echo

    cat "$NArbOrdner/Inhalt.txt"

    echo
    echo "Datei angelegt am $(date)"
    echo "von $0"
    echo

    if [ "$MakeOcr" = "True" ]
    then
        OcrTime=$(( (OcrEnde - OcrStart) / 1000000 ))
        echo "Laufzeit OCR: $OcrTime ms"
        echo
    fi

    ZwischenEnde=$(date +%s%N)
    ZwischenRuntime=$(( (ZwischenEnde - Start) / 1000000 ))
    echo "Gesamtlaufzeit bis Readme: $ZwischenRuntime ms"

} > "$Readme"

# ---------------------------------------------------------------------------
# .mailmeta.json
# ---------------------------------------------------------------------------
#
# Der Sidecar ist die maschinenlesbare Schnittstelle fuer RAG/Graph.
# Python wird nur fuer RFC822-/Header-Decoding und korrektes JSON-Escaping genutzt.
# Ein Fehler hier ist absichtlich nicht fatal: Mail, Text, PDFs und Readme bleiben erhalten.
#

MailMeta="$NOrdner/.mailmeta.json"

if [ "$MakeMailMeta" = "True" ]
then
    if command -v python3 >/dev/null 2>&1
    then
        log "Erzeuge .mailmeta.json"

        if ! MAILMETA_EML="$NFile" \
            MAILMETA_DIR="$NOrdner" \
            MAILMETA_EML_NAME="$Datei" \
            MAILMETA_TEXT="$EmailText" \
            MAILMETA_README="$(basename -- "$Readme")" \
            MAILMETA_HTML_PDF_LIST="$HtmlPdfList" \
            MAILMETA_OUTPUT="$MailMeta" \
            python3 - <<'PYMAILMETA' >>"$LogFile" 2>&1
import json
import os
import re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

eml_path = Path(os.environ["MAILMETA_EML"])
out_dir = Path(os.environ["MAILMETA_DIR"])
out_path = Path(os.environ["MAILMETA_OUTPUT"])
text_name = os.environ.get("MAILMETA_TEXT", "")
readme_name = os.environ.get("MAILMETA_README", "Readme.md")
eml_name = os.environ.get("MAILMETA_EML_NAME", eml_path.name)
html_pdf_list_path = Path(os.environ.get("MAILMETA_HTML_PDF_LIST", ""))

with eml_path.open("rb") as fh:
    msg = BytesParser(policy=policy.default).parse(fh)

def header(name):
    value = msg.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None

def msg_ids(value):
    if not value:
        return []
    ids = re.findall(r"<[^<>]+>", value)
    if ids:
        return ids
    # Fallback fuer nicht RFC-konforme Header: Inhalt erhalten statt verwerfen.
    value = value.strip()
    return [value] if value else []

def addresses(name):
    values = msg.get_all(name, [])
    result = []
    for display, address in getaddresses([str(v) for v in values]):
        if not display and not address:
            continue
        result.append({
            "name": display or None,
            "address": address or None,
        })
    return result

date_raw = header("Date")
date_iso = None
if date_raw:
    try:
        date_iso = parsedate_to_datetime(date_raw).isoformat()
    except Exception:
        pass

html_pdfs = []
if html_pdf_list_path.is_file():
    for line in html_pdf_list_path.read_text(encoding="utf-8", errors="replace").splitlines():
        name = line.strip()
        if name and name not in html_pdfs:
            html_pdfs.append(name)

# Alles, was bereits im Zielordner liegt und keine vom Skript erzeugte
# Repräsentation ist, behandeln wir als extrahierte Anlage. Die Original-EML
# wird erst nach diesem Schritt in den Ordner verschoben.
generated = {text_name, readme_name, ".mailmeta.json", *html_pdfs}
attachments = []
for path in sorted(out_dir.iterdir(), key=lambda p: p.name.lower()):
    if not path.is_file():
        continue
    if path.name in generated:
        continue
    attachments.append(path.name)

meta = {
    "schema": "nextcloud-mailmeta-v1",
    "content_kind": "email",
    "headers": {
        "message_id": header("Message-ID"),
        "in_reply_to": msg_ids(header("In-Reply-To")),
        "references": msg_ids(header("References")),
        "date_raw": date_raw,
        "date_iso": date_iso,
        "subject": header("Subject"),
        "from": addresses("From"),
        "to": addresses("To"),
        "cc": addresses("Cc"),
        "bcc": addresses("Bcc"),
        "reply_to": addresses("Reply-To"),
    },
    "files": {
        "eml": eml_name,
        "text": text_name or None,
        "html_pdf": html_pdfs,
        "readme": readme_name,
        "attachments": attachments,
    },
    "generator": {
        "name": "nextcloud-eml-cleaned.sh",
        "mailmeta_schema": 1,
    },
}

tmp = out_path.with_suffix(out_path.suffix + ".tmp")
tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(out_path)
PYMAILMETA
        then
            log "WARNUNG: .mailmeta.json konnte nicht erzeugt werden"
            rm -f -- "$MailMeta" "$MailMeta.tmp" 2>>"$LogFile"
        fi
    else
        log "WARNUNG: python3 nicht gefunden; .mailmeta.json wird nicht erzeugt"
    fi
else
    log ".mailmeta.json deaktiviert"
fi

# ---------------------------------------------------------------------------
# Temporären Arbeitsordner löschen
# ---------------------------------------------------------------------------

log "Lösche tmp Ordner: $NArbOrdner"
rm -rf -- "$NArbOrdner" 2>>"$LogFile"

# ---------------------------------------------------------------------------
# EML-Datei in den erzeugten Mailordner verschieben
# ---------------------------------------------------------------------------

log "Verschiebe Original-EML nach $NOrdner"

if ! mv -- "$NFile" "$NOrdner/" 2>>"$LogFile"
then
    die "Original-EML konnte nicht in den Zielordner verschoben werden"
fi

# ---------------------------------------------------------------------------
# Nextcloud Files-Cache aktualisieren
# ---------------------------------------------------------------------------

log "Scanne Elternpfad shallow: $NAbsPfad"

if ! php "$occPfad/occ" files:scan -p "$NAbsPfad" --shallow >>"$LogFile" 2>&1
then
    log "WARNUNG: files:scan --shallow meldete einen Fehler für $NAbsPfad"
fi

log "Scanne neuen Mailordner: $NAbsPfad/$NOrdnerS"

if ! php "$occPfad/occ" files:scan -p "$NAbsPfad/$NOrdnerS" >>"$LogFile" 2>&1
then
    log "WARNUNG: files:scan meldete einen Fehler für $NAbsPfad/$NOrdnerS"
fi

# ---------------------------------------------------------------------------
# FullTextSearch aktualisieren
# ---------------------------------------------------------------------------
#
# Historische Pfadlogik bewusst beibehalten.
# Für normale Benutzerpfade wird "/<user>/files/" abgeschnitten.
# Gruppenordner sollten bei einer späteren Modernisierung separat getestet werden.
#

NPrefix="/$NUser/files/"

if [[ "$NAbsPfad" == "$NPrefix"* ]]
then
    NSPfad=${NAbsPfad:${#NPrefix}}
else
    # Historisch konnte NAbsPfad bei Gruppenordnern anders aufgebaut sein.
    # Nichts blind abschneiden; den vorhandenen Wert verwenden.
    NSPfad=${NAbsPfad#/}
    log "WARNUNG: NAbsPfad beginnt nicht mit '$NPrefix'; verwende FTS-Pfad '$NSPfad'"
fi

FtsPfad="$NSPfad/$NOrdnerS"

log "Indexiere Elastic-Pfad: $FtsPfad"

if [ "$RunLegacyPathOnlyFtsIndex" = "True" ]
then
    log "FTS Legacy-Aufruf nur mit path"

    if ! php "$occPfad/occ" fulltextsearch:index \
        "{\"path\":\"$FtsPfad\"}" >>"$LogFile" 2>&1
    then
        log "WARNUNG: Legacy fulltextsearch:index meldete einen Fehler"
    fi
fi

log "FTS-Aufruf mit user + path"

if ! php "$occPfad/occ" fulltextsearch:index \
    "{\"user\":\"$NUser\",\"path\":\"$FtsPfad\"}" >>"$LogFile" 2>&1
then
    log "WARNUNG: fulltextsearch:index mit user+path meldete einen Fehler"
fi

# ---------------------------------------------------------------------------
# Ende
# ---------------------------------------------------------------------------

End=$(date +%s%N)
Runtime=$(( (End - Start) / 1000000 ))

log "Laufzeit: $Runtime ms"
exit 0

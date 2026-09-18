import re


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Silbentrennung über Zeilenende konservativ entfernen
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Einzelne Zeilenumbrüche in Leerzeichen umwandeln,
    # Absatzgrenzen erhalten
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    # Mehrfache Leerzeichen reduzieren
    text = re.sub(r"[ \t]+", " ", text)

    # Mehr als zwei Leerzeilen reduzieren
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def chunk_text(
    text: str,
    chunk_size: int = 3000,
    overlap: int = 400,
) -> list[str]:

    text = normalize_text(text)

    chunks = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))

        # möglichst an Absatz/Satzende schneiden
        if end < len(text):
            search_start = max(start, end - 500)
            candidates = [
                text.rfind("\n\n", search_start, end),
                text.rfind(". ", search_start, end),
            ]
            cut = max(candidates)

            if cut > start:
                end = cut + 1

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(end - overlap, start + 1)

    return chunks

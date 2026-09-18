"""Conservative source-date inference for evidence documents.

The goal is to separate technical file/upload timestamps from the likely date
of the source content.  v0.7 deliberately keeps this lightweight and
explainable: only explicit textual/filename dates are accepted.  Technical
metadata is *not* promoted to source_date.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
import re
from typing import Any


@dataclass(frozen=True)
class SourceDate:
    value: str = ""
    precision: str = ""   # day | month | year
    confidence: float = 0.0
    basis: str = ""       # explicit_header | explicit_text | filename
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_MONTHS = {
    "januar": 1, "jan": 1,
    "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mrz": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}

_ISO_RE = re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])(?!\d)")
_DMY_RE = re.compile(r"(?<!\d)(0?[1-9]|[12]\d|3[01])[.\-/](0?[1-9]|1[0-2])[.\-/]((?:19|20)?\d{2})(?!\d)")
_GERMAN_RE = re.compile(
    r"(?<!\d)(0?[1-9]|[12]\d|3[01])\.?\s+"
    r"(Januar|Jan\.?|Februar|Feb\.?|März|Maerz|Mrz\.?|April|Apr\.?|Mai|Juni|Jun\.?|Juli|Jul\.?|August|Aug\.?|September|Sept?\.?|Oktober|Okt\.?|November|Nov\.?|Dezember|Dez\.?)"
    r"\s+((?:19|20)\d{2})(?!\d)",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_HEADER_CUE_RE = re.compile(
    r"(?:^|\n)\s*(?:date|datum|dokumentdatum|vertragsdatum|beschlussdatum)\s*:\s*$",
    re.IGNORECASE,
)
_PLACE_DATE_RE = re.compile(r"\b(?:den\s+)?$", re.IGNORECASE)


def _year(value: str) -> int:
    n = int(value)
    if n < 100:
        n += 2000 if n <= 69 else 1900
    return n


def _valid(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _line_at(text: str, start: int, end: int) -> str:
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    if right < 0:
        right = len(text)
    return text[left:right].strip()[:240]


def _context_before(text: str, start: int, chars: int = 80) -> str:
    return text[max(0, start - chars):start]


def _candidate_from_match(text: str, match: re.Match[str], kind: str) -> SourceDate | None:
    if kind == "iso":
        y, m, d = map(int, match.groups())
    elif kind == "dmy":
        d = int(match.group(1)); m = int(match.group(2)); y = _year(match.group(3))
    else:
        d = int(match.group(1))
        month_name = re.sub(r"[.]", "", match.group(2)).casefold().replace("ä", "ä")
        month_name = {"märz": "märz", "maerz": "maerz"}.get(month_name, month_name)
        m = _MONTHS.get(month_name)
        y = int(match.group(3))
        if not m:
            return None
    value = _valid(y, m, d)
    if not value:
        return None

    before = _context_before(text, match.start(), 120)
    line = _line_at(text, match.start(), match.end())
    header = bool(re.search(r"(?:date|datum|dokumentdatum|vertragsdatum|beschlussdatum)\s*:\s*[^\n]{0,40}$", before, re.I))
    place_style = bool(re.search(r"(?:,|\bden)\s*$", before, re.I))
    early = match.start() < 3500
    if header:
        conf, basis = 0.98, "explicit_header"
    elif place_style and early:
        conf, basis = 0.94, "explicit_text"
    elif early:
        conf, basis = 0.80, "explicit_text"
    else:
        conf, basis = 0.64, "explicit_text"
    return SourceDate(value, "day", conf, basis, line)


def infer_source_date(*, title: str = "", text: str = "") -> SourceDate:
    """Return the most plausible explicit source date, or an empty result.

    We intentionally do not use file creation/modification timestamps here.
    A newly scanned ten-year-old document must therefore remain old if its
    content/filename says so, and unknown if the content does not expose a date.
    """
    text = str(text or "")
    title = str(title or "")
    filename = title.replace("\\", "/").rsplit("/", 1)[-1]
    candidates: list[SourceDate] = []

    # Inspect beginning and end; signatures/footers can contain source dates,
    # but the beginning receives a higher confidence inside _candidate_from_match.
    sample = text if len(text) <= 30000 else text[:18000] + "\n" + text[-8000:]
    for regex, kind in ((_ISO_RE, "iso"), (_DMY_RE, "dmy"), (_GERMAN_RE, "german")):
        for match in regex.finditer(sample):
            candidate = _candidate_from_match(sample, match, kind)
            if candidate:
                candidates.append(candidate)

    # Filenames/path titles commonly encode YYYY-MM-DD and are a good fallback,
    # but are weaker than an explicit document header.
    for regex, kind in ((_ISO_RE, "iso"), (_DMY_RE, "dmy"), (_GERMAN_RE, "german")):
        for match in regex.finditer(filename):
            candidate = _candidate_from_match(filename, match, kind)
            if candidate:
                candidates.append(SourceDate(candidate.value, "day", 0.88, "filename", candidate.evidence))

    if candidates:
        # Strongest evidence first; for ties prefer earliest textual occurrence
        # implicitly by stable sort/insertion order.
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[0]

    # Only accept a bare year when the title itself strongly looks dated.
    years = list(_YEAR_RE.finditer(filename))
    if len(years) == 1:
        year = years[0].group(1)
        return SourceDate(year, "year", 0.62, "filename", _line_at(filename, years[0].start(), years[0].end()))

    return SourceDate()

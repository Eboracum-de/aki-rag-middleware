"""Small deterministic normalizations for user-entered search syntax."""

from __future__ import annotations


_DOUBLE_QUOTE_TRANSLATION = str.maketrans({
    # English / generic smart quotes.
    "\u201c": '"',  # LEFT DOUBLE QUOTATION MARK
    "\u201d": '"',  # RIGHT DOUBLE QUOTATION MARK
    "\u201e": '"',  # DOUBLE LOW-9 QUOTATION MARK (German opening quote)
    "\u201f": '"',  # DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    # Guillemets are frequently produced by localized editors / copy-paste.
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2039": '"',
    "\u203a": '"',
})


def normalize_query_quotes(text: str) -> str:
    """Normalize typographic double quotes to the ASCII search delimiter.

    Search syntax treats double quotes as phrase delimiters.  Keyboard layout,
    browser/editor typography and copy/paste should not change retrieval
    semantics, therefore the common typographic variants are equivalent here.
    The function deliberately leaves apostrophes/single quotes untouched.
    """

    return str(text or "").translate(_DOUBLE_QUOTE_TRANSLATION)

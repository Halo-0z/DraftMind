"""Prospect name normalization and duplicate detection helpers.

These helpers exist because the 2026 prospect pool is assembled from several
sources (the local seed list in ``scripts/seed_db.py``, the NBA.com scrape in
``scripts/import_nba_prospects.py`` and the CSV market priors).  Different
sources spell the same player differently -- most commonly with/without a
``Jr.``/``Sr.`` suffix (e.g. NBA.com lists ``Darius Acuff`` while the local
seed has ``Darius Acuff Jr.``).  Without a shared normalization rule the same
player silently becomes two :class:`Prospect` rows, and the duplicate (which
has no projection) can end up being selected in a later round as if it were a
different person (B0-J preflight: Darius Acuff Jr. was selected at #8 while
the duplicate "Darius Acuff" was selected at #29).

The functions here are intentionally pure (no DB dependency) so they can be
unit-tested in isolation and reused by seed, import, and audit code paths.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

# Suffixes that should be stripped for identity comparison.  Kept as a regex
# anchored at end-of-string so we only strip a trailing generational suffix,
# never a name like "Junior" that is the player's actual first name.
_SUFFIX_RE = re.compile(r"\s+(jr|sr|ii|iii|iv)\.?\s*$", re.IGNORECASE)
# Punctuation that carries no identity information: periods (after initials,
# suffix dots), commas, apostrophes (Ja’Kobi -> jakobi), hyphens, quotes.
# Includes the unicode curly single quotes (’ and ‘) that appear in the 2026
# CSV (e.g. "Ja’Kobi Gillespie") so they normalize the same as ASCII '.
_PUNCT_RE = re.compile(r"[.,'\"`’‘]|\-")
_WHITESPACE_RE = re.compile(r"\s+")


def normalized_name(name: str | None) -> str:
    """Return a lossy identity key for a prospect name.

    Transformations (all irreversible on purpose -- this is a *comparison*
    key, never displayed):
      * strip + lowercase
      * drop a single trailing generational suffix (Jr./Sr./II/III/IV)
      * strip ``. , ' " ` -`` punctuation
      * collapse internal whitespace to single spaces

    Two names that normalize to the same string are treated as the same
    person for duplicate-detection purposes.  Examples:

      >>> normalized_name("Darius Acuff Jr.") == normalized_name("Darius Acuff")
      True
      >>> normalized_name("Ja’Kobi Gillespie") == normalized_name("JaKobi Gillespie")
      True
    """
    if not name:
        return ""
    n = name.strip().lower()
    n = _SUFFIX_RE.sub("", n)
    n = _PUNCT_RE.sub("", n)
    n = _WHITESPACE_RE.sub(" ", n)
    return n.strip()


def group_by_normalized_name(names: Iterable[str]) -> dict[str, list[str]]:
    """Group an iterable of display names by their normalized key.

    Returns a mapping ``normalized_key -> [original_name, ...]``.  Groups with
    more than one original name are candidate duplicates.  The original
    ordering within each group is preserved.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for n in names:
        groups[normalized_name(n)].append(n)
    return dict(groups)


def find_duplicate_name_groups(names: Iterable[str]) -> dict[str, list[str]]:
    """Return only the normalized groups that contain >1 distinct display name.

    Convenience wrapper around :func:`group_by_normalized_name` for callers
    that only care about the duplicates.
    """
    groups = group_by_normalized_name(names)
    return {
        key: originals
        for key, originals in groups.items()
        if len({o.strip().lower() for o in originals}) > 1
    }

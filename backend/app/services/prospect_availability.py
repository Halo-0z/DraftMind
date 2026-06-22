"""Official withdrawal / availability guard for DraftMind Auto Simulation.

This module expresses **eligibility / availability only**. It does NOT express
market sentiment, draft stock, or ranking opinion. Its sole purpose is to
prevent the Auto Simulation from selecting prospects who have officially
withdrawn from (or are otherwise ineligible for) a given draft year.

Design rules (M4-CC):
  * Only filters the candidate list; never mutates Prospect objects.
  * No DB writes, no migrations.
  * Name matching is normalized (case, whitespace, hyphens, accents) so that
    "Pavle Backo" and "Pavle Bačko" are treated as the same unavailable
    candidate.
  * Scoped to ``draft_year == 2026``. Other years are unaffected.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from app.models.prospect import Prospect


# ---------------------------------------------------------------------------
# Official withdrawn / unavailable name set (2026 NBA Draft)
# ---------------------------------------------------------------------------
#
# Names are stored in a canonical normalized form (see
# ``normalize_prospect_name``). Both "Pavle Backo" and "Pavle Bačko" normalize
# to the same key, so only one entry is needed; we keep both spellings in the
# source set for documentation clarity and rely on normalization to dedupe.

_OFFICIAL_WITHDRAWN_2026_RAW: tuple[str, ...] = (
    "Tounde Yessoufou",
    "Isiah Harwell",
    "Malachi Moreno",
    "Bassala Bagayoko",
    "Marc-Owen Fodzo Dada",
    "Pavle Backo",
    "Pavle Bačko",
    "Francesco Ferrari",
    "Luigi Suigo",
)


def normalize_prospect_name(name: str) -> str:
    """Normalize a prospect name for availability matching.

    Steps:
      1. Unicode NFKD decomposition, strip combining marks (accents).
         e.g. "Bačko" -> "Backo".
      2. Lowercase.
      3. Replace hyphens with spaces.
      4. Collapse runs of whitespace to a single space.
      5. Strip leading/trailing whitespace.

    This ensures "Pavle Backo", "pavle  backo", "Pavle Bačko" and
    "  Pavle   Bačko " all map to the same key ``"pavle backo"``.
    """
    if not name:
        return ""
    # 1. Accent stripping: decompose then drop combining characters.
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    # 2. Lowercase
    lowered = ascii_only.lower()
    # 3. Hyphens -> spaces (so "Marc-Owen" matches "Marc Owen")
    no_hyphens = lowered.replace("-", " ")
    # 4. Collapse whitespace
    collapsed = re.sub(r"\s+", " ", no_hyphens)
    # 5. Strip
    return collapsed.strip()


# Pre-normalized set for O(1) lookup.
_OFFICIAL_WITHDRAWN_2026: frozenset[str] = frozenset(
    normalize_prospect_name(name) for name in _OFFICIAL_WITHDRAWN_2026_RAW
)


def is_officially_unavailable_for_draft(
    name: str, draft_year: int | None = None
) -> bool:
    """Return True if ``name`` is officially unavailable for ``draft_year``.

    Only active for ``draft_year == 2026``. For any other year (or ``None``)
    this always returns ``False`` — the guard must never silently filter
    prospects from a year it has no withdrawal data for.
    """
    if draft_year != 2026:
        return False
    normalized = normalize_prospect_name(name)
    if not normalized:
        return False
    return normalized in _OFFICIAL_WITHDRAWN_2026


def filter_available_prospects(
    prospects: Iterable[Prospect],
    draft_year: int | None = None,
) -> list[Prospect]:
    """Filter out officially unavailable prospects from ``prospects``.

    Returns a new list. The input iterable is not mutated, and the Prospect
    objects themselves are never modified — only the candidate list is
    filtered.

    For ``draft_year != 2026`` (or ``None``) the input is returned as a new
    list unchanged.
    """
    if draft_year != 2026:
        return list(prospects)
    return [
        prospect
        for prospect in prospects
        if not is_officially_unavailable_for_draft(
            prospect.name, draft_year=draft_year
        )
    ]

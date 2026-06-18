"""RAG-v1-B2: ManualNoteRecord — persistent knowledge source for manual notes.

This model persists the request-level ``ManualNote`` schema
(``app.schemas.evidence.ManualNote``) so that manual analyst notes can survive
across requests and feed a future field-level retrieval service (RAG-v1-C).

Naming: the class is ``ManualNoteRecord`` (not ``ManualNote``) to avoid
collision with the Pydantic schema of the same name.

Safety boundary:

- ``evidence_only`` defaults to ``True`` and is the DB-level marker that this
  row must never feed back into scoring, selection, or ranking.
- This model is NOT imported by ``ranking_engine``, ``simulation_service``,
  or ``prediction_calibration``.  It is only consumed by the evidence /
  explanation layer.
- No FK back_populates is added to ``Prospect`` / ``Team`` to keep the
  selection-system models untouched.  The FK columns exist for indexing and
  future retrieval; relationships are intentionally omitted to avoid widening
  the scope into the ranking-side models.

Field notes:

- ``entity_id`` is stored as ``String`` to match the schema's ``int | str``
  union (the schema allows string identifiers like team abbreviations).
- ``tags`` is stored as a comma-separated string, mirroring the existing
  ``scheme_tags`` pattern in ``ProspectScoutingProfile`` / ``TeamNeedProfile``.
- ``confidence`` is a plain ``Float`` column; the 0-1 range is enforced at
  the schema layer (``ManualNote`` / ``EvidenceDocumentRead``) and is not
  re-implemented as a DB CHECK constraint to stay consistent with the rest of
  the codebase (no other model uses CHECK constraints).
- ``created_at`` / ``updated_at`` use ``datetime.utcnow`` defaults.  The
  project has no shared timestamp mixin; this is the minimal local pattern.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ManualNoteRecord(Base):
    """Persistent manual analyst note (evidence-only knowledge source)."""

    __tablename__ = "manual_notes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    year: Mapped[int] = mapped_column(index=True)

    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    # Stored as String to accommodate the schema's int | str union.
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)

    prospect_id: Mapped[int | None] = mapped_column(
        ForeignKey("prospects.id"), nullable=True, index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id"), nullable=True, index=True
    )
    pick_no: Mapped[int | None] = mapped_column(nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(240))
    body: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    source: Mapped[str] = mapped_column(String(80), default="manual")
    author: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    source_date: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # 0-1 range enforced at schema layer; no DB CHECK constraint (project convention).
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Comma-separated tags, mirroring scheme_tags in scouting profiles.
    tags: Mapped[str] = mapped_column(String(500), default="")
    relevance_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Evidence-only safety marker.  Defaults to True; must never be used as a
    # scoring / selection / ranking signal.
    evidence_only: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

from __future__ import annotations

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


PROJECTION_SOURCES = (
    "seed_projection",
    "manual_projection",
    "consensus_reference",
)

TEAM_PROJECTION_TYPES = (
    "consensus_mock",
    "team_report",
    "workout_signal",
    "manual_prediction",
)


class ProspectDraftProjection(Base):
    __tablename__ = "prospect_draft_projections"
    __table_args__ = (
        UniqueConstraint(
            "prospect_id",
            "year",
            "source",
            name="uq_prospect_projection_prospect_year_source",
        ),
        # M4-D: projection field upper bound widened from 60 to 100 to support
        # second-round / UDFA-bubble market board projections.  expected_pick >
        # 60 represents a market board slot / outside-draft projection, NOT a
        # real NBA pick number (the draft only has 60 picks).  These values are
        # used for eval / calibration awareness only.  The calibration top
        # market prior gate remains controlled by expected_pick <= 8, so
        # late-board projections do not inflate first-round selection.
        CheckConstraint(
            "consensus_rank IS NULL OR consensus_rank BETWEEN 1 AND 100",
            name="ck_prospect_projection_consensus_rank_range",
        ),
        CheckConstraint(
            "big_board_rank IS NULL OR big_board_rank BETWEEN 1 AND 100",
            name="ck_prospect_projection_big_board_rank_range",
        ),
        CheckConstraint(
            "expected_pick IS NULL OR expected_pick BETWEEN 1 AND 100",
            name="ck_prospect_projection_expected_pick_range",
        ),
        CheckConstraint(
            "draft_range_min IS NULL OR draft_range_min BETWEEN 1 AND 100",
            name="ck_prospect_projection_range_min",
        ),
        CheckConstraint(
            "draft_range_max IS NULL OR draft_range_max BETWEEN 1 AND 100",
            name="ck_prospect_projection_range_max",
        ),
        CheckConstraint(
            "draft_range_min IS NULL OR draft_range_max IS NULL OR draft_range_min <= draft_range_max",
            name="ck_prospect_projection_range_order",
        ),
        CheckConstraint("tier BETWEEN 1 AND 10", name="ck_prospect_projection_tier"),
        CheckConstraint(
            "source IN ('seed_projection', 'manual_projection', 'consensus_reference')",
            name="ck_prospect_projection_source",
        ),
        CheckConstraint("source_count >= 0", name="ck_prospect_projection_source_count"),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_prospect_projection_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    year: Mapped[int] = mapped_column(index=True)
    consensus_rank: Mapped[int | None] = mapped_column(nullable=True)
    big_board_rank: Mapped[int | None] = mapped_column(nullable=True)
    expected_pick: Mapped[int | None] = mapped_column(nullable=True)
    draft_range_min: Mapped[int | None] = mapped_column(nullable=True)
    draft_range_max: Mapped[int | None] = mapped_column(nullable=True)
    tier: Mapped[int] = mapped_column(default=5)
    source: Mapped[str] = mapped_column(String(32), default="manual_projection")
    source_count: Mapped[int] = mapped_column(default=1)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    last_updated: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    prospect = relationship("Prospect")


class TeamPickProjection(Base):
    __tablename__ = "team_pick_projections"
    __table_args__ = (
        UniqueConstraint(
            "year",
            "pick_no",
            "team_id",
            "prospect_id",
            "projection_type",
            "source",
            name="uq_team_pick_projection_signal",
        ),
        CheckConstraint("pick_no BETWEEN 1 AND 60", name="ck_team_pick_projection_pick_no"),
        CheckConstraint(
            "projection_type IN ('consensus_mock', 'team_report', 'workout_signal', 'manual_prediction')",
            name="ck_team_pick_projection_type",
        ),
        CheckConstraint(
            "source IN ('seed_projection', 'manual_projection', 'consensus_reference')",
            name="ck_team_pick_projection_source",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_team_pick_projection_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    year: Mapped[int] = mapped_column(index=True)
    pick_no: Mapped[int] = mapped_column(index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    projection_type: Mapped[str] = mapped_column(String(32), default="manual_prediction")
    source: Mapped[str] = mapped_column(String(32), default="manual_projection")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    notes: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    team = relationship("Team")
    prospect = relationship("Prospect")

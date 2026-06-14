from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Prospect(Base):
    __tablename__ = "prospects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    year: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    position: Mapped[str] = mapped_column(String(12), index=True)
    age: Mapped[float] = mapped_column(Float)
    height: Mapped[str] = mapped_column(String(24))
    weight: Mapped[int]
    school_or_league: Mapped[str] = mapped_column(String(120))
    ppg: Mapped[float] = mapped_column(Float)
    rpg: Mapped[float] = mapped_column(Float)
    apg: Mapped[float] = mapped_column(Float)
    fg_pct: Mapped[float] = mapped_column(Float)
    three_pct: Mapped[float] = mapped_column(Float)
    ft_pct: Mapped[float] = mapped_column(Float)
    stocks: Mapped[float] = mapped_column(Float)
    archetype: Mapped[str] = mapped_column(String(120))
    upside_score: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float] = mapped_column(Float)
    # B0-K1: provenance / confidence for the ppg/rpg/apg/fg/3pt/ft/stocks
    # fields above.  Both nullable for backward compatibility (pre-B0-K1 rows
    # have no provenance and are treated as ``unknown``).
    #
    # ``stats_source`` values:
    #   seed_manual              - hand-curated Prospect rows in seed_db.PROSPECTS
    #   nba_importer_heuristic   - estimate_stats() template values from the
    #                              NBA.com importer (position baseline, not real)
    #   unknown                  - legacy / no provenance recorded
    #
    # These fields are purely informational.  They MUST NOT change final_score
    # or selected_player in this milestone -- they only let downstream audits
    # and (later) calibration tell real stats from heuristic ones.
    stats_source: Mapped[str | None] = mapped_column(String(40), nullable=True, default=None)
    stats_confidence: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    scouting_reports: Mapped[list["ScoutingReport"]] = relationship(
        back_populates="prospect",
        cascade="all, delete-orphan",
    )
    scouting_profiles: Mapped[list["ProspectScoutingProfile"]] = relationship(
        back_populates="prospect",
        cascade="all, delete-orphan",
    )

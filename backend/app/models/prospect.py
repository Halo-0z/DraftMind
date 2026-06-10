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

    scouting_reports: Mapped[list["ScoutingReport"]] = relationship(
        back_populates="prospect",
        cascade="all, delete-orphan",
    )

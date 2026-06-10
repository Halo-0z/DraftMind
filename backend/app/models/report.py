from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ScoutingReport(Base):
    __tablename__ = "scouting_reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    report_text: Mapped[str] = mapped_column(Text)

    prospect: Mapped["Prospect"] = relationship(back_populates="scouting_reports")

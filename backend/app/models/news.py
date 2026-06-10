from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NewsArticle(Base):
    """Cached NBA prospect / draft news article (Chinese-language first)."""

    __tablename__ = "news_articles"
    __table_args__ = (
        Index("ix_news_published_at", "published_at"),
        Index("ix_news_source", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(400))
    summary: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(600), unique=True, index=True)
    author: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str] = mapped_column(String(8), default="zh")
    published_at: Mapped[datetime] = mapped_column(DateTime)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    # Free-form text used for retrieval: title + summary + first body excerpt.
    body_excerpt: Mapped[str] = mapped_column(Text, default="")
    # Comma-separated prospect identifiers referenced in the article.
    prospect_names: Mapped[str] = mapped_column(Text, default="")
    # Comma-separated team abbreviations referenced in the article.
    team_abbrs: Mapped[str] = mapped_column(Text, default="")

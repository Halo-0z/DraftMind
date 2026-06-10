from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewsArticleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    summary: str
    url: str
    author: str | None = None
    language: str
    published_at: datetime
    fetched_at: datetime
    body_excerpt: str
    prospect_names: str
    team_abbrs: str


class NewsSearchResponse(BaseModel):
    query: str
    total: int
    articles: list[NewsArticleRead]

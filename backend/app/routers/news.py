from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import NewsArticle
from app.schemas.news import NewsArticleRead, NewsSearchResponse
from app.services.news_service import fetch_recent_articles, search_articles, SOURCES


router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=NewsSearchResponse)
def list_news(
    prospect: str | None = Query(default=None, description="按新秀姓名筛选"),
    team: str | None = Query(default=None, description="按球队缩写筛选，如 SAS"),
    keyword: str | None = Query(default=None, description="自由关键词"),
    language: str | None = Query(default=None, description="zh / en"),
    refresh: bool = Query(default=False, description="是否先拉取最新新闻"),
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> NewsSearchResponse:
    if refresh:
        try:
            fetch_recent_articles(db=db, refresh=True)
        except Exception as exc:  # noqa: BLE001 - upstream RSS may be flaky
            raise HTTPException(status_code=502, detail=f"新闻源暂不可用: {exc}") from exc

    articles = search_articles(
        db,
        prospect_name=prospect,
        team_abbr=team,
        keyword=keyword,
        language=language,
        limit=limit,
    )
    return NewsSearchResponse(
        query=prospect or team or keyword or "",
        total=len(articles),
        articles=[NewsArticleRead.model_validate(article) for article in articles],
    )


@router.post("/refresh", response_model=NewsSearchResponse)
def refresh_news(
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
) -> NewsSearchResponse:
    try:
        articles = fetch_recent_articles(db=db, refresh=True)
    except Exception as exc:  # noqa: BLE001
        # Never propagate source failures to the user; the service has
        # already logged and skipped every individual source. If we still
        # reach here, treat it as an empty refresh so the UI can show
        # whatever was already cached.
        import logging
        logging.getLogger(__name__).warning("news refresh outer failure: %s", exc)
        articles = []
    found = search_articles(db, limit=limit)
    return NewsSearchResponse(
        query="",
        total=len(found),
        articles=[NewsArticleRead.model_validate(article) for article in found],
    )


@router.delete("/purge")
def purge_orphaned_news(db: Session = Depends(get_db)) -> dict:
    """Delete all articles from sources no longer in SOURCES config."""
    active_sources = {s["name"] for s in SOURCES}
    orphaned = list(db.scalars(select(NewsArticle).where(NewsArticle.source.notin_(active_sources))))
    count = len(orphaned)
    if count:
        ids = [a.id for a in orphaned]
        db.execute(delete(NewsArticle).where(NewsArticle.id.in_(ids)))
        db.commit()
    return {"deleted": count, "active_sources": list(active_sources)}

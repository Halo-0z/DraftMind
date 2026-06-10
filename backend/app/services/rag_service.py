from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.news import NewsArticle
from app.models.prospect import Prospect
from app.models.report import ScoutingReport
from app.services.news_service import build_prospect_context


def build_prospect_context_block(
    db: Session,
    *,
    prospect: Prospect,
    team_abbr: str | None,
    limit: int = 3,
) -> str:
    """Aggregate scouting + news context for a prospect, used as RAG input.

    Returns a multi-line Chinese-friendly block; callers should pass this
    string to the LLM as additional context but never let the model
    invent numbers from it.
    """

    lines: list[str] = []

    reports = list(prospect.scouting_reports or [])
    if reports:
        for report in reports[:2]:
            excerpt = (report.report_text or "").strip()
            if excerpt:
                lines.append(f"- 球探报告({report.source}): {excerpt[:280]}")

    articles = build_prospect_context(
        db,
        prospect_name=prospect.name,
        team_abbr=team_abbr,
        limit=limit,
    )
    for article in articles:
        lines.append(
            f"- 新闻({article.source}, {article.published_at.strftime('%m-%d')}): "
            f"{article.title}\n  摘要: {article.summary[:220]}\n  链接: {article.url}"
        )

    if not lines:
        return ""

    header = f"以下是与 {prospect.name} 相关的、已确认的球探报告与近期新闻摘要。禁止在此之外编造任何数据："
    return header + "\n" + "\n".join(lines)

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings
import requests


logger = logging.getLogger(__name__)


def fetch_teams() -> list[dict[str, Any]]:
    """Return NBA teams from balldontlie. Free tier covers this endpoint."""

    settings = get_settings()
    headers: dict[str, str] = {"User-Agent": "DraftMind/0.1"}
    if settings.balldontlie_api_key:
        headers["Authorization"] = settings.balldontlie_api_key

    response = requests.get(
        f"{settings.balldontlie_base_url}/teams",
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "data" in payload:
        return list(payload["data"])
    if isinstance(payload, list):
        return payload
    return []


def fetch_team_standings(season: int) -> list[dict[str, Any]]:
    """Standings require a paid tier; treat a 402/403 as an empty list."""

    settings = get_settings()
    headers: dict[str, str] = {"User-Agent": "DraftMind/0.1"}
    if settings.balldontlie_api_key:
        headers["Authorization"] = settings.balldontlie_api_key
    try:
        response = requests.get(
            f"{settings.balldontlie_base_url}/standings",
            headers=headers,
            params={"season": season},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.warning("balldontlie standings request failed: %s", exc)
        return []
    if response.status_code in (401, 402, 403, 404):
        return []
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "data" in payload:
        return list(payload["data"])
    return payload if isinstance(payload, list) else []

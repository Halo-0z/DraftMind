"""Smoke-test all the new modules by importing them and exercising critical paths."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=== import check ===")
from app import main
print("main ok")

from app.models import NewsArticle, Prospect, ScoutingReport
print("models ok")

from app.services.news_service import fetch_recent_articles, search_articles, upsert_article
print("news_service ok")

from app.services.rag_service import build_prospect_context_block
print("rag_service ok")

from app.services.llm_service import LLMService, _parse_json_response, _explanation_from_payload
print("llm_service ok")

from app.services.balldontlie_service import fetch_teams
print("balldontlie_service ok")

from app.services.agent_service import AgentService
print("agent_service ok")

print()
print("=== settings check ===")
from app.config import get_settings
s = get_settings()
print(f"provider={s.llm_provider}, model={s.llm_model}, has_key={bool(s.llm_api_key)}")

print()
print("=== provider mode ===")
svc = LLMService(settings=s)
print(f"provider={svc.provider}, is_mock={svc.is_mock}")

print()
print("=== JSON parse check ===")
parsed = _parse_json_response("```json\n{\"a\": 1}\n```")
assert parsed == {"a": 1}, parsed
print("json parse ok")

print()
print("ALL SMOKE TESTS PASSED")

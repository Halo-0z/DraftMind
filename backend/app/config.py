from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "DraftMind API"
    app_env: str = "development"
    api_prefix: str = "/api"
    database_url: str = "sqlite:///./draftmind.db"

    # ---- LLM (OpenAI 兼容协议) ----
    # DraftMind 已验证可对接以下模型（仅需改 LLM_MODEL / LLM_API_BASE 即可，
    # 全部走 OpenAI 兼容协议，无需改代码）：
    #
    # ★ 首推：DeepSeek-V4-Pro  你的 tokenhub 在线推理服务 ID
    #        输入 ¥12/百万  输出 ¥24/百万  缓存命中 ¥1/百万
    # ★ 备选：DeepSeek-V4-Flash  性价比翻倍
    #        输入 ¥1/百万   输出 ¥2/百万   缓存命中 ¥0.2/百万
    # 注：deepseek-v4-pro-202606 是腾讯原厂直供最新版，需要先在 tokenhub 后台
    #     显式开通才能用，否则会 401006 model not in allowed list。
    #
    # base_url（OpenAI 协议）:
    #   腾讯云 TokenHub : https://tokenhub.tencentmaas.com/v1
    #   DeepSeek 官方    : https://api.deepseek.com
    #
    # 三步启动真实 LLM:
    #   1) 在 .env 填 LLM_API_KEY (= tokenhub 的 sk-xxx)
    #   2) 设 LLM_PROVIDER=deepseek
    #   3) 设 LLM_MODEL=deepseek-v4-pro  (必须与 tokenhub 服务 ID 一致)
    llm_provider: str = "mock"
    llm_model: str = "deepseek-v4-pro"
    llm_api_key: str = ""
    llm_api_base: str = "https://tokenhub.tencentmaas.com/v1"
    llm_timeout: float = 25.0
    # Tencent legacy secret (kept for SDK-style callers).
    tencent_secret_id: str = ""
    tencent_secret_key: str = ""

    # ---- Evidence Explanation LLM (RAG-v0-M3.1-D) ----
    # Real LLM explanation is OFF by default.  Even if llm_api_key is present,
    # the evidence explanation provider adapter will NOT be created unless this
    # flag is explicitly set to True.  This is the hard safety boundary.
    enable_real_llm_explanation: bool = False
    llm_explanation_timeout: float = 10.0
    llm_explanation_max_tokens: int = 900
    llm_explanation_temperature: float = 0.0

    # ---- Evidence Retrieval (RAG-v1-D1-C) ----
    # ManualNote persisted retrieval is OFF by default.  When False, the
    # evidence router does NOT pass a DB session to build_pick_evidence and
    # the retrieval path stays dormant (identical to pre-RAG-v1 behavior).
    # When True, the router injects the DB session and sets
    # retrieve_knowledge=True so persisted ManualNote rows are appended to
    # retrieved_evidence / citations only — never to ranking / scoring /
    # selection fields.  This flag is read server-side; it is NOT exposed
    # via the API schema or controllable by the frontend.
    evidence_retrieve_manual_notes: bool = False

    # ---- Semantic Retrieval (RAG-v2-M2-E) ----
    # Config-gated semantic retrieval over manual notes.  OFF by default
    # so existing callers are unaffected.  When True, the evidence service
    # chunks manual notes, embeds them with the fake deterministic
    # embedding (M2-C1), builds an in-memory vector index (M2-D1), runs
    # semantic retrieval (M2-D2), and appends the results to
    # retrieved_evidence / citations only — never to ranking / scoring /
    # selection fields.  Any failure falls back to the old logic so the
    # semantic path is never a hard dependency.  This flag is read
    # server-side; it is NOT exposed via the API schema.
    evidence_retrieve_semantic: bool = False
    evidence_semantic_top_k: int = 5
    evidence_semantic_min_score: float = 0.0

    # ---- News ingestion ----
    news_user_agent: str = "Mozilla/5.0 DraftMind/0.1 (Chinese)"
    news_refresh_minutes: int = 60
    news_max_articles: int = 200
    news_fetch_timeout: float = 6.0  # per-request HTTP timeout in seconds

    # ---- Free NBA data ----
    balldontlie_api_key: str = ""
    balldontlie_base_url: str = "https://api.balldontlie.io/nba/v1"

    model_config = SettingsConfigDict(env_file="../.env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

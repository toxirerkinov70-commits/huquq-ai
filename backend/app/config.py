from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-2.5-flash"
    # each model carries its own free-tier daily allowance, so exhausting one does
    # not block the others; the client walks this list when a model is spent
    gemini_llm_fallbacks: str = (
        "gemini-2.5-flash-lite,gemini-flash-latest,gemini-flash-lite-latest,"
        "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    )
    # "local" runs the embedding model on this machine and has no quota;
    # "gemini" uses the API, which on the free tier allows 1000 requests a day
    embed_provider: str = "local"
    gemini_embed_model: str = "gemini-embedding-001"
    local_embed_model: str = "intfloat/multilingual-e5-base"
    embed_dim: int = 768
    # each of these costs one extra LLM call per question; the free tier is limited
    enable_query_expansion: bool = True
    enable_rerank: bool = True
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "uz_legal"
    sqlite_path: str = "./data/app.db"
    lex_base_url: str = "https://lex.uz"
    lex_request_delay: float = 1.5
    # the corpus goes stale on its own, so the refresh runs unattended; turn this off
    # only when the backend is started somewhere that must not reach lex.uz
    enable_scheduler: bool = True
    log_level: str = "INFO"


settings = Settings()

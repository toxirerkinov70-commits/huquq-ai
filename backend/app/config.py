from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-2.5-flash"
    gemini_embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "uz_legal"
    sqlite_path: str = "./data/app.db"
    lex_base_url: str = "https://lex.uz"
    lex_request_delay: float = 1.5
    log_level: str = "INFO"


settings = Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # utf-8-sig, not utf-8: a byte order mark at the start of .env attaches itself to
    # the first variable's name, so that variable silently reads as empty. When the
    # first line is the API key, every answer fails with a 403 and nothing says why.
    # Windows editors and PowerShell's Set-Content write the mark by default.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8-sig", extra="ignore"
    )

    gemini_api_key: str = ""
    gemini_llm_model: str = "gemini-2.5-flash"
    # each model carries its own free-tier daily allowance, so exhausting one does
    # not block the others; the client walks this list when a model is spent
    gemini_llm_fallbacks: str = (
        "gemini-2.5-flash-lite,gemini-flash-latest,gemini-flash-lite-latest,"
        "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    )
    # a downgrade caused by a spent daily quota is not permanent; after this many
    # minutes the primary model is tried again instead of serving the weakest model
    # in the chain until the process restarts
    llm_primary_retry_minutes: int = 90
    # "local" runs the embedding model on this machine and has no quota;
    # "gemini" uses the API, which on the free tier allows 1000 requests a day
    embed_provider: str = "local"
    gemini_embed_model: str = "gemini-embedding-001"
    local_embed_model: str = "intfloat/multilingual-e5-base"
    embed_dim: int = 768
    # how many questions may be embedded at once. torch releases the GIL, so more than
    # one is real parallelism, but each concurrent encode holds its own working memory
    embed_concurrency: int = 2
    # each of these costs one extra LLM call per question; the free tier is limited
    enable_query_expansion: bool = True
    enable_rerank: bool = True
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "uz_legal"
    sqlite_path: str = "./data/app.db"
    lex_base_url: str = "https://lex.uz"
    lex_request_delay: float = 1.5

    # --- access control -------------------------------------------------------
    # signs the bearer tokens handed to browsers. Left empty it is generated once and
    # kept in data/.auth_secret so a fresh checkout still runs; set it explicitly in
    # production or every restart invalidates every token
    auth_secret: str = ""
    # opens the admin endpoints. Empty means they are switched off entirely
    admin_api_key: str = ""
    # comma separated origins allowed to call the API from a browser. "*" is refused
    # unless allow_public_cors is on, because the API spends money on every request
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    allow_public_cors: bool = False
    # requests larger than this are rejected before they reach a handler
    max_request_bytes: int = 16 * 1024 * 1024
    # anonymous visitors get an account automatically; turning this off makes the
    # service invite-only
    allow_anonymous_signup: bool = True
    default_plan: str = "free"
    # these accounts are the service's own; they are put on the owner plan on sight,
    # whichever way they sign in
    owner_emails: str = "toxirerkinov70@gmail.com"

    # --- registration ---------------------------------------------------------
    # the "Sign in with Google" button needs this; empty hides the button
    google_client_id: str = ""
    # console prints the code to the log instead of sending it — development only,
    # and refused outright when ENVIRONMENT is production
    sms_provider: str = "console"
    eskiz_email: str = ""
    eskiz_password: str = ""
    eskiz_from: str = "4546"
    otp_length: int = 6
    otp_ttl_seconds: int = 180
    otp_max_attempts: int = 5
    # a new code cannot be requested until this many seconds have passed
    otp_resend_seconds: int = 60
    otp_daily_limit: int = 10
    # bumping this asks every user to accept the offer again
    terms_version: str = "2026-08-01"
    # per-IP ceiling applied on top of the per-plan quotas, to blunt scripted abuse
    rate_limit: str = "60/minute"
    auth_rate_limit: str = "10/minute"

    # --- billing --------------------------------------------------------------
    # USD per one million tokens. Verify against ai.google.dev/pricing before relying
    # on the figures for invoicing; they exist so cost per answer is measured rather
    # than guessed
    price_input_per_mtok: float = 0.30
    price_output_per_mtok: float = 2.50
    usd_to_uzs: float = 12900.0

    # --- operations -----------------------------------------------------------
    # the refresh runs in its own container so the API can be scaled with workers;
    # leaving it on inside the API process makes every worker start its own crawl
    enable_scheduler: bool = False
    log_level: str = "INFO"
    log_json: bool = False
    environment: str = "development"


settings = Settings()

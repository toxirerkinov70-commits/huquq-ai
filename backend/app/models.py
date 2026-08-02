from pydantic import BaseModel, Field


class Attachment(BaseModel):
    name: str = Field(max_length=255)
    mime: str = Field(max_length=100)
    # base64 of at most ~10 MB of file bytes
    data: str = Field(max_length=15_000_000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    agent: str = "umumiy"
    session_id: str | None = None
    stream: bool = True
    attachment: Attachment | None = None


class Source(BaseModel):
    doc_id: str | None = None
    doc_title: str | None = None
    article_no: str | None = None
    article_title: str | None = None
    source_url: str | None = None
    snippet: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    used_agent: str = "umumiy"
    session_id: str | None = None


class SessionSummary(BaseModel):
    id: str
    agent: str = "umumiy"
    title: str | None = None
    pinned: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class SessionMessage(BaseModel):
    role: str
    content: str
    sources: list[Source] = []
    created_at: str | None = None


class SessionDetail(BaseModel):
    id: str
    messages: list[SessionMessage] = []


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    agent: str = "umumiy"
    k: int = Field(default=10, ge=1, le=50)
    mode: str = "hybrid"
    rerank: bool = False
    expand: bool = False


class SearchHit(BaseModel):
    chunk_id: str
    score: float
    source: str
    doc_id: str | None = None
    doc_title: str | None = None
    article_no: str | None = None
    article_title: str | None = None
    source_url: str | None = None
    text: str | None = None


class SearchResponse(BaseModel):
    query: str
    detected_article_no: str | None = None
    detected_doc_ids: list[str] = []
    hits: list[SearchHit] = []


class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    doc_type: str | None = None
    act_type: int | None = None
    adopted_date: str | None = None
    effective_date: str | None = None
    status: str | None = None
    articles: int | None = None
    url: str | None = None


class ArticleSummary(BaseModel):
    article_no: str | None = None
    article_title: str | None = None
    source_url: str | None = None
    chapter: str | None = None


class DocumentDetail(DocumentSummary):
    okoz: list[str] = []
    tsz: list[str] = []
    articles_list: list[ArticleSummary] = []


# --- accounts, plans and usage -----------------------------------------------


class QuotaStatus(BaseModel):
    plan: str
    plan_name: str
    used_today: int
    daily_limit: int
    remaining: int
    reset_seconds: int


class AuthResponse(BaseModel):
    token: str
    user_id: str
    plan: str
    quota: QuotaStatus
    # the client routes on these: a returning user goes straight in, a new one is
    # walked through the remaining steps
    name: str | None = None
    needs_profile: bool = False
    needs_terms: bool = False


class PhoneStartRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=25)


class PhoneStartResponse(BaseModel):
    phone_masked: str
    expires_in: int
    resend_in: int
    registered: bool = False
    # filled only by the console sender outside production, so the flow is testable
    debug_code: str | None = None


class PhoneVerifyRequest(BaseModel):
    phone: str = Field(min_length=7, max_length=25)
    code: str = Field(min_length=4, max_length=8)


class GoogleAuthRequest(BaseModel):
    # the button flow sends credential, the popup flow sends access_token; exactly one
    credential: str | None = Field(default=None, min_length=20, max_length=4096)
    access_token: str | None = Field(default=None, min_length=20, max_length=4096)


class CompleteRegistrationRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    accept_terms: bool = False


class AuthConfig(BaseModel):
    google_enabled: bool
    google_client_id: str | None = None
    # why the button is missing, outside production only — a developer who has not set
    # the client id should be told that, not left wondering where the button went
    google_hint: str | None = None
    allow_anonymous: bool
    terms_version: str
    phone_prefix: str = "+998"
    otp_length: int = 6
    sms_hint: str | None = None


class PlanFeatures(BaseModel):
    key: str
    name: str
    price_uzs: int
    tagline: str
    daily_questions: int
    allow_agentic: bool
    allow_attachments: bool
    attachment_mb: int
    allow_api_keys: bool
    api_keys_max: int
    history_days: int
    # the pricing page needs these to know which cards lead to a checkout
    listed: bool = True
    purchasable: bool = False
    features: list[str] = []


class ApiKeyInfo(BaseModel):
    id: int
    prefix: str
    name: str | None = None
    created_at: str | None = None
    last_used_at: str | None = None
    revoked_at: str | None = None


class ApiKeyCreated(ApiKeyInfo):
    # shown once and never stored in readable form
    key: str


class ApiKeyRequest(BaseModel):
    name: str | None = Field(default=None, max_length=80)


class AccountResponse(BaseModel):
    user_id: str
    kind: str
    name: str | None = None
    phone: str | None = None
    phone_display: str | None = None
    email: str | None = None
    picture: str | None = None
    plan: PlanFeatures
    plan_expires_at: str | None = None
    created_at: str | None = None
    accepted_terms: bool = False
    is_owner: bool = False
    quota: QuotaStatus
    api_keys: list[ApiKeyInfo] = []


class SessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    pinned: bool | None = None


class OrderRequest(BaseModel):
    plan: str
    months: int = Field(default=1, ge=1, le=12)
    provider: str | None = Field(default=None, max_length=30)


class OrderInfo(BaseModel):
    id: str
    plan: str
    plan_name: str | None = None
    months: int
    amount_uzs: int
    provider: str | None = None
    status: str
    created_at: str | None = None
    paid_at: str | None = None
    note: str | None = None


class PaymentMethod(BaseModel):
    key: str
    name: str
    description: str
    available: bool


class UsageResponse(BaseModel):
    window_days: int
    totals: dict
    daily: list[dict] = []
    cost_uzs: float = 0.0


class PlanChangeRequest(BaseModel):
    user_id: str
    plan: str
    expires_at: str | None = None


class StatusChangeRequest(BaseModel):
    user_id: str
    status: str = Field(pattern="^(active|blocked|archived)$")

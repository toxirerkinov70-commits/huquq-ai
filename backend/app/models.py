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

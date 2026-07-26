import hashlib
import logging
import re
import threading
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RETRY_STATUS = {429, 500, 502, 503, 504}
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


class LexClient:
    """HTTP client for lex.uz with robots.txt compliance, disk cache and backoff."""

    def __init__(
        self,
        base_url: str,
        delay: float,
        cache_dir: Path,
        timeout: float = 60.0,
        max_retries: int = 3,
        concurrency: int = 1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "uz,ru;q=0.9,en;q=0.8",
            },
            follow_redirects=True,
            timeout=timeout,
        )
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._robots = self._load_robots()
        robots_delay = self._robots.crawl_delay(USER_AGENT) or 0.0
        self.delay = max(delay, float(robots_delay))
        if self.delay > delay:
            logger.info(
                "robots.txt Crawl-delay=%ss overrides configured delay %ss", robots_delay, delay
            )
        if concurrency > 1:
            self.delay /= concurrency
            logger.warning(
                "concurrency=%s lowers the effective spacing to %.2fs, which exceeds the "
                "rate declared in robots.txt",
                concurrency,
                self.delay,
            )

    def __enter__(self) -> "LexClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _load_robots(self) -> RobotFileParser:
        resp = self._client.get(f"{self.base_url}/robots.txt")
        resp.raise_for_status()
        parser = RobotFileParser()
        # lex.uz serves robots.txt with a BOM, which breaks directive parsing
        parser.parse(resp.text.lstrip("﻿").splitlines())
        return parser

    def get(self, path: str, cache_key: str | None = None, use_cache: bool = True) -> str:
        return self._request("GET", path, cache_key=cache_key or path, use_cache=use_cache)

    def post(
        self, path: str, data: dict[str, str], cache_key: str, use_cache: bool = True
    ) -> str:
        return self._request("POST", path, cache_key=cache_key, data=data, use_cache=use_cache)

    def _request(
        self,
        method: str,
        path: str,
        cache_key: str,
        data: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> str:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        if not self._robots.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows {url}")

        cache_path = self._cache_path(cache_key)
        if use_cache and cache_path.exists():
            logger.debug("cache hit %s", cache_key)
            return cache_path.read_text(encoding="utf-8")

        text = self._request_with_retry(method, url, data)
        if use_cache:
            cache_path.write_text(text, encoding="utf-8")
        return text

    def _request_with_retry(
        self, method: str, url: str, data: dict[str, str] | None
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._wait()
            try:
                resp = self._client.request(method, url, data=data)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("%s %s failed (%s), attempt %s", method, url, exc, attempt + 1)
            else:
                if resp.status_code not in RETRY_STATUS:
                    resp.raise_for_status()
                    return resp.text
                if resp.status_code == 429:
                    self._slow_down()
                last_error = httpx.HTTPStatusError(
                    f"status {resp.status_code}", request=resp.request, response=resp
                )
                logger.warning(
                    "%s %s returned %s, attempt %s", method, url, resp.status_code, attempt + 1
                )
            time.sleep(self.delay * 2**attempt)
        raise RuntimeError(
            f"{method} {url} failed after {self.max_retries} attempts"
        ) from last_error

    def _wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if self._last_request and elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self._last_request = time.monotonic()

    def _slow_down(self) -> None:
        """A 429 means we are already too fast, so back off for the rest of the run."""
        with self._lock:
            self.delay *= 2
        logger.warning("server returned 429, raising request spacing to %.2fs", self.delay)

    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
        prefix = _UNSAFE_CHARS.sub("_", key).strip("_")[:60]
        return self.cache_dir / f"{prefix}_{digest}.html"

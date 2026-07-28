import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Iterator
from urllib.parse import urlencode

from selectolax.parser import HTMLParser

from .client import LexClient

logger = logging.getLogger(__name__)

NEXT_LINK_ID = "ucFoundActsControl_LinkButton1"
POSTBACK_RE = re.compile(r"__doPostBack\('([^']+)'")
TOTAL_RE = re.compile(r"([\d\s ]+?)\s*hujjat topildi")
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
NUMBER_RE = re.compile(r"yildagi\s+(\S+)")
STATUS_RE = re.compile(r"status_code_(\w+)")


@dataclass(frozen=True)
class GroupSpec:
    number: int
    name: str
    act_type: int | None
    path: str = "/uz/search/all"
    params: dict[str, str] = field(default_factory=dict)

    def query(self) -> str:
        params = {"lang": "4", "status": "Y", "minor": "N"}
        if self.act_type is not None:
            params["act_type"] = str(self.act_type)
        params.update(self.params)
        params = {key: value for key, value in params.items() if value != ""}
        return f"{self.path}?{urlencode(params)}"


GROUPS: dict[int, GroupSpec] = {
    1: GroupSpec(1, "Konstitutsiya", 1),
    2: GroupSpec(2, "Kodekslar", 21),
    3: GroupSpec(3, "Qonunlar", 22),
    4: GroupSpec(4, "Prezident hujjatlari", 3),
    5: GroupSpec(5, "Hukumat qarorlari", 4),
    6: GroupSpec(6, "Sud amaliyoti", None, path="/uz/search/court", params={"minor": ""}),
    7: GroupSpec(7, "Idoraviy hujjatlar", 5),
    8: GroupSpec(8, "Xalqaro hujjatlar", 6),
    # The court tab is built around individual cases and yielded only four Plenum
    # rulings. The Plenum is an organ, not a document type, so the body filter on the
    # general search is what actually reaches its rulings and practice reviews.
    9: GroupSpec(
        9,
        "Oliy sud Plenumi qarorlari",
        None,
        path="/uz/search/all",
        params={"fbody_id": "2328"},
    ),
}


@dataclass
class ResultsPage:
    records: list[dict]
    total: int | None
    hidden: dict[str, str]
    next_target: str | None


def parse_results_page(html: str, spec: GroupSpec) -> ResultsPage:
    tree = HTMLParser(html)
    hidden = {
        inp.attributes["name"]: inp.attributes.get("value", "") or ""
        for inp in tree.css("input[type=hidden]")
        if (inp.attributes.get("name") or "").startswith("__")
    }

    records = []
    for row in tree.css("tr.dd-table__main-item"):
        record = _parse_row(row, spec)
        if record is not None:
            records.append(record)

    total = None
    match = TOTAL_RE.search(tree.text())
    if match is not None:
        total = int(re.sub(r"\D", "", match.group(1)))

    next_target = None
    next_link = tree.css_first(f"a#{NEXT_LINK_ID}")
    if next_link is not None:
        href = next_link.attributes.get("href") or ""
        postback = POSTBACK_RE.search(href)
        if postback is not None:
            next_target = postback.group(1)

    return ResultsPage(records=records, total=total, hidden=hidden, next_target=next_target)


def _parse_row(row, spec: GroupSpec) -> dict | None:
    link = row.css_first("div.dd-table__main-left-desc a")
    if link is None:
        return None
    href = link.attributes.get("href") or ""
    # a search with a text query links to /uz/docs/-8336553?query=...#sr-1, and the
    # trailing part would otherwise be stored as the document id
    doc_id = href.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    if not doc_id:
        return None

    badge = row.css_first("span.badge")
    badge_text = badge.text(strip=True) if badge is not None else ""
    title = link.text(strip=True)

    status = "Y"
    state = row.css_first("span.lx_act_state i")
    if state is not None:
        match = STATUS_RE.search(state.attributes.get("class") or "")
        if match is not None:
            status = match.group(1).upper()

    return {
        "doc_id": doc_id,
        "url": f"https://lex.uz{href}",
        "title": title,
        "act_type": spec.act_type,
        "group": spec.number,
        "form": _parse_form(badge_text, title),
        "doc_number": _parse_number(badge_text),
        "adopted_date": _parse_date(badge_text),
        "effective_date": None,
        "status": status,
        "organ": None,
        "okoz": [],
        "lang": 4,
        "discovered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _parse_form(badge_text: str, title: str) -> str | None:
    # badge reads "Oʻzbekiston Respublikasining Qonuni, 02.06.2026 yildagi OʻRQ-1148-son";
    # for codes it only repeats the title and carries no form information
    head = badge_text.split(",", 1)[0].strip()
    if not head or head == title:
        return None
    return head


def _parse_number(badge_text: str) -> str | None:
    match = NUMBER_RE.search(badge_text)
    return match.group(1) if match is not None else None


def _parse_date(badge_text: str) -> str | None:
    match = DATE_RE.search(badge_text)
    if match is None:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        logger.warning("invalid date in badge: %s", badge_text)
        return None


def discover_group(
    client: LexClient, spec: GroupSpec, max_pages: int | None = None
) -> Iterator[dict]:
    query = spec.query()
    html = client.get(query, cache_key=f"search/g{spec.number}/p1")
    page = parse_results_page(html, spec)
    logger.info("group %s (%s): %s documents reported", spec.number, spec.name, page.total)

    page_number = 1
    seen: set[str] = set()
    while True:
        new_records = [rec for rec in page.records if rec["doc_id"] not in seen]
        seen.update(rec["doc_id"] for rec in new_records)
        yield from new_records
        logger.info(
            "group %s page %s: %s rows, %s unique so far",
            spec.number,
            page_number,
            len(page.records),
            len(seen),
        )

        if not page.records or page.next_target is None:
            break
        if max_pages is not None and page_number >= max_pages:
            logger.info("stopping at page limit %s", max_pages)
            break

        page_number += 1
        data = dict(page.hidden)
        data["__EVENTTARGET"] = page.next_target
        data["__EVENTARGUMENT"] = ""
        html = client.post(query, data=data, cache_key=f"search/g{spec.number}/p{page_number}")
        page = parse_results_page(html, spec)

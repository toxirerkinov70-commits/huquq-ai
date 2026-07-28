"""Watch the official publication feed for documents that entered force recently.

lex.uz publishes what was promulgated today, this week and this month at
/uz/search/official. Reading the daily page is far cheaper than re-crawling the whole
registry, and the weekly page covers days when the daily run did not happen.
"""

import logging
import re
from dataclasses import dataclass

from .client import LexClient
from .discover import GroupSpec, parse_results_page

logger = logging.getLogger(__name__)

WINDOWS = ("today", "week", "month")

# only the groups the corpus actually carries; anything else is listed and skipped
KONSTITUTSIYA, KODEKS, QONUN, SUD = 1, 2, 3, 6

FORM_RULES: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"konstitutsiya", re.IGNORECASE), KONSTITUTSIYA),
    (re.compile(r"kodeks", re.IGNORECASE), KODEKS),
    (re.compile(r"plenum|sud amaliyoti|sudlov hay", re.IGNORECASE), SUD),
    (re.compile(r"qonun", re.IGNORECASE), QONUN),
]


@dataclass
class Spotted:
    record: dict
    group: int | None

    @property
    def in_scope(self) -> bool:
        return self.group is not None


def watch_spec(window: str) -> GroupSpec:
    if window not in WINDOWS:
        raise ValueError(f"unknown window {window!r}, expected one of {WINDOWS}")
    return GroupSpec(
        number=0,
        name=f"official/{window}",
        act_type=None,
        path="/uz/search/official",
        params={"pub_date": window},
    )


def classify(record: dict) -> int | None:
    """Assign a registry group from the listing badge, or None when out of scope.

    The feed carries presidential decrees and ministerial acts too. Those were left out
    of the corpus on purpose, so they are counted in the report and then dropped.
    """
    text = f"{record.get('form') or ''} {record.get('title') or ''}"
    for pattern, group in FORM_RULES:
        if pattern.search(text):
            return group
    return None


def spot_new(client: LexClient, window: str, max_pages: int = 10) -> list[Spotted]:
    """Read one publication window and return everything it lists, classified."""
    spec = watch_spec(window)
    query = spec.query()
    # the feed changes daily, so the response cache would defeat the purpose
    html = client.get(query, use_cache=False)
    page = parse_results_page(html, spec)
    logger.info("window %s: %s documents reported", window, page.total)

    found: dict[str, Spotted] = {}
    page_number = 1
    while True:
        for record in page.records:
            record["group"] = classify(record)
            found.setdefault(record["doc_id"], Spotted(record, record["group"]))

        if not page.records or page.next_target is None or page_number >= max_pages:
            break
        page_number += 1
        data = dict(page.hidden)
        data["__EVENTTARGET"] = page.next_target
        data["__EVENTARGUMENT"] = ""
        html = client.post(query, data=data, cache_key=f"watch/{window}/p{page_number}", use_cache=False)
        page = parse_results_page(html, spec)

    spotted = list(found.values())
    logger.info(
        "window %s: %s listed, %s in scope", window, len(spotted), sum(s.in_scope for s in spotted)
    )
    return spotted

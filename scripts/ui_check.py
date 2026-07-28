"""Frontend holatlarini headless brauzerda tekshiradi va skrinshot oladi.

Talab: pip install playwright (brauzer: python -m playwright install chromium).
Backend http://localhost:8000 da ishlab turishi kerak. Natija: data/ui_shots/.
"""

import json
import os
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("UI_CHECK_BASE", "http://localhost:8000")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ui_shots")
os.makedirs(OUT, exist_ok=True)

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(("PASS" if ok else "FAIL"), name, detail)


def shot(page, name: str) -> None:
    page.screenshot(path=os.path.join(OUT, name))


def main() -> int:
    with urllib.request.urlopen(BASE + "/api/sessions") as r:
        sessions = json.load(r)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
        page = ctx.new_page()
        page.goto(BASE)
        page.wait_for_selector("#agents button")

        check("light theme default", page.get_attribute("html", "data-theme") == "light")
        check("welcome cards", page.locator(".sample").count() == 2)
        shot(page, "welcome-light.png")

        page.click('.theme-switch button[data-theme-pref="dark"]')
        check("dark theme", page.get_attribute("html", "data-theme") == "dark")
        shot(page, "welcome-dark.png")

        page.click("#agentic")
        check("ring toggle", page.get_attribute("#agentic", "aria-pressed") == "true")
        shot(page, "ring-on.png")
        page.click("#agentic")

        page.click("#agents-toggle")
        check(
            "agents collapse",
            page.evaluate("document.querySelector('.agents-section').classList.contains('collapsed')")
            and page.evaluate("document.querySelector('#agents').offsetHeight") == 0,
        )
        shot(page, "agents-collapsed.png")
        page.click("#agents-toggle")

        page.click("#nav-search")
        page.fill("#global-query", "soliq")
        page.wait_for_timeout(700)
        check("global search", page.locator("#search-results > *").count() > 0)
        shot(page, "search-modal.png")
        page.click("#search-close")

        page.click(".sample:has(.cat:text('Agent rejimi'))")
        check(
            "agent info modal",
            page.is_visible("#modal") and page.locator("#modal-body strong").count() > 0,
        )
        shot(page, "agent-info-modal.png")
        page.click("#modal-close")

        if sessions:
            sid = sessions[0]["id"]
            page.evaluate(f"localStorage.setItem('huquq_session_id', '{sid}')")
            page.click('.theme-switch button[data-theme-pref="light"]')
            page.reload()
            page.wait_for_selector(".msg.bot")
            check("session restored", page.locator(".msg").count() >= 2)
            check(
                "disclaimer per answer",
                page.locator(".answer-disclaimer").count() == page.locator(".msg.bot").count(),
            )
            check(
                "active session highlighted",
                page.evaluate("document.querySelector('.session-item.active')?.dataset.sessionId") == sid,
            )
            shot(page, "restored-session.png")
        else:
            print("SKIP session restore: no sessions in db")

        page.click('.theme-switch button[data-theme-pref="system"]')
        check("system pref light", page.get_attribute("html", "data-theme") == "light")
        ctx_dark = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page_dark = ctx_dark.new_page()
        page_dark.goto(BASE)
        check("system pref dark", page_dark.get_attribute("html", "data-theme") == "dark")

        browser.close()

    passed = sum(results)
    print(f"{passed}/{len(results)} passed, shots: {os.path.relpath(OUT)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

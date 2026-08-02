"""Frontend holatlarini headless brauzerda tekshiradi va skrinshot oladi.

Talab: pip install playwright (brauzer: python -m playwright install chromium).
Backend http://localhost:8000 da ishlab turishi kerak. Natija: data/ui_shots/.
"""

import json
import os
import random
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


def post(path: str, payload: dict | None = None, token: str | None = None):
    body = json.dumps(payload or {}).encode()
    request = urllib.request.Request(BASE + path, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def get_json(path: str, token: str):
    request = urllib.request.Request(BASE + path)
    request.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def ready_account() -> str:
    """An account past registration, which is what the chat screen requires."""
    token = post("/api/auth/anon")["token"]
    post("/api/auth/complete", {"name": "Toxirbek", "accept_terms": True}, token)
    return token


def seed_conversation(token: str) -> None:
    """One greeting, so the conversation row and its menu have something to act on.

    A greeting rather than a legal question: it skips retrieval and the model call is
    short, so the check does not cost a minute and a half of the daily quota.
    """
    try:
        post("/api/chat", {"question": "Salom", "stream": False}, token)
    except Exception as exc:  # noqa: BLE001 - the checks below report the consequence
        print("SEED failed:", exc)


def main() -> int:
    token = ready_account()
    if not get_json("/api/sessions", token):
        seed_conversation(token)
    sessions = get_json("/api/sessions", token)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # --- registration screen, as a first visitor sees it ---
        guest_ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
        guest = guest_ctx.new_page()
        guest.goto(BASE)
        guest.wait_for_selector(".auth-card")
        check("auth screen for a new visitor", guest.is_visible("#auth-screen"))
        check("app hidden until signed in", not guest.is_visible("#app-layout"))
        check("logo on the sign-in screen", guest.locator(".auth-logo").count() == 1)
        # outside production an unconfigured Google button stays on screen, disabled and
        # carrying the reason; a missing button reads as a broken page
        config = json.load(urllib.request.urlopen(BASE + "/api/auth/config"))
        if config["google_enabled"]:
            check("google button live", guest.is_enabled("#auth-google"))
        else:
            check("google button explains itself", guest.is_visible("#auth-google"))
            check("google button is not clickable", not guest.is_enabled("#auth-google"))
            check("reason shown", guest.is_visible("#auth-config-note"))
        check("dev sms note shown", guest.is_visible("#auth-sms-hint") == bool(config.get("sms_hint")))
        shot(guest, "auth-phone.png")

        # a fresh number each run, or the resend timer from the previous run blocks this
        digits = "90" + "".join(random.choice("0123456789") for _ in range(7))
        guest.fill("#auth-phone", digits)
        expected = f"{digits[:2]} {digits[2:5]} {digits[5:7]} {digits[7:9]}"
        check("phone is formatted while typing", guest.input_value("#auth-phone") == expected)
        check("button unlocks on a full number", guest.is_enabled("#auth-send-code"))
        guest.click("#auth-send-code")
        guest.wait_for_selector(".code-field input")
        check("code screen has six boxes", guest.locator(".code-field input").count() == 6)
        check("masked number shown", "***" in guest.inner_text("#auth-phone-masked"))
        check("resend is on a timer", not guest.is_enabled("#auth-resend"))
        shot(guest, "auth-code.png")

        # a foreign number never gets a code
        guest.click("#auth-back-method")
        guest.fill("#auth-phone", "")
        guest.fill("#auth-phone", "121234567")
        guest.click("#auth-send-code")
        guest.wait_for_selector("#auth-error-method:not([hidden])")
        check("foreign operator refused on screen", guest.is_visible("#auth-error-method"))
        shot(guest, "auth-error.png")

        # --- signed in ---
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light")
        ctx.add_init_script(f"localStorage.setItem('huquq_token', {json.dumps(token)})")
        page = ctx.new_page()
        page.goto(BASE)
        page.wait_for_selector("#agents .agent")
        check("signed in goes straight to the chat", page.is_visible("#app-layout"))

        check("light theme default", page.get_attribute("html", "data-theme") == "light")
        check("welcome cards", page.locator(".sample").count() == 2)
        check("greeted by name", "Toxirbek" in page.inner_text(".empty h1"))
        check("agent icons", page.locator(".agent .agent-icon svg").count() == 7)
        shot(page, "welcome-light.png")

        # the sidebar used to stay dark in light mode; both must now agree
        sidebar_bg = page.evaluate(
            "getComputedStyle(document.querySelector('.sidebar')).backgroundColor"
        )
        channels = [int(value) for value in sidebar_bg.replace("rgb(", "").replace(")", "").split(",")[:3]]
        check("sidebar follows the light theme", sum(channels) / 3 > 180, sidebar_bg)

        check("plan shown under the name", "Bepul" in page.inner_text("#account-plan"))
        check("daily count shown", "/5" in page.inner_text("#account-plan"))

        page.click("#open-settings")
        page.wait_for_selector(".settings-card")
        check("settings open", page.is_visible("#settings-modal"))
        check("settings panes", page.locator("#settings-nav button").count() == 5)
        shot(page, "settings-profile.png")

        page.click('#settings-nav button[data-pane="look"]')
        page.wait_for_selector('#pane-look .seg')
        page.click('#pane-look .seg button:has-text("Tungi")')
        check("dark theme from settings", page.get_attribute("html", "data-theme") == "dark")
        sidebar_dark = page.evaluate(
            "getComputedStyle(document.querySelector('.sidebar')).backgroundColor"
        )
        dark_channels = [int(v) for v in sidebar_dark.replace("rgb(", "").replace(")", "").split(",")[:3]]
        check("sidebar follows the dark theme", sum(dark_channels) / 3 < 60, sidebar_dark)
        shot(page, "settings-dark.png")

        page.click('#pane-look button:has-text("Kunduzgi")')
        page.click('#settings-nav button[data-pane="plan"]')
        page.wait_for_selector("#pane-plan .set-row")
        check("plan pane filled", page.locator("#pane-plan .set-row").count() >= 3)
        shot(page, "settings-plan.png")

        # --- pricing and checkout, reached the way a user reaches it: through settings ---
        page.click("#pane-plan .btn.primary")
        page.wait_for_selector(".plan-card")
        check("pricing modal", page.locator(".plan-card").count() == 4)
        check("owner plan hidden from pricing", "Egasi" not in page.inner_text("#plans-grid"))
        shot(page, "plans-modal.png")

        page.click('.plan-card:has-text("Standart")')
        page.wait_for_selector(".term-option")
        check("checkout opened", page.is_visible("#checkout-modal"))
        check("four terms offered", page.locator(".term-option").count() == 4)
        check("discount shown", page.locator(".term-save").count() >= 1)
        check("payment methods listed", page.locator(".pay-option").count() >= 3)
        check("unavailable methods marked", page.locator(".pay-soon").count() >= 1)
        shot(page, "checkout.png")
        page.click(".term-option:nth-child(4)")
        check("term selection sticks", page.locator(".term-option.selected").count() == 1)
        # the order button has to be reachable, not below the fold
        check("order button in view", page.is_visible(".checkout-body .auth-primary"))
        check("prices use spaces, not commas", "," not in page.inner_text(".term-total"))
        page.click(".checkout-body .auth-primary")
        page.wait_for_selector(".order-code")
        check("order placed", page.locator(".order-status.pending").count() == 1)
        check("order number shown", page.inner_text(".order-code").startswith("HQ-"))
        shot(page, "order-placed.png")

        # stepping back must land on the previous screen, not throw the user to the chat
        check("checkout offers a way back", page.is_visible("#checkout-modal .modal-back"))
        page.click("#checkout-modal .modal-back")
        page.wait_for_selector(".plan-card")
        check("back from checkout lands on pricing", page.is_visible("#plans-modal"))
        check("pricing offers a way back too", page.is_visible("#plans-modal .modal-back"))
        page.click("#plans-modal .modal-back")
        page.wait_for_selector(".settings-card")
        check("back from pricing lands in settings", page.is_visible("#settings-modal"))
        check(
            "and on the pane it was opened from",
            page.is_visible('.settings-pane[data-pane="plan"].active'),
        )

        page.click('#settings-nav button[data-pane="privacy"]')
        page.wait_for_selector("#pane-privacy .btn")
        # the privacy notice, which is the one carrying a retention table
        page.locator("#pane-privacy .btn").nth(1).click()
        page.wait_for_timeout(900)
        check("legal document opened from settings", page.is_visible("#modal"))
        check("plain language, no code blocks", page.locator("#modal-body code").count() == 0)
        check("tables render as tables", page.locator("#modal-body .md-table table").count() >= 1)
        check("quotes render as quotes", page.locator("#modal-body blockquote").count() >= 1)
        check("no raw markdown left", ">" not in page.inner_text("#modal-body").replace("→", ""))
        shot(page, "legal-doc.png")
        page.click("#modal .modal-back")
        page.wait_for_selector(".settings-card")
        check("back from a document lands in settings", page.is_visible("#settings-modal"))
        page.click("#settings-close")

        # --- conversation rows ---
        if sessions:
            sid = sessions[0]["id"]
            page.evaluate(f"localStorage.setItem('huquq_session_id', '{sid}')")
            page.reload()
            page.wait_for_selector(".msg.bot")
            check("session restored", page.locator(".msg").count() >= 2)
            check(
                "disclaimer per answer",
                page.locator(".answer-disclaimer").count() == page.locator(".msg.bot").count(),
            )
            shot(page, "restored-session.png")

            page.hover(".session-item")
            page.click(".session-item .s-menu")
            page.wait_for_selector(".row-menu")
            check("row menu opens", page.locator(".row-menu button").count() == 3)
            check("rename in menu", "nomlash" in page.inner_text(".row-menu"))
            check("pin in menu", "adash" in page.inner_text(".row-menu"))
            shot(page, "session-menu.png")
            page.keyboard.press("Escape")
        else:
            print("SKIP session row checks: no sessions in db")

        page.click("#nav-search")
        page.fill("#global-query", "soliq")
        page.wait_for_timeout(700)
        check("global search", page.locator("#search-results > *").count() > 0)
        page.click("#search-close")

        # the welcome cards only exist on an empty chat, and a session was just restored
        page.click("#new-chat")
        page.wait_for_selector(".sample")
        page.click('.sample:has(.cat:text("Agent rejimi"))')
        check(
            "agent info modal",
            page.is_visible("#modal") and page.locator("#modal-body strong").count() > 0,
        )
        page.click("#modal-close")

        # --- language ---
        page.click("#open-settings")
        page.click('#settings-nav button[data-pane="look"]')
        page.wait_for_selector("#pane-look .seg")
        page.click('#pane-look button:has-text("Русский")')
        check("russian ui", "Новый диалог" in page.inner_text("#new-chat"))
        shot(page, "settings-ru.png")
        page.click('#pane-look button:has-text("O\'zbekcha")')
        check("uzbek ui restored", "Yangi suhbat" in page.inner_text("#new-chat"))
        page.click("#settings-close")

        # --- a fresh visitor sees nobody's history ---
        anon = browser.new_context(viewport={"width": 1440, "height": 900})
        anon_page = anon.new_page()
        anon_page.goto(BASE)
        anon_page.wait_for_selector(".auth-card")
        check("fresh visitor is asked to sign in", anon_page.is_visible("#auth-screen"))

        # --- phone ---
        # the sidebar is a drawer here and everything below the fold used to be
        # unreachable, so these checks are about what a thumb can actually get to
        mob = browser.new_context(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        mob.add_init_script(f"localStorage.setItem('huquq_token', {json.dumps(token)})")
        phone = mob.new_page()
        phone.goto(BASE)
        phone.wait_for_selector("#agents .agent", state="attached")
        check(
            "no sideways scrolling on a phone",
            phone.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
        )

        phone.click("#menu-btn")
        phone.wait_for_timeout(350)
        check("drawer opens", phone.evaluate("document.querySelector('.sidebar').classList.contains('open')"))
        check("agents start folded on a phone", phone.locator(".agents-section.collapsed").count() == 1)
        check("account row reachable", phone.is_visible("#open-settings"))
        check("plan named under the account", phone.inner_text("#account-plan").strip() != "")
        check("drawer has a close button", phone.is_visible("#drawer-close"))
        shot(phone, "phone-sidebar.png")

        phone.click("#agents-toggle")
        phone.wait_for_timeout(250)
        seen = phone.evaluate(
            """() => Array.from(document.querySelectorAll('.agent')).filter((n) => {
                const r = n.getBoundingClientRect();
                return r.height > 0 && r.top >= -1 && r.bottom <= window.innerHeight + 1;
            }).length"""
        )
        check("every agent mode reachable", seen == 7, f"{seen}/7")
        # the seventh used to be printed over the conversations heading
        overlap = phone.evaluate(
            """() => {
                const last = Array.from(document.querySelectorAll('.agent')).pop();
                const head = document.querySelector('.sessions-section .side-title');
                if (!last || !head) return false;
                const a = last.getBoundingClientRect(), b = head.getBoundingClientRect();
                return a.bottom > b.top + 1 && a.top < b.bottom - 1;
            }"""
        )
        check("no overlap between agents and conversations", not overlap)
        phone.locator(".agent").last.click()
        check("last agent selects", phone.locator(".agent.active").count() == 1)

        phone.click("#menu-btn")
        phone.wait_for_timeout(350)
        # the close button, not the grey area, is how a drawer is meant to be dismissed
        phone.click("#drawer-close")
        phone.wait_for_timeout(350)
        check(
            "close button shuts the drawer",
            not phone.evaluate("document.querySelector('.sidebar').classList.contains('open')"),
        )

        phone.click("#menu-btn")
        phone.wait_for_timeout(350)
        phone.click("#open-settings")
        phone.wait_for_selector(".settings-card")
        phone.click('#settings-nav button[data-pane="plan"]')
        phone.wait_for_selector("#pane-plan .btn.primary")
        phone.click("#pane-plan .btn.primary")
        phone.wait_for_selector(".plan-card")
        grid = phone.evaluate(
            """() => { const g = document.querySelector('.plans-grid');
                return {scroll: g.scrollHeight > g.clientHeight,
                        can: ['auto','scroll'].includes(getComputedStyle(g).overflowY)}; }"""
        )
        check("pricing scrolls on a phone", (not grid["scroll"]) or grid["can"])
        shot(phone, "phone-plans.png")
        phone.click("#plans-close")

        browser.close()

    passed = sum(results)
    print(f"{passed}/{len(results)} passed, shots: {os.path.relpath(OUT)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

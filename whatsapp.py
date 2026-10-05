"""WhatsApp Web automation with a persistent Chrome profile.

The Chrome profile in SESSION_DIR keeps the WhatsApp Web login, so the QR
code only has to be scanned once (until the phone unlinks the device).
"""
import logging
import os
import sys
import time
import unicodedata

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

import config

log = logging.getLogger(__name__)

WA_URL = "https://web.whatsapp.com/"

# WhatsApp Web changes its markup now and then, so each element has a few
# candidate selectors. The first one found wins.
SEL_LOGGED_IN = ["#pane-side", "div[aria-label='Chat list']", "div[data-testid='chat-list']"]
SEL_QR = ["canvas[aria-label*='Scan']", "div[data-ref] canvas", "[data-testid='qrcode']"]
SEL_SEARCH = [
    "div[contenteditable='true'][data-tab='3']",
    "div[role='textbox'][aria-label*='Search']",
    "input[aria-label*='Search']",
    "input[role='textbox']",
]
SEL_COMPOSE = [
    "#main footer div[contenteditable='true']",
    "div[contenteditable='true'][data-tab='10']",
    "div[aria-label^='Type a message']",
]
SEL_PENDING = "#main span[data-icon='msg-time']"
SEL_DIALOG = "div[role='dialog'], div[data-animate-modal-popup='true']"
# Buttons that close WhatsApp's "What's new", notification and tips popups.
DISMISS_TEXTS = ["OK", "Got it", "Continue", "Not now", "Close", "Skip",
                 "Dismiss", "Later", "Maybe later", "No thanks"]

# Paste text into the compose box the way a real clipboard paste would.
# This keeps line breaks and emoji, which send_keys cannot type.
PASTE_JS = """
const el = arguments[0], text = arguments[1];
el.focus();
const dt = new DataTransfer();
dt.setData('text/plain', text);
el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
"""

IS_LINUX = sys.platform.startswith("linux")
HEADLESS_UA = (
    "Mozilla/5.0 (" + ("X11; Linux x86_64" if IS_LINUX else "Windows NT 10.0; Win64; x64") + ") "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
)
# The QR code's text lives in this attribute; used to draw it in a terminal.
SEL_QR_DATA = "div[data-ref]"


class WhatsAppError(RuntimeError):
    pass


def _first(driver, selectors):
    for sel in selectors:
        found = driver.find_elements(By.CSS_SELECTOR, sel)
        if found:
            return found[0]
    return None


def _wait_first(driver, selectors, timeout):
    try:
        return WebDriverWait(driver, timeout, poll_frequency=0.5).until(
            lambda d: _first(d, selectors)
        )
    except TimeoutException:
        return None


class WhatsApp:
    def __init__(self, headless: bool | None = None):
        self.headless = config.HEADLESS if headless is None else headless
        # A Linux server has no screen, so Chrome must run headless there.
        if IS_LINUX and not os.environ.get("DISPLAY"):
            self.headless = True
        self.driver = None

    # ── lifecycle ──────────────────────────────────────────
    def start(self):
        config.SESSION_DIR.mkdir(parents=True, exist_ok=True)
        opts = webdriver.ChromeOptions()
        opts.add_argument(f"--user-data-dir={config.SESSION_DIR}")
        opts.add_argument("--profile-directory=Default")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        if self.headless:
            opts.add_argument("--headless=new")
            # WhatsApp refuses browsers that announce "HeadlessChrome".
            opts.add_argument(f"--user-agent={HEADLESS_UA}")
        if IS_LINUX:
            # Needed when Chrome runs as root / inside small VMs and containers.
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")
        _clear_stale_chrome()
        try:
            self.driver = webdriver.Chrome(options=opts)
        except WebDriverException as exc:
            raise WhatsAppError(
                "Could not start Chrome. Close any Chrome window that is using the "
                f"'{config.SESSION_DIR.name}' profile and try again.\n{exc.msg}"
            ) from exc
        # Without these, a stuck page or script blocks the bot forever.
        self.driver.set_page_load_timeout(120)
        self.driver.set_script_timeout(60)
        self.driver.get(WA_URL)

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            finally:
                self.driver = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # ── login ──────────────────────────────────────────────
    def wait_until_logged_in(self, timeout: int) -> bool:
        return _wait_first(self.driver, SEL_LOGGED_IN, timeout) is not None

    def login_interactive(self, timeout: int = 300) -> bool:
        """Show the QR code and wait for it to be scanned."""
        if self.wait_until_logged_in(60):
            log.info("Already logged in - saved session is valid.")
            return True
        where = "below (and in logs/qr.png)" if self.headless else "in the Chrome window"
        log.info("Scan the QR code %s with WhatsApp on 63792 29627 "
                 "(Settings > Linked devices > Link a device).", where)
        deadline = time.time() + timeout
        last_ref = None
        while time.time() < deadline:
            if _first(self.driver, SEL_LOGGED_IN):
                break
            if self.headless:
                last_ref = self._show_qr(last_ref)
            time.sleep(2)
        else:
            return False
        # Give WhatsApp a moment to finish writing the session to disk.
        time.sleep(10)
        return True

    def _show_qr(self, last_ref):
        """Draw the QR in the terminal and save it to logs/qr.png whenever it changes.

        WhatsApp replaces the QR about every 20 seconds.
        """
        el = _first(self.driver, [SEL_QR_DATA])
        ref = el.get_attribute("data-ref") if el else None
        if not ref or ref == last_ref:
            return last_ref
        config.LOG_DIR.mkdir(exist_ok=True)
        # Save just the QR (with its white margin) so it scans easily from a
        # picture; fall back to the whole page.
        try:
            el.screenshot(str(config.LOG_DIR / "qr.png"))
        except WebDriverException:
            self.screenshot(config.LOG_DIR / "qr.png")
        try:
            import qrcode
            qr = qrcode.QRCode(border=2)
            qr.add_data(ref)
            print("\n")
            qr.print_ascii(invert=True)
            print("New QR code - scan it now (it changes every ~20 s).", flush=True)
        except ImportError:
            log.info("QR saved to logs/qr.png (pip install qrcode to see it in the terminal).")
        return ref

    def ensure_logged_in(self, timeout: int = 90):
        if self.wait_until_logged_in(timeout):
            return
        if _first(self.driver, SEL_QR):
            raise WhatsAppError(
                "WhatsApp session has expired - run `python main.py login` and scan the QR again."
            )
        raise WhatsAppError("WhatsApp Web did not finish loading.")

    # ── popups ─────────────────────────────────────────────
    def dismiss_popups(self, rounds: int = 4):
        """Close any modal dialog covering the page."""
        d = self.driver
        for _ in range(rounds):
            dialogs = [x for x in d.find_elements(By.CSS_SELECTOR, SEL_DIALOG) if x.is_displayed()]
            if not dialogs:
                return
            dlg = dialogs[0]
            log.info("Closing popup: %s", " ".join(dlg.text.split())[:120] or "(no text)")
            if not self._click_dismiss_button(dlg):
                d.switch_to.active_element.send_keys(Keys.ESCAPE)
            time.sleep(1.5)

    def _click_dismiss_button(self, dlg) -> bool:
        for btn in dlg.find_elements(By.CSS_SELECTOR, "button, div[role='button']"):
            label = (btn.text or btn.get_attribute("aria-label") or "").strip()
            if label.lower() in (t.lower() for t in DISMISS_TEXTS) and btn.is_displayed():
                try:
                    btn.click()
                except WebDriverException:
                    self.driver.execute_script("arguments[0].click();", btn)
                return True
        return False

    def _click(self, el):
        """Click, closing a popup first if one is in the way."""
        try:
            el.click()
        except ElementClickInterceptedException:
            self.dismiss_popups()
            try:
                el.click()
            except ElementClickInterceptedException:
                self.driver.execute_script("arguments[0].focus(); arguments[0].click();", el)

    def screenshot(self, path):
        try:
            self.driver.save_screenshot(str(path))
            return True
        except Exception:
            return False

    # ── sending ────────────────────────────────────────────
    def open_chat(self, name: str):
        d = self.driver
        # On a slow server the chat list can take a while, and popups can keep
        # appearing, so keep closing them until the search box shows up.
        search = None
        deadline = time.time() + 90
        while search is None and time.time() < deadline:
            time.sleep(3)
            self.dismiss_popups()
            search = _first(d, SEL_SEARCH)
        if search is None:
            raise WhatsAppError("Could not find the WhatsApp search box.")
        self._click(search)
        search.send_keys(Keys.CONTROL, "a")
        search.send_keys(Keys.BACKSPACE)
        search.send_keys(name)

        # Group names often use styled Unicode letters (e.g. 𝙰𝙱𝙸 𝙻𝙰𝚆 𝙵𝙸𝚁𝙼),
        # so compare normalised titles rather than exact text.
        target = _norm(name)
        time.sleep(2)  # let the search results finish re-rendering
        # Results can re-render under us (stale element), so find and click
        # in a loop until the click lands.
        for attempt in range(5):
            try:
                chat = WebDriverWait(d, 20, poll_frequency=0.5).until(
                    lambda _: self._find_title(target, "#pane-side span[title], #side span[title]")
                )
            except TimeoutException:
                raise WhatsAppError(f"Chat '{name}' not found. Check GROUP_NAME in .env.")
            try:
                self._click(chat)
                break
            except StaleElementReferenceException:
                time.sleep(1)
        else:
            raise WhatsAppError(f"Could not click chat '{name}' (list kept changing).")

        try:
            WebDriverWait(d, 15, poll_frequency=0.5).until(
                lambda _: self._find_title(target, "#main header span[title], #main header span[dir='auto']")
            )
        except TimeoutException:
            raise WhatsAppError(f"Opened a chat, but it does not look like '{name}'.")

    def _find_title(self, target: str, css: str):
        for el in self.driver.find_elements(By.CSS_SELECTOR, css):
            try:
                title = el.get_attribute("title") or el.text
            except WebDriverException:
                continue
            if _norm(title) == target:
                return el
        return None

    def send_message(self, text: str):
        d = self.driver
        box = _wait_first(d, SEL_COMPOSE, 20)
        if box is None:
            raise WhatsAppError("Could not find the message box (are you still a member of the group?).")

        self._click(box)
        d.execute_script(PASTE_JS, box, text)
        time.sleep(1)

        if not box.text.strip():
            # Paste was ignored - fall back to typing, Shift+Enter per line.
            log.warning("Paste did not take - typing the message instead.")
            for i, line in enumerate(text.split("\n")):
                if i:
                    box.send_keys(Keys.SHIFT, Keys.ENTER)
                if line:
                    box.send_keys(_bmp_only(line))
            time.sleep(1)

        # Click the green Send button if present, otherwise fall back to ENTER
        time.sleep(0.5)
        send_btn = d.find_elements(
            By.CSS_SELECTOR,
            "button[aria-label='Send'], span[data-icon='send'], button:has(span[data-icon='send'])"
        )
        if send_btn:
            d.execute_script("arguments[0].click();", send_btn[0])
        else:
            box.send_keys(Keys.ENTER)

        # Wait for the box to clear and for the "clock" (pending) tick to go.
        try:
            WebDriverWait(d, 20).until(lambda _: not box.text.strip())
        except TimeoutException:
            raise WhatsAppError("Message did not send (text still in the box).")
        try:
            WebDriverWait(d, 60).until(
                lambda _: not d.find_elements(By.CSS_SELECTOR, SEL_PENDING)
            )
        except TimeoutException:
            raise WhatsAppError("Message is still pending after 60s - check the phone's internet.")
        time.sleep(2)


def _norm(s: str) -> str:
    """'𝙰𝙱𝙸  𝙻𝙰𝚆 𝙵𝙸𝚁𝙼' -> 'abi law firm'."""
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) not in ("Cf", "Mn"))
    return " ".join(s.split()).casefold()


def _bmp_only(s: str) -> str:
    # ChromeDriver's send_keys cannot type characters outside the BMP (emoji).
    return "".join(ch for ch in s if ord(ch) <= 0xFFFF)


def _clear_stale_chrome():
    """Kill Chrome left over from a crashed run and drop its profile lock.

    A leftover Chrome keeps SESSION_DIR locked, and every later start fails
    with "user data directory is already in use".
    """
    if not IS_LINUX:
        return
    import subprocess
    subprocess.run(["pkill", "-9", "-f", f"user-data-dir={config.SESSION_DIR}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            os.remove(config.SESSION_DIR / name)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Could not remove %s: %s", name, exc)

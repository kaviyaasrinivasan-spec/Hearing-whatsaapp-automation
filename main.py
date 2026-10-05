"""ABI LAW FIRM - next-day hearing reminders on WhatsApp.

Commands
  python main.py login                 scan the QR once and save the session
  python main.py preview [--date D]    print the message without sending
  python main.py send [--date D]       send now (default: tomorrow's hearings)
  python main.py check                 test login + group, sends nothing
  python main.py run                   stay running and send every day at SEND_TIME
"""
import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from selenium.common.exceptions import WebDriverException

import config
from cases_api import CasesApiError, fetch_hearings
from message import build_empty_message, build_messages
from whatsapp import WhatsApp, WhatsAppError

log = logging.getLogger("hearing-bot")


def setup_logging():
    # Windows consoles default to cp1252, which cannot print styled names.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(config.LOG_DIR / "automation.log", maxBytes=1_000_000,
                             backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.ERROR)


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def tomorrow() -> str:
    return (now_local() + timedelta(days=1)).strftime("%Y-%m-%d")


# ── sent log: stops a second send for the same day ─────────
# {"2026-09-25": {"done": true, "sent_at": "...", "count": 2, "sent": ["143", "150"]}}
def _load_sent() -> dict:
    try:
        return json.loads(config.SENT_LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _day_done(day: str) -> bool:
    entry = _load_sent().get(day)
    # Entries written before per-case tracking have no "done" key.
    return bool(entry) and entry.get("done", True)


def _record(day: str, key: str | None = None, count: int | None = None, done: bool = False):
    sent = _load_sent()
    entry = sent.setdefault(day, {"done": False, "sent": []})
    entry.setdefault("sent", [])
    if key is not None and key not in entry["sent"]:
        entry["sent"].append(key)
    if count is not None:
        entry["count"] = count
    entry["done"] = done or entry.get("done", False)
    entry["sent_at"] = now_local().isoformat(timespec="seconds")
    config.SENT_LOG.write_text(json.dumps(sent, indent=2), encoding="utf-8")


# ── commands ───────────────────────────────────────────────
def get_messages(day: str) -> tuple[list[tuple[str, str]], int]:
    payload = fetch_hearings(day)
    count = payload.get("count", 0)
    messages = build_messages(payload)
    if not messages and config.SEND_WHEN_EMPTY:
        messages = [("empty", build_empty_message(payload))]
    return messages, count


def cmd_login(_args) -> int:
    with WhatsApp() as wa:
        if wa.login_interactive():
            log.info("Logged in. Session saved in %s", config.SESSION_DIR)
            return 0
    log.error("QR code was not scanned in time.")
    return 1


def cmd_check(_args) -> int:
    """Log in and open the group without sending anything."""
    with WhatsApp() as wa:
        wa.ensure_logged_in()
        wa.open_chat(config.GROUP_NAME)
    log.info("Check OK - logged in and '%s' opens. Nothing was sent.", config.GROUP_NAME)
    return 0


def cmd_preview(args) -> int:
    day = args.date or tomorrow()
    messages, count = get_messages(day)
    print(f"--- {count} hearing(s) on {day}: {len(messages)} message(s) ---")
    if not messages:
        print("(nothing would be sent)")
    for n, (_key, text) in enumerate(messages, 1):
        print(f"\n===== message {n} =====")
        print(text)
    return 0


def cmd_send(args) -> int:
    day = args.date or tomorrow()
    if _day_done(day) and not args.force:
        log.info("Hearings for %s were already sent (%s). Use --force to resend.",
                 day, _load_sent()[day].get("sent_at"))
        return 0

    messages, count = get_messages(day)
    log.info("%d hearing(s) on %s", count, day)
    if not messages:
        log.info("No hearings and SEND_WHEN_EMPTY=false - nothing to send.")
        return 0

    if args.force:
        # Start this date afresh.
        sent = _load_sent()
        sent.pop(day, None)
        config.SENT_LOG.write_text(json.dumps(sent, indent=2), encoding="utf-8")

    for attempt in (1, 2):
        already = set(_load_sent().get(day, {}).get("sent", []))
        pending = [(k, t) for k, t in messages if k not in already]
        if already:
            log.info("%d of %d message(s) already sent - sending the rest.",
                     len(messages) - len(pending), len(messages))
        wa = WhatsApp()
        try:
            wa.start()
            wa.ensure_logged_in()
            wa.open_chat(config.GROUP_NAME)
            for key, text in pending:
                wa.send_message(text)
                _record(day, key=key, count=count)
                log.info("Sent message %d of %d.", messages.index((key, text)) + 1, len(messages))
                time.sleep(2)
            _record(day, count=count, done=True)
            log.info("Sent %d hearing(s) for %s to '%s'.", count, day, config.GROUP_NAME)
            return 0
        except (WhatsAppError, WebDriverException) as exc:
            msg = getattr(exc, "msg", None) or str(exc)
            log.error("Attempt %d failed: %s", attempt, msg.splitlines()[0] if msg else exc)
            shot = config.LOG_DIR / f"error_{now_local():%Y%m%d_%H%M%S}.png"
            if wa.driver and wa.screenshot(shot):
                log.error("Screenshot saved: %s", shot)
            if "expired" in str(exc):
                break
            time.sleep(15)
        finally:
            wa.close()
    return 1


# If the 8 PM send fails, keep retrying this often until LAST_RETRY_HOUR.
RETRY_EVERY_MIN = 15
LAST_RETRY_HOUR = 23
# One send (all messages) must finish within this, or it is killed.
SEND_TIMEOUT_SEC = 20 * 60


def cmd_run(_args) -> int:
    hh, mm = (int(x) for x in config.SEND_TIME.split(":"))
    log.info("Scheduler started - sending every day at %s %s.", config.SEND_TIME, config.TIMEZONE)
    while True:
        now = now_local()
        slot = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        in_window = slot <= now and now.hour < LAST_RETRY_HOUR

        if in_window and not _day_done(tomorrow()):
            # Covers the 8 PM send, a restart after 8 PM, and retries after a failure.
            _safe_send()
            if not _day_done(tomorrow()):
                log.warning("Hearings for %s not sent yet - retrying in %d min.",
                            tomorrow(), RETRY_EVERY_MIN)
                _sleep_until(now_local() + timedelta(minutes=RETRY_EVERY_MIN))
                continue

        target = slot if now < slot else slot + timedelta(days=1)
        log.info("Next run at %s", target.strftime("%Y-%m-%d %H:%M"))
        _sleep_until(target)


def _sleep_until(target: datetime):
    # Short steps, so a clock change or a suspended VM still wakes on time.
    while (wait := (target - now_local()).total_seconds()) > 0:
        time.sleep(min(wait, 60))


def _safe_send():
    """Run one send in a child process, so a hung Chrome cannot freeze the scheduler."""
    cmd = [sys.executable, str(config.BASE_DIR / "main.py"), "send"]
    try:
        result = subprocess.run(cmd, cwd=config.BASE_DIR, timeout=SEND_TIMEOUT_SEC)
        if result.returncode:
            log.error("Send exited with code %d.", result.returncode)
    except subprocess.TimeoutExpired:
        log.error("Send did not finish in %d min - killed it.", SEND_TIMEOUT_SEC // 60)
    except Exception:
        log.exception("Unexpected error starting the send")


def main() -> int:
    setup_logging()
    p = argparse.ArgumentParser(description="ABI LAW FIRM hearing reminders on WhatsApp")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="scan the QR once and save the session")
    for name in ("preview", "send"):
        sp = sub.add_parser(name)
        sp.add_argument("--date", help="YYYY-MM-DD (default: tomorrow)")
        if name == "send":
            sp.add_argument("--force", action="store_true", help="resend even if already sent")
    sub.add_parser("run", help="run forever, sending daily at SEND_TIME")
    sub.add_parser("check", help="test the WhatsApp session and group without sending")
    args = p.parse_args()

    handler = {"login": cmd_login, "preview": cmd_preview,
               "send": cmd_send, "run": cmd_run, "check": cmd_check}[args.cmd]
    try:
        return handler(args)
    except CasesApiError as exc:
        log.error("%s", exc)
        return 1
    except WhatsAppError as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

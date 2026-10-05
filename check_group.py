"""Read-only check: which account is logged in, and what did the bot post
around 8 PM on 27 and 28 Sep. Sends nothing.

    HEADLESS=true venv/bin/python check_group.py
"""
import re
import subprocess
import sys
import time

from selenium.webdriver.common.by import By

import config
from whatsapp import WhatsApp

if sys.platform.startswith("linux"):
    subprocess.run(["pkill", "-9", "-f", "whatsapp_session"])

pat = re.compile(r"\[(7:5\d|8:0\d|8:1\d) pm, 2[78]/9/2026\]")
sel = "#main div[data-pre-plain-text]"

wa = WhatsApp(headless=True)
wa.start()
try:
    wa.ensure_logged_in()
    d = wa.driver
    print("Logged in as:", d.execute_script(
        "return localStorage.getItem('last-wid-md') || localStorage.getItem('last-wid')"))
    wa.open_chat(config.GROUP_NAME)
    time.sleep(6)

    # Scroll up until 27 Sep is on screen.
    for _ in range(25):
        msgs = d.find_elements(By.CSS_SELECTOR, sel)
        if any("27/9/2026" in (m.get_attribute("data-pre-plain-text") or "") for m in msgs[:3]):
            break
        d.execute_script("arguments[0].scrollIntoView();", msgs[0])
        time.sleep(2)

    hits = 0
    for m in d.find_elements(By.CSS_SELECTOR, sel):
        pre = m.get_attribute("data-pre-plain-text") or ""
        if not pat.search(pre):
            continue
        hits += 1
        row = m.find_elements(By.XPATH, "./ancestor::div[contains(@class,'message-')][1]")
        box = row[0] if row else m
        side = "OUT (sent by this account)" if "message-out" in (box.get_attribute("class") or "") else "IN"
        icons = [i.get_attribute("data-icon") for i in box.find_elements(By.CSS_SELECTOR, "span[data-icon]")]
        print("-----", pre, side, icons)
        print(m.text[:100].replace("\n", " | "))
    print("messages 7:50-8:19 pm on 27/28 Sep:", hits)
    wa.screenshot(config.LOG_DIR / "group_check.png")
finally:
    wa.close()
